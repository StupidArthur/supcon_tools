package bindings

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// 创建一个模拟命令
func makeMockCommand(exitCode int, stdout, stderr string) commandFactory {
	return func(name string, arg ...string) *exec.Cmd {
		cs := []string{"-test.run=TestHelperProcess", "--", name}
		cs = append(cs, arg...)
		cmd := exec.Command(os.Args[0], cs...)
		cmd.Env = []string{
			"GO_WANT_HELPER_PROCESS=1",
			fmt.Sprintf("HELPER_EXIT_CODE=%d", exitCode),
			fmt.Sprintf("HELPER_STDOUT=%s", stdout),
			fmt.Sprintf("HELPER_STDERR=%s", stderr),
		}
		return cmd
	}
}

// 创建一个持续运行的模拟命令
func makeLongRunningCommand(sleepSeconds int) commandFactory {
	return func(name string, arg ...string) *exec.Cmd {
		cs := []string{"-test.run=TestHelperProcess", "--", name}
		cs = append(cs, arg...)
		cmd := exec.Command(os.Args[0], cs...)
		cmd.Env = []string{
			"GO_WANT_HELPER_PROCESS=1",
			"HELPER_EXIT_CODE=0",
			fmt.Sprintf("HELPER_SLEEP=%d", sleepSeconds),
		}
		return cmd
	}
}

// 创建模拟的 readiness checker
func makeMockReadinessChecker(readyAfterCalls int, instanceName string) (readinessChecker, func() int32) {
	var callCount atomic.Int32
	checker := func(ctx context.Context, apiHost string, apiPort int) (bool, string, error) {
		count := callCount.Add(1)
		if int(count) >= readyAfterCalls {
			return true, instanceName, nil
		}
		return false, "", nil
	}
	return checker, func() int32 { return callCount.Load() }
}

func waitForStatus(t *testing.T, b *SystemBinding, predicate func(SystemStatus) bool) SystemStatus {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		status := b.Status()
		if predicate(status) {
			return status
		}
		time.Sleep(10 * time.Millisecond)
	}
	status := b.Status()
	t.Fatalf("等待状态超时，最终状态: %+v", status)
	return SystemStatus{}
}

func TestBuildArgs(t *testing.T) {
	tests := []struct {
		name     string
		params   StartParams
		expected []string
	}{
		{
			name: "完整参数",
			params: StartParams{
				ConfigPath:  "config/test.yaml",
				Mode:        "REALTIME",
				CycleTime:   0.5,
				Port:        4840,
				APIPort:     8000,
				APIHost:     "127.0.0.1",
				RuntimeName: "test-instance",
				EnableOpcUa: true,
			},
			expected: []string{
				"-c", "config/test.yaml",
				"--mode", "REALTIME",
				"--cycle-time", "0.5",
				"--port", "4840",
				"--api",
				"--api-host", "127.0.0.1",
				"--api-port", "8000",
				"--name", "test-instance",
			},
		},
		{
			name: "只有必要参数",
			params: StartParams{
				ConfigPath: "config/test.yaml",
			},
			expected: []string{"-c", "config/test.yaml", "--api"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			args := BuildArgs(tt.params)
			if len(args) != len(tt.expected) {
				t.Errorf("参数数量不匹配: got %d, want %d\n  got:  %v\n  want: %v",
					len(args), len(tt.expected), args, tt.expected)
				return
			}
			for i, arg := range args {
				if arg != tt.expected[i] {
					t.Errorf("参数[%d]不匹配: got %q, want %q", i, arg, tt.expected[i])
				}
			}
		})
	}
}

func TestBuildArgs_ContainsAllRequired(t *testing.T) {
	params := StartParams{
		ConfigPath:  "test.yaml",
		Mode:        "REALTIME",
		CycleTime:   0.5,
		Port:        18951,
		APIPort:     8000,
		APIHost:     "127.0.0.1",
		RuntimeName: "second_order_tank",
		EnableOpcUa: true,
	}
	args := BuildArgs(params)
	argsStr := strings.Join(args, " ")

	requiredArgs := []string{"--name", "--mode", "--cycle-time", "--port", "--api", "--api-host", "--api-port"}
	for _, required := range requiredArgs {
		if !strings.Contains(argsStr, required) {
			t.Errorf("参数缺少 %q", required)
		}
	}

	// 验证具体值
	for i, arg := range args {
		switch arg {
		case "--name":
			if i+1 < len(args) && args[i+1] != "second_order_tank" {
				t.Errorf("--name 值不匹配: got %q, want %q", args[i+1], "second_order_tank")
			}
		case "--port":
			if i+1 < len(args) && args[i+1] != "18951" {
				t.Errorf("--port 值不匹配: got %q, want %q", args[i+1], "18951")
			}
		case "--api-port":
			if i+1 < len(args) && args[i+1] != "8000" {
				t.Errorf("--api-port 值不匹配: got %q, want %q", args[i+1], "8000")
			}
		}
	}
}

func TestBuildArgs_PortAlwaysIncluded(t *testing.T) {
	// standalone_main.py 不支持关闭 OPC UA，port 始终传递
	params := StartParams{
		ConfigPath:  "test.yaml",
		Port:        18951,
		EnableOpcUa: false, // 即使 false 也传递
	}
	args := BuildArgs(params)

	hasPort := false
	for i, arg := range args {
		if arg == "--port" && i+1 < len(args) {
			hasPort = true
		}
	}

	if !hasPort {
		t.Error("port 参数应该始终包含（standalone_main.py 不支持关闭 OPC UA）")
	}
}

func TestStart_ReadySuccess(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(2, "test-runtime")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test-runtime",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	status := b.Status()
	if !status.Running {
		t.Error("进程应该在运行")
	}
	if !status.APIReady {
		t.Error("API 应该已经 ready")
	}
	if status.RuntimeName != "test-runtime" {
		t.Errorf("RuntimeName 不匹配: got %q, want %q", status.RuntimeName, "test-runtime")
	}

	b.Cleanup()
}

func TestStatus_APIReadyOnlyAfterReadinessMatch(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)
	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(10 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	var ready atomic.Bool
	b.setReadinessChecker(func(context.Context, string, int) (bool, string, error) {
		if ready.Load() {
			return true, "test-runtime", nil
		}
		return false, "", nil
	})

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)
	startDone := make(chan error, 1)
	go func() {
		startDone <- b.Start(StartParams{ConfigPath: configPath, APIPort: 8000, RuntimeName: "test-runtime"})
	}()

	status := waitForStatus(t, b, func(s SystemStatus) bool { return s.Running })
	if status.APIReady {
		t.Fatal("readiness 尚未匹配时 apiReady 不得为 true")
	}

	ready.Store(true)
	select {
	case err := <-startDone:
		if err != nil {
			t.Fatalf("Start 失败: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("ready 后 Start 未返回")
	}

	status = b.Status()
	if !status.Running || !status.APIReady {
		t.Fatalf("ready 后状态不正确: %+v", status)
	}
	b.Cleanup()
}

func TestStart_InstanceNameMismatch(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "wrong-name")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test-runtime",
	})
	if err == nil {
		t.Fatal("应该返回错误")
	}
	if !strings.Contains(err.Error(), "instance_name 不匹配") {
		t.Errorf("错误消息不匹配: %v", err)
	}

	// 验证进程已退出
	time.Sleep(100 * time.Millisecond)
	status := b.Status()
	if status.Running {
		t.Error("进程应该已经退出")
	}
}

func TestStart_ReadyTimeout(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(500 * time.Millisecond)

	b.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int) (bool, string, error) {
		return false, "", nil
	})

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	start := time.Now()
	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test-runtime",
	})
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("应该返回错误")
	}
	if !strings.Contains(err.Error(), "API ready 超时") {
		t.Errorf("错误消息不匹配: %v", err)
	}
	// 超时应该在 500ms 左右，加上进程退出等待时间
	if elapsed > 10*time.Second {
		t.Errorf("超时时间过长: %v", elapsed)
	}

	// 验证进程已退出
	time.Sleep(100 * time.Millisecond)
	status := b.Status()
	if status.Running {
		t.Error("进程应该已经退出")
	}
}

func TestStart_ProcessExitBeforeReady(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeMockCommand(42, "some output", "error occurred"))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err == nil {
		t.Fatal("应该返回错误")
	}
	// 验证错误包含 exit code
	if !strings.Contains(err.Error(), "42") {
		t.Errorf("应该包含 exit code 42: %v", err)
	}
	// 验证错误包含 stderr
	if !strings.Contains(err.Error(), "error occurred") {
		t.Errorf("应该包含 stderr: %v", err)
	}

	// 验证进程已退出
	time.Sleep(100 * time.Millisecond)
	status := b.Status()
	if status.Running {
		t.Error("进程应该已经退出")
	}
}

func TestStart_DuplicateStart(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	// 第一次启动
	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("第一次 Start 失败: %v", err)
	}

	// 第二次启动应该失败
	err = b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8001,
		RuntimeName: "test2",
	})
	if err == nil {
		t.Fatal("重复启动应该失败")
	}

	b.Cleanup()
}

func TestStart_ConcurrentStart(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	// 使用 barrier 同步两个 goroutine
	var barrier sync.WaitGroup
	barrier.Add(2)

	var wg sync.WaitGroup
	wg.Add(2)

	results := make([]error, 2)

	for i := 0; i < 2; i++ {
		go func(idx int) {
			defer wg.Done()
			barrier.Done() // 准备就绪
			barrier.Wait() // 等待另一个 goroutine

			results[idx] = b.Start(StartParams{
				ConfigPath:  configPath,
				APIPort:     8000,
				RuntimeName: "test",
			})
		}(i)
	}

	wg.Wait()

	// 只有一个应该成功
	successCount := 0
	for _, err := range results {
		if err == nil {
			successCount++
		}
	}

	if successCount != 1 {
		t.Errorf("应该恰好一个 Start 成功，实际 %d 个成功", successCount)
	}

	b.Cleanup()
}

func TestStop_GracefulExit(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)
	b.setStopTimeout(3 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	started := time.Now()
	err = b.Stop()
	if err != nil {
		t.Fatalf("Stop 失败: %v", err)
	}
	if elapsed := time.Since(started); elapsed >= 2*time.Second {
		t.Fatalf("Stop 不应在 Interrupt 不受支持时等待完整超时，实际耗时 %v", elapsed)
	}

	status := b.Status()
	if status.Running {
		t.Error("进程应该已经停止")
	}
}

func TestStop_DuplicateStop(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)
	b.setStopTimeout(3 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	// 第一次 Stop
	err = b.Stop()
	if err != nil {
		t.Fatalf("第一次 Stop 失败: %v", err)
	}

	// 第二次 Stop 应该返回错误
	err = b.Stop()
	if err == nil {
		t.Fatal("重复 Stop 应该返回错误")
	}
}

func TestStop_NotRunning(t *testing.T) {
	b := NewSystemBinding()

	err := b.Stop()
	if err == nil {
		t.Fatal("停止未运行的进程应该返回错误")
	}
}

func TestCleanup(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	b.Cleanup()

	status := b.Status()
	if status.Running {
		t.Error("进程应该已经停止")
	}
}

func TestCleanup_NotRunning(t *testing.T) {
	b := NewSystemBinding()
	b.Cleanup() // 不应该 panic
}

func TestProcessExit_AfterReady(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	// 进程运行 2 秒后退出
	b.setCommandFactory(makeLongRunningCommand(2))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	// 验证 ready 后状态
	status := b.Status()
	if !status.Running || !status.APIReady {
		t.Error("进程应该在运行且 API ready")
	}

	// 等待进程退出
	time.Sleep(3 * time.Second)

	// 验证进程退出后状态自动更新
	status = b.Status()
	if status.Running {
		t.Error("进程应该已经退出")
	}
	if status.APIReady {
		t.Error("API 应该不再是 ready")
	}
	if status.LastError == "" {
		t.Error("意外退出后应保留 lastError")
	}

	// 退出后的 proc 必须已经释放，允许再次启动。
	err = b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("进程退出后应允许再次 Start: %v", err)
	}
	b.Cleanup()
}

func TestFileHashSHA256_DifferentContent(t *testing.T) {
	tmpDir := t.TempDir()

	file1 := filepath.Join(tmpDir, "file1.yaml")
	file2 := filepath.Join(tmpDir, "file2.yaml")

	// 相同长度但不同内容
	os.WriteFile(file1, []byte("content_a"), 0644)
	os.WriteFile(file2, []byte("content_b"), 0644)

	hash1, _ := fileHashSHA256(file1)
	hash2, _ := fileHashSHA256(file2)

	if hash1 == hash2 {
		t.Error("不同内容应该有不同的 hash")
	}
}

func TestFileHashSHA256_SameContent(t *testing.T) {
	tmpDir := t.TempDir()

	file1 := filepath.Join(tmpDir, "file1.yaml")
	file2 := filepath.Join(tmpDir, "file2.yaml")

	content := []byte("same content")
	os.WriteFile(file1, content, 0644)
	os.WriteFile(file2, content, 0644)

	hash1, _ := fileHashSHA256(file1)
	hash2, _ := fileHashSHA256(file2)

	if hash1 != hash2 {
		t.Error("相同内容应该有相同的 hash")
	}
}

func TestStart_UnicodePath(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "测试实例")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "配置文件.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "测试实例",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	status := b.Status()
	if status.ConfigPath != configPath {
		t.Errorf("ConfigPath 不匹配: got %q, want %q", status.ConfigPath, configPath)
	}
	if status.RuntimeName != "测试实例" {
		t.Errorf("RuntimeName 不匹配: got %q, want %q", status.RuntimeName, "测试实例")
	}

	b.Cleanup()
}

func TestStart_WithHTTPServer(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(StatusResponse{
			InstanceName: "test-runtime",
		})
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	port := server.Listener.Addr().(*net.TCPAddr).Port

	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     port,
		APIHost:     "127.0.0.1",
		RuntimeName: "test-runtime",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	status := b.Status()
	if !status.APIReady {
		t.Error("API 应该已经 ready")
	}

	b.Cleanup()
}

func TestParseStatusResponse(t *testing.T) {
	tests := []struct {
		name     string
		data     string
		expected *StatusResponse
		wantErr  bool
	}{
		{
			name:     "正常响应",
			data:     `{"instance_name":"test"}`,
			expected: &StatusResponse{InstanceName: "test"},
		},
		{
			name:    "无效 JSON",
			data:    `invalid`,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := ParseStatusResponse([]byte(tt.data))
			if tt.wantErr {
				if err == nil {
					t.Fatal("应该返回错误")
				}
				return
			}
			if err != nil {
				t.Fatalf("解析失败: %v", err)
			}
			if result.InstanceName != tt.expected.InstanceName {
				t.Errorf("InstanceName 不匹配: got %q, want %q", result.InstanceName, tt.expected.InstanceName)
			}
		})
	}
}

// 并发测试
func TestStart_ConcurrentWithStop(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(10 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)
	b.setStopTimeout(1 * time.Second)
	b.setReadinessChecker(func(context.Context, string, int) (bool, string, error) {
		return false, "", nil
	})

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	startDone := make(chan error, 1)
	go func() {
		startDone <- b.Start(StartParams{ConfigPath: configPath, APIPort: 8000, RuntimeName: "test"})
	}()
	waitForStatus(t, b, func(s SystemStatus) bool { return s.Running && !s.APIReady })

	stopDone := make(chan error, 1)
	go func() {
		stopDone <- b.Stop()
	}()

	select {
	case err := <-stopDone:
		if err != nil {
			t.Fatalf("STARTING 中 Stop 失败: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("STARTING 中 Stop 永久阻塞")
	}
	select {
	case err := <-startDone:
		if err == nil {
			t.Fatal("被 Stop 取消的 Start 不应成功")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Stop 后 Start 永久阻塞")
	}
	if status := b.Status(); status.Running || status.APIReady {
		t.Fatalf("Stop 后状态未清理: %+v", status)
	}
}

func TestStart_ConcurrentWithCleanup(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	factoryEntered := make(chan struct{})
	releaseFactory := make(chan struct{})
	baseFactory := makeLongRunningCommand(30)
	b.setCommandFactory(func(name string, args ...string) *exec.Cmd {
		close(factoryEntered)
		<-releaseFactory
		return baseFactory(name, args...)
	})
	b.setReadyPollInterval(10 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)
	b.setStopTimeout(1 * time.Second)
	b.setReadinessChecker(func(context.Context, string, int) (bool, string, error) {
		return false, "", nil
	})

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	startDone := make(chan error, 1)
	go func() {
		startDone <- b.Start(StartParams{ConfigPath: configPath, APIPort: 8000, RuntimeName: "test"})
	}()
	<-factoryEntered

	cleanupDone := make(chan struct{})
	go func() {
		b.Cleanup()
		close(cleanupDone)
	}()

	select {
	case <-cleanupDone:
		t.Fatal("进程创建尚未注册时 Cleanup 不得提前返回")
	case <-time.After(50 * time.Millisecond):
	}
	close(releaseFactory)

	select {
	case <-cleanupDone:
	case <-time.After(3 * time.Second):
		t.Fatal("Cleanup 未能清理正在启动的进程")
	}
	select {
	case err := <-startDone:
		if err == nil {
			t.Fatal("被 Cleanup 取消的 Start 不应成功")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Cleanup 后 Start 永久阻塞")
	}
	if status := b.Status(); status.Running || status.APIReady {
		t.Fatalf("Cleanup 后状态未清理: %+v", status)
	}
}

func TestStatus_ConcurrentWithProcessExit(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	// 进程运行 1 秒后退出
	b.setCommandFactory(makeLongRunningCommand(1))
	b.setReadyPollInterval(50 * time.Millisecond)
	b.setReadyTimeout(5 * time.Second)

	checker, _ := makeMockReadinessChecker(1, "test")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "test.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}

	// 并发读取 Status 直到进程退出
	var wg sync.WaitGroup
	wg.Add(1)

	go func() {
		defer wg.Done()
		for i := 0; i < 100; i++ {
			b.Status()
			time.Sleep(20 * time.Millisecond)
		}
	}()

	wg.Wait()
}

// TestHelperProcess 是一个辅助测试进程
func TestHelperProcess(t *testing.T) {
	if os.Getenv("GO_WANT_HELPER_PROCESS") != "1" {
		return
	}

	exitCode := 0
	fmt.Sscanf(os.Getenv("HELPER_EXIT_CODE"), "%d", &exitCode)

	if stdout := os.Getenv("HELPER_STDOUT"); stdout != "" {
		fmt.Println(stdout)
	}
	if stderr := os.Getenv("HELPER_STDERR"); stderr != "" {
		fmt.Fprintln(os.Stderr, stderr)
	}

	if sleep := os.Getenv("HELPER_SLEEP"); sleep != "" {
		var seconds int
		fmt.Sscanf(sleep, "%d", &seconds)
		time.Sleep(time.Duration(seconds) * time.Second)
	}

	os.Exit(exitCode)
}

func writeSidecar(t *testing.T, csvPath, body string) {
	t.Helper()
	if err := os.WriteFile(csvPath+".display.json", []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func TestReadDisplayColumnsFiltersToCSVColumns(t *testing.T) {
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	writeSidecar(t, csvPath, `{"display_columns":["pid2.MV","pid2.SV","tank_2.level","not_in_csv"]}`)

	valid := []string{"_cycle", "pid2.MV", "pid2.SV", "pid2.PV", "tank_2.level", "tank_1.level"}
	got := readDisplayColumns(csvPath, valid)
	want := []string{"pid2.MV", "pid2.SV", "tank_2.level"}
	if !equalStrings(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestReadDisplayColumnsMissingSidecar(t *testing.T) {
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	if got := readDisplayColumns(csvPath, []string{"a"}); got != nil {
		t.Fatalf("expected nil for missing sidecar, got %v", got)
	}
}

func TestReadDisplayColumnsMalformedSidecar(t *testing.T) {
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	writeSidecar(t, csvPath, `{not json`)
	if got := readDisplayColumns(csvPath, []string{"a"}); got != nil {
		t.Fatalf("expected nil for malformed sidecar, got %v", got)
	}
}

func TestBuildBatchExportArgs(t *testing.T) {
	got := buildBatchExportArgs("cfg.yaml", 100, "out.xlsx", "XLSX", []string{"tank_2.level", "pid2.SV"}, "控制器")
	want := []string{
		"-c", "cfg.yaml",
		"--batch", "100",
		"--export", "out.xlsx",
		"--format", "xlsx",
		"--columns", "tank_2.level,pid2.SV",
		"--sheet-name", "控制器",
	}
	if !equalStrings(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestBuildBatchExportArgsOmitsOptional(t *testing.T) {
	got := buildBatchExportArgs("cfg.yaml", 50, "out.csv", "csv", nil, "")
	want := []string{
		"-c", "cfg.yaml",
		"--batch", "50",
		"--export", "out.csv",
		"--format", "csv",
	}
	if !equalStrings(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestBuildConvertExportArgs(t *testing.T) {
	got := buildConvertExportArgs("rows.json", "out.xlsx", "xlsx", "控制器")
	want := []string{"--convert-export", "--rows-json", "rows.json", "--export", "out.xlsx", "--format", "xlsx", "--sheet-name", "控制器"}
	if !equalStrings(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	got2 := buildConvertExportArgs("rows.json", "out.csv", "csv", "")
	want2 := []string{"--convert-export", "--rows-json", "rows.json", "--export", "out.csv", "--format", "csv"}
	if !equalStrings(got2, want2) {
		t.Fatalf("got %v, want %v", got2, want2)
	}
}

func sampleExportRows() []map[string]any {
	return []map[string]any{
		{"_cycle": 0, "value": 1.25},
		{"_cycle": 1, "value": 2.5},
	}
}

func TestExportRowsFormattedCSV(t *testing.T) {
	b := NewSystemBinding()
	out := filepath.Join(t.TempDir(), "out.csv")
	if err := b.ExportRowsFormatted([]string{"_cycle", "value"}, sampleExportRows(), out, "csv", ""); err != nil {
		t.Fatalf("csv export: %v", err)
	}
	data, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	if !strings.Contains(text, "_cycle,value") || !strings.Contains(text, "1.25") || !strings.Contains(text, "2.5") {
		t.Fatalf("unexpected csv: %q", text)
	}
}

func TestExportRowsFormattedXLSUnsupported(t *testing.T) {
	b := NewSystemBinding()
	out := filepath.Join(t.TempDir(), "out.xls")
	err := b.ExportRowsFormatted([]string{"_cycle", "value"}, sampleExportRows(), out, "xls", "")
	if err == nil {
		t.Fatal("expected error for xls")
	}
	if !strings.Contains(err.Error(), "当前版本暂不支持 xls") {
		t.Fatalf("expected clear xls error, got: %v", err)
	}
	if _, statErr := os.Stat(out); !os.IsNotExist(statErr) {
		t.Fatal("xls must not create a file")
	}
}

func TestExportRowsFormattedNoBatchLease(t *testing.T) {
	b := NewSystemBinding()
	out := filepath.Join(t.TempDir(), "out.csv")
	if err := b.ExportRowsFormatted([]string{"_cycle", "value"}, sampleExportRows(), out, "csv", ""); err != nil {
		t.Fatalf("csv export: %v", err)
	}
	b.mu.Lock()
	active := b.activeBatches
	b.mu.Unlock()
	if active != 0 {
		t.Fatalf("export must not take a batch lease, activeBatches=%d", active)
	}
}

// TestExportRowsFormattedRealChain 走真实调用链（SystemBinding → dfLaunch → python standalone_main.py），
// 等价于正式 GUI 导出所使用的后端路径（仅缺 webview 点击层）。环境无法解析 DataFactory 时跳过。
func TestExportRowsFormattedRealChain(t *testing.T) {
	repoRoot, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(repoRoot, "standalone_main.py")); err != nil {
		t.Skipf("standalone_main.py not found under %s: %v", repoRoot, err)
	}
	t.Setenv("SUPCON_TOOL_REPO_ROOT", repoRoot)
	t.Setenv("SUPCON_DATAFACTORY_PATH", "")

	b := NewSystemBinding()
	if err := b.ensureDataFactory(); err != nil {
		t.Skipf("DataFactory not resolvable: %v", err)
	}
	t.Logf("GetDataFactoryPath = %s", b.GetDataFactoryPath())

	rows := sampleExportRows()
	cols := []string{"_cycle", "value"}

	xlsxPath := filepath.Join(t.TempDir(), "real.xlsx")
	if err := b.ExportRowsFormatted(cols, rows, xlsxPath, "xlsx", "控制器"); err != nil {
		t.Fatalf("xlsx real-chain export: %v", err)
	}
	info, err := os.Stat(xlsxPath)
	if err != nil || info.Size() == 0 {
		t.Fatalf("xlsx not produced: err=%v", err)
	}
	t.Logf("xlsx size = %d bytes", info.Size())

	csvPath := filepath.Join(t.TempDir(), "real.csv")
	if err := b.ExportRowsFormatted(cols, rows, csvPath, "csv", ""); err != nil {
		t.Fatalf("csv real-chain export: %v", err)
	}
	csvData, _ := os.ReadFile(csvPath)
	if !strings.Contains(string(csvData), "1.25") {
		t.Fatalf("csv missing data: %q", string(csvData))
	}
}
