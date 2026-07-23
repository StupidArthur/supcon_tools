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

// \u521b\u5efa\u4e00\u4e2a\u6a21\u62df\u547d\u4ee4
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

// \u521b\u5efa\u4e00\u4e2a\u6301\u7eed\u8fd0\u884c\u7684\u6a21\u62df\u547d\u4ee4
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

// \u521b\u5efa\u6a21\u62df\u7684 readiness checker
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
	t.Fatalf("\u7b49\u5f85\u72b6\u6001\u8d85\u65f6\uff0c\u6700\u7ec8\u72b6\u6001: %+v", status)
	return SystemStatus{}
}

func TestBuildArgs(t *testing.T) {
	tests := []struct {
		name     string
		params   StartParams
		expected []string
	}{
		{
			name: "\u5b8c\u6574\u53c2\u6570",
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
			name: "\u53ea\u6709\u5fc5\u8981\u53c2\u6570",
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
				t.Errorf("\u53c2\u6570\u6570\u91cf\u4e0d\u5339\u914d: got %d, want %d\n  got:  %v\n  want: %v",
					len(args), len(tt.expected), args, tt.expected)
				return
			}
			for i, arg := range args {
				if arg != tt.expected[i] {
					t.Errorf("\u53c2\u6570[%d]\u4e0d\u5339\u914d: got %q, want %q", i, arg, tt.expected[i])
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
			t.Errorf("\u53c2\u6570\u7f3a\u5c11 %q", required)
		}
	}

	// \u9a8c\u8bc1\u5177\u4f53\u503c
	for i, arg := range args {
		switch arg {
		case "--name":
			if i+1 < len(args) && args[i+1] != "second_order_tank" {
				t.Errorf("--name \u503c\u4e0d\u5339\u914d: got %q, want %q", args[i+1], "second_order_tank")
			}
		case "--port":
			if i+1 < len(args) && args[i+1] != "18951" {
				t.Errorf("--port \u503c\u4e0d\u5339\u914d: got %q, want %q", args[i+1], "18951")
			}
		case "--api-port":
			if i+1 < len(args) && args[i+1] != "8000" {
				t.Errorf("--api-port \u503c\u4e0d\u5339\u914d: got %q, want %q", args[i+1], "8000")
			}
		}
	}
}

func TestBuildArgs_PortAlwaysIncluded(t *testing.T) {
	// standalone_main.py \u4e0d\u652f\u6301\u5173\u95ed OPC UA\uff0cport \u59cb\u7ec8\u4f20\u9012
	params := StartParams{
		ConfigPath:  "test.yaml",
		Port:        18951,
		EnableOpcUa: false, // \u5373\u4f7f false \u4e5f\u4f20\u9012
	}
	args := BuildArgs(params)

	hasPort := false
	for i, arg := range args {
		if arg == "--port" && i+1 < len(args) {
			hasPort = true
		}
	}

	if !hasPort {
		t.Error("port \u53c2\u6570\u5e94\u8be5\u59cb\u7ec8\u5305\u542b\uff08standalone_main.py \u4e0d\u652f\u6301\u5173\u95ed OPC UA\uff09")
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
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	status := b.Status()
	if !status.Running {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5728\u8fd0\u884c")
	}
	if !status.APIReady {
		t.Error("API \u5e94\u8be5\u5df2\u7ecf ready")
	}
	if status.RuntimeName != "test-runtime" {
		t.Errorf("RuntimeName \u4e0d\u5339\u914d: got %q, want %q", status.RuntimeName, "test-runtime")
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
		t.Fatal("readiness \u5c1a\u672a\u5339\u914d\u65f6 apiReady \u4e0d\u5f97\u4e3a true")
	}

	ready.Store(true)
	select {
	case err := <-startDone:
		if err != nil {
			t.Fatalf("Start \u5931\u8d25: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("ready \u540e Start \u672a\u8fd4\u56de")
	}

	status = b.Status()
	if !status.Running || !status.APIReady {
		t.Fatalf("ready \u540e\u72b6\u6001\u4e0d\u6b63\u786e: %+v", status)
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
		t.Fatal("\u5e94\u8be5\u8fd4\u56de\u9519\u8bef")
	}
	if !strings.Contains(err.Error(), "instance_name \u4e0d\u5339\u914d") {
		t.Errorf("\u9519\u8bef\u6d88\u606f\u4e0d\u5339\u914d: %v", err)
	}

	// \u9a8c\u8bc1\u8fdb\u7a0b\u5df2\u9000\u51fa
	time.Sleep(100 * time.Millisecond)
	status := b.Status()
	if status.Running {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5df2\u7ecf\u9000\u51fa")
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
		t.Fatal("\u5e94\u8be5\u8fd4\u56de\u9519\u8bef")
	}
	if !strings.Contains(err.Error(), "API ready \u8d85\u65f6") {
		t.Errorf("\u9519\u8bef\u6d88\u606f\u4e0d\u5339\u914d: %v", err)
	}
	// \u8d85\u65f6\u5e94\u8be5\u5728 500ms \u5de6\u53f3\uff0c\u52a0\u4e0a\u8fdb\u7a0b\u9000\u51fa\u7b49\u5f85\u65f6\u95f4
	if elapsed > 10*time.Second {
		t.Errorf("\u8d85\u65f6\u65f6\u95f4\u8fc7\u957f: %v", elapsed)
	}

	// \u9a8c\u8bc1\u8fdb\u7a0b\u5df2\u9000\u51fa
	time.Sleep(100 * time.Millisecond)
	status := b.Status()
	if status.Running {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5df2\u7ecf\u9000\u51fa")
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
		t.Fatal("\u5e94\u8be5\u8fd4\u56de\u9519\u8bef")
	}
	// \u9a8c\u8bc1\u9519\u8bef\u5305\u542b exit code
	if !strings.Contains(err.Error(), "42") {
		t.Errorf("\u5e94\u8be5\u5305\u542b exit code 42: %v", err)
	}
	// \u9a8c\u8bc1\u9519\u8bef\u5305\u542b stderr
	if !strings.Contains(err.Error(), "error occurred") {
		t.Errorf("\u5e94\u8be5\u5305\u542b stderr: %v", err)
	}

	// \u9a8c\u8bc1\u8fdb\u7a0b\u5df2\u9000\u51fa
	time.Sleep(100 * time.Millisecond)
	status := b.Status()
	if status.Running {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5df2\u7ecf\u9000\u51fa")
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

	// \u7b2c\u4e00\u6b21\u542f\u52a8
	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("\u7b2c\u4e00\u6b21 Start \u5931\u8d25: %v", err)
	}

	// \u7b2c\u4e8c\u6b21\u542f\u52a8\u5e94\u8be5\u5931\u8d25
	err = b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8001,
		RuntimeName: "test2",
	})
	if err == nil {
		t.Fatal("\u91cd\u590d\u542f\u52a8\u5e94\u8be5\u5931\u8d25")
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

	// \u4f7f\u7528 barrier \u540c\u6b65\u4e24\u4e2a goroutine
	var barrier sync.WaitGroup
	barrier.Add(2)

	var wg sync.WaitGroup
	wg.Add(2)

	results := make([]error, 2)

	for i := 0; i < 2; i++ {
		go func(idx int) {
			defer wg.Done()
			barrier.Done() // \u51c6\u5907\u5c31\u7eea
			barrier.Wait() // \u7b49\u5f85\u53e6\u4e00\u4e2a goroutine

			results[idx] = b.Start(StartParams{
				ConfigPath:  configPath,
				APIPort:     8000,
				RuntimeName: "test",
			})
		}(i)
	}

	wg.Wait()

	// \u53ea\u6709\u4e00\u4e2a\u5e94\u8be5\u6210\u529f
	successCount := 0
	for _, err := range results {
		if err == nil {
			successCount++
		}
	}

	if successCount != 1 {
		t.Errorf("\u5e94\u8be5\u6070\u597d\u4e00\u4e2a Start \u6210\u529f\uff0c\u5b9e\u9645 %d \u4e2a\u6210\u529f", successCount)
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
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	started := time.Now()
	err = b.Stop()
	if err != nil {
		t.Fatalf("Stop \u5931\u8d25: %v", err)
	}
	if elapsed := time.Since(started); elapsed >= 2*time.Second {
		t.Fatalf("Stop \u4e0d\u5e94\u5728 Interrupt \u4e0d\u53d7\u652f\u6301\u65f6\u7b49\u5f85\u5b8c\u6574\u8d85\u65f6\uff0c\u5b9e\u9645\u8017\u65f6 %v", elapsed)
	}

	status := b.Status()
	if status.Running {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5df2\u7ecf\u505c\u6b62")
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
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	// \u7b2c\u4e00\u6b21 Stop
	err = b.Stop()
	if err != nil {
		t.Fatalf("\u7b2c\u4e00\u6b21 Stop \u5931\u8d25: %v", err)
	}

	// \u7b2c\u4e8c\u6b21 Stop \u5e94\u8be5\u8fd4\u56de\u9519\u8bef
	err = b.Stop()
	if err == nil {
		t.Fatal("\u91cd\u590d Stop \u5e94\u8be5\u8fd4\u56de\u9519\u8bef")
	}
}

func TestStop_NotRunning(t *testing.T) {
	b := NewSystemBinding()

	err := b.Stop()
	if err == nil {
		t.Fatal("\u505c\u6b62\u672a\u8fd0\u884c\u7684\u8fdb\u7a0b\u5e94\u8be5\u8fd4\u56de\u9519\u8bef")
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
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	b.Cleanup()

	status := b.Status()
	if status.Running {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5df2\u7ecf\u505c\u6b62")
	}
}

func TestCleanup_NotRunning(t *testing.T) {
	b := NewSystemBinding()
	b.Cleanup() // \u4e0d\u5e94\u8be5 panic
}

func TestProcessExit_AfterReady(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	// \u8fdb\u7a0b\u8fd0\u884c 2 \u79d2\u540e\u9000\u51fa
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
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	// \u9a8c\u8bc1 ready \u540e\u72b6\u6001
	status := b.Status()
	if !status.Running || !status.APIReady {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5728\u8fd0\u884c\u4e14 API ready")
	}

	// \u7b49\u5f85\u8fdb\u7a0b\u9000\u51fa
	time.Sleep(3 * time.Second)

	// \u9a8c\u8bc1\u8fdb\u7a0b\u9000\u51fa\u540e\u72b6\u6001\u81ea\u52a8\u66f4\u65b0
	status = b.Status()
	if status.Running {
		t.Error("\u8fdb\u7a0b\u5e94\u8be5\u5df2\u7ecf\u9000\u51fa")
	}
	if status.APIReady {
		t.Error("API \u5e94\u8be5\u4e0d\u518d\u662f ready")
	}
	if status.LastError == "" {
		t.Error("\u610f\u5916\u9000\u51fa\u540e\u5e94\u4fdd\u7559 lastError")
	}

	// \u9000\u51fa\u540e\u7684 proc \u5fc5\u987b\u5df2\u7ecf\u91ca\u653e\uff0c\u5141\u8bb8\u518d\u6b21\u542f\u52a8\u3002
	err = b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "test",
	})
	if err != nil {
		t.Fatalf("\u8fdb\u7a0b\u9000\u51fa\u540e\u5e94\u5141\u8bb8\u518d\u6b21 Start: %v", err)
	}
	b.Cleanup()
}

func TestFileHashSHA256_DifferentContent(t *testing.T) {
	tmpDir := t.TempDir()

	file1 := filepath.Join(tmpDir, "file1.yaml")
	file2 := filepath.Join(tmpDir, "file2.yaml")

	// \u76f8\u540c\u957f\u5ea6\u4f46\u4e0d\u540c\u5185\u5bb9
	os.WriteFile(file1, []byte("content_a"), 0644)
	os.WriteFile(file2, []byte("content_b"), 0644)

	hash1, _ := fileHashSHA256(file1)
	hash2, _ := fileHashSHA256(file2)

	if hash1 == hash2 {
		t.Error("\u4e0d\u540c\u5185\u5bb9\u5e94\u8be5\u6709\u4e0d\u540c\u7684 hash")
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
		t.Error("\u76f8\u540c\u5185\u5bb9\u5e94\u8be5\u6709\u76f8\u540c\u7684 hash")
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

	checker, _ := makeMockReadinessChecker(1, "\u6d4b\u8bd5\u5b9e\u4f8b")
	b.setReadinessChecker(checker)

	configPath := filepath.Join(tmpDir, "\u914d\u7f6e\u6587\u4ef6.yaml")
	os.WriteFile(configPath, []byte("test: true"), 0644)

	err := b.Start(StartParams{
		ConfigPath:  configPath,
		APIPort:     8000,
		RuntimeName: "\u6d4b\u8bd5\u5b9e\u4f8b",
	})
	if err != nil {
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	status := b.Status()
	if status.ConfigPath != configPath {
		t.Errorf("ConfigPath \u4e0d\u5339\u914d: got %q, want %q", status.ConfigPath, configPath)
	}
	if status.RuntimeName != "\u6d4b\u8bd5\u5b9e\u4f8b" {
		t.Errorf("RuntimeName \u4e0d\u5339\u914d: got %q, want %q", status.RuntimeName, "\u6d4b\u8bd5\u5b9e\u4f8b")
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
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	status := b.Status()
	if !status.APIReady {
		t.Error("API \u5e94\u8be5\u5df2\u7ecf ready")
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
			name:     "\u6b63\u5e38\u54cd\u5e94",
			data:     `{"instance_name":"test"}`,
			expected: &StatusResponse{InstanceName: "test"},
		},
		{
			name:    "\u65e0\u6548 JSON",
			data:    `invalid`,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := ParseStatusResponse([]byte(tt.data))
			if tt.wantErr {
				if err == nil {
					t.Fatal("\u5e94\u8be5\u8fd4\u56de\u9519\u8bef")
				}
				return
			}
			if err != nil {
				t.Fatalf("\u89e3\u6790\u5931\u8d25: %v", err)
			}
			if result.InstanceName != tt.expected.InstanceName {
				t.Errorf("InstanceName \u4e0d\u5339\u914d: got %q, want %q", result.InstanceName, tt.expected.InstanceName)
			}
		})
	}
}

// \u5e76\u53d1\u6d4b\u8bd5
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
			t.Fatalf("STARTING \u4e2d Stop \u5931\u8d25: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("STARTING \u4e2d Stop \u6c38\u4e45\u963b\u585e")
	}
	select {
	case err := <-startDone:
		if err == nil {
			t.Fatal("\u88ab Stop \u53d6\u6d88\u7684 Start \u4e0d\u5e94\u6210\u529f")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Stop \u540e Start \u6c38\u4e45\u963b\u585e")
	}
	if status := b.Status(); status.Running || status.APIReady {
		t.Fatalf("Stop \u540e\u72b6\u6001\u672a\u6e05\u7406: %+v", status)
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
		t.Fatal("\u8fdb\u7a0b\u521b\u5efa\u5c1a\u672a\u6ce8\u518c\u65f6 Cleanup \u4e0d\u5f97\u63d0\u524d\u8fd4\u56de")
	case <-time.After(50 * time.Millisecond):
	}
	close(releaseFactory)

	select {
	case <-cleanupDone:
	case <-time.After(3 * time.Second):
		t.Fatal("Cleanup \u672a\u80fd\u6e05\u7406\u6b63\u5728\u542f\u52a8\u7684\u8fdb\u7a0b")
	}
	select {
	case err := <-startDone:
		if err == nil {
			t.Fatal("\u88ab Cleanup \u53d6\u6d88\u7684 Start \u4e0d\u5e94\u6210\u529f")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Cleanup \u540e Start \u6c38\u4e45\u963b\u585e")
	}
	if status := b.Status(); status.Running || status.APIReady {
		t.Fatalf("Cleanup \u540e\u72b6\u6001\u672a\u6e05\u7406: %+v", status)
	}
}

func TestStatus_ConcurrentWithProcessExit(t *testing.T) {
	b := NewSystemBinding()
	tmpDir := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmpDir, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0755)

	// \u8fdb\u7a0b\u8fd0\u884c 1 \u79d2\u540e\u9000\u51fa
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
		t.Fatalf("Start \u5931\u8d25: %v", err)
	}

	// \u5e76\u53d1\u8bfb\u53d6 Status \u76f4\u5230\u8fdb\u7a0b\u9000\u51fa
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

// TestHelperProcess \u662f\u4e00\u4e2a\u8f85\u52a9\u6d4b\u8bd5\u8fdb\u7a0b
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

func TestReadDisplayMetadataReadsColumnsAndScales(t *testing.T) {
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	writeSidecar(t, csvPath, `{"display_columns":["pid2.MV","pid2.SV","tank_2.level","not_in_csv"],`+
		`"plot_scales":{"pid2.MV":100.0,"pid2.SV":1.2,"tank_2.level":1.2,"not_in_csv":99.0}}`)

	valid := []string{"_cycle", "pid2.MV", "pid2.SV", "tank_2.level"}
	gotCols, gotScales := readDisplayMetadata(csvPath, valid)
	if !equalStrings(gotCols, []string{"pid2.MV", "pid2.SV", "tank_2.level"}) {
		t.Fatalf("columns got %v, want [pid2.MV pid2.SV tank_2.level]", gotCols)
	}
	wantScales := map[string]float64{"pid2.MV": 100.0, "pid2.SV": 1.2, "tank_2.level": 1.2}
	if len(gotScales) != len(wantScales) {
		t.Fatalf("scales len got %d, want %d (%v)", len(gotScales), len(wantScales), gotScales)
	}
	for k, v := range wantScales {
		if gotScales[k] != v {
			t.Fatalf("scale %s got %v, want %v", k, gotScales[k], v)
		}
	}
}

func TestReadDisplayMetadataBackcompatOldSidecar(t *testing.T) {
	// \u65e7 sidecar \u53ea\u6709 display_columns\uff0c\u6ca1\u6709 plot_scales \u2014 \u5fc5\u987b\u8fd4\u56de nil scales\uff0c\u4e0d\u62a5\u9519\u3002
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	writeSidecar(t, csvPath, `{"display_columns":["a","b"]}`)
	gotCols, gotScales := readDisplayMetadata(csvPath, []string{"a", "b", "c"})
	if !equalStrings(gotCols, []string{"a", "b"}) {
		t.Fatalf("columns got %v", gotCols)
	}
	if gotScales != nil {
		t.Fatalf("expected nil scales for old sidecar, got %v", gotScales)
	}
}

func TestReadDisplayMetadataFiltersInvalidScales(t *testing.T) {
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	// CSV \u4e2d\u53ea\u4fdd\u7559 a\u3001b\uff1bplot_scales \u4e2d\u6df7\u5165\uff1a
	//  - 0\u3001\u8d1f\u6570\uff1a\u8fdd\u53cd f > 0
	//  - \u5b57\u7b26\u4e32\uff1ajson.Number \u89e3\u6790\u5931\u8d25
	//  - c\u3001d\uff1a\u5217\u4e0d\u5728 CSV \u4e2d
	// \u5408\u6cd5\u7684\u53ea\u5269 a=1.2\u3001b=100.0\u3002
	body := `{"display_columns":["a","b"],` +
		`"plot_scales":{"a":1.2,"b":100.0,"c":1.2,"d":1.2,` +
		`"zero":0,"neg":-1.2,"str":"abc"}}`
	writeSidecar(t, csvPath, body)
	if data, _ := os.ReadFile(csvPath + ".display.json"); len(data) > 0 {
		t.Logf("sidecar: %s", string(data))
	}
	gotCols, gotScales := readDisplayMetadata(csvPath, []string{"a", "b"})
	if !equalStrings(gotCols, []string{"a", "b"}) {
		// dump fresh payload
		if data, _ := os.ReadFile(csvPath + ".display.json"); data != nil {
			t.Logf("raw bytes: %q", string(data))
			// local parse to see what json sees
			t.Logf("parsed columns: %v", gotCols)
		}
		t.Fatalf("columns got %v", gotCols)
	}
	if len(gotScales) != 2 {
		t.Fatalf("scales got %v (want only a=1.2, b=100.0)", gotScales)
	}
	if gotScales["a"] != 1.2 {
		t.Fatalf("a got %v, want 1.2", gotScales["a"])
	}
	if gotScales["b"] != 100.0 {
		t.Fatalf("b got %v, want 100.0", gotScales["b"])
	}
	for _, bad := range []string{"zero", "neg", "str", "c", "d"} {
		if _, ok := gotScales[bad]; ok {
			t.Fatalf("invalid scale %q should be filtered, got %v", bad, gotScales[bad])
		}
	}
}

func TestReadDisplayMetadataMissingSidecar(t *testing.T) {
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	// \u4e0d\u5b58\u5728\u65f6\u5fc5\u987b\u8fd4\u56de\u96f6\u503c\uff08nil, nil\uff09\uff0c\u4e0d\u963b\u65ad Batch\u3002
	gotCols, gotScales := readDisplayMetadata(csvPath, []string{"a"})
	if gotCols != nil || gotScales != nil {
		t.Fatalf("expected (nil, nil), got (%v, %v)", gotCols, gotScales)
	}
}

func TestReadDisplayMetadataMalformedSidecar(t *testing.T) {
	csvPath := filepath.Join(t.TempDir(), "result.csv")
	writeSidecar(t, csvPath, `{not json`)
	// JSON \u635f\u574f\u5fc5\u987b\u4e0d\u963b\u65ad Batch\uff08\u8fd4\u56de\u96f6\u503c\uff0c\u4e0d panic\uff09\u3002
	gotCols, gotScales := readDisplayMetadata(csvPath, []string{"a"})
	if gotCols != nil || gotScales != nil {
		t.Fatalf("expected (nil, nil) for malformed sidecar, got (%v, %v)", gotCols, gotScales)
	}
}

func TestBuildBatchExportArgs(t *testing.T) {
	got := buildBatchExportArgs("cfg.yaml", 100, "out.xlsx", "XLSX", []string{"tank_2.level", "pid2.SV"}, "\u63a7\u5236\u5668")
	want := []string{
		"-c", "cfg.yaml",
		"--batch", "100",
		"--export", "out.xlsx",
		"--format", "xlsx",
		"--columns", "tank_2.level,pid2.SV",
		"--sheet-name", "\u63a7\u5236\u5668",
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
	got := buildConvertExportArgs("rows.json", "out.xlsx", "xlsx", "\u63a7\u5236\u5668")
	want := []string{"--convert-export", "--rows-json", "rows.json", "--export", "out.xlsx", "--format", "xlsx", "--template", "prediction", "--sheet-name", "\u63a7\u5236\u5668"}
	if !equalStrings(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	got2 := buildConvertExportArgs("rows.json", "out.csv", "csv", "")
	want2 := []string{"--convert-export", "--rows-json", "rows.json", "--export", "out.csv", "--format", "csv", "--template", "prediction"}
	if !equalStrings(got2, want2) {
		t.Fatalf("got %v, want %v", got2, want2)
	}
}

func sampleExportRows() []map[string]any {
	return []map[string]any{
		{"_sim_time": 1000.0, "_need_sample": true, "value": 1.25},
		{"_sim_time": 1001.0, "_need_sample": true, "value": 2.5},
	}
}

func TestExportRowsFormattedCSV(t *testing.T) {
	// \u4e0e TestExportRowsFormattedUnifiedCommand \u76f8\u540c\u7684\u73af\u5883\u914d\u7f6e\uff08\u8ba9 ensureDataFactory \u89e3\u6790\u5230 standalone_main.py\uff09
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
	out := filepath.Join(t.TempDir(), "out.csv")
	if err := b.ExportRowsFormatted([]string{"value"], sampleExportRows(), out, "csv", ""); err != nil {
		t.Fatalf("csv export: %v", err)
	}
	data, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	// prediction \u6a21\u677f\uff1a\u4e24\u884c\u8868\u5934 + timeStamp \u5217 + \u539f\u59cb value\uff08\u4e0d\u7f29\u653e\uff09
	if !strings.Contains(text, "timeStamp,value") {
		t.Fatalf("csv missing timeStamp header: %q", text)
	}
	if !strings.Contains(text, "\u65f6\u95f4\u6233,\u67d0\u5de5\u4e1a\u6570\u636e") {
		t.Fatalf("csv missing description row: %q", text)
	}
	if !strings.Contains(text, "1.25") || !strings.Contains(text, "2.5") {
		t.Fatalf("csv missing raw values: %q", text)
	}
	if strings.Contains(text, "_cycle") || strings.Contains(text, "_sim_time") || strings.Contains(text, "_need_sample") {
		t.Fatalf("csv leaked internal fields: %q", text)
	}
}

func TestExportRowsFormattedXLSUnsupported(t *testing.T) {
	b := NewSystemBinding()
	out := filepath.Join(t.TempDir(), "out.xls")
	err := b.ExportRowsFormatted([]string{"_cycle", "value"}, sampleExportRows(), out, "xls", "")
	if err == nil {
		t.Fatal("expected error for xls")
	}
	if !strings.Contains(err.Error(), "\u5f53\u524d\u7248\u672c\u6682\u4e0d\u652f\u6301 xls") {
		t.Fatalf("expected clear xls error, got: %v", err)
	}
	if _, statErr := os.Stat(out); !os.IsNotExist(statErr) {
		t.Fatal("xls must not create a file")
	}
}

func TestExportRowsFormattedNoBatchLease(t *testing.T) {
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
	b.setCommandFactory(func(name string, arg ...string) *exec.Cmd {
		if len(arg) > 0 {
			_ = os.WriteFile(arg[len(arg)-1], []byte("ok\n"), 0o644)
		}
		return exec.Command(name, arg...)
	})
	out := filepath.Join(t.TempDir(), "out.csv")
	if err := b.ExportRowsFormatted([]string{"value"}, sampleExportRows(), out, "csv", ""); err != nil {
		t.Fatalf("csv export: %v", err)
	}
	b.mu.Lock()
	active := b.activeBatches
	b.mu.Unlock()
	if active != 0 {
		t.Fatalf("export must not take a batch lease, activeBatches=%d", active)
	}
}

// TestExportRowsFormattedRealChain \u8d70\u771f\u5b9e\u8c03\u7528\u94fe\uff08SystemBinding \u2192 dfLaunch \u2192 python standalone_main.py\uff09\uff0c
// \u7b49\u4ef7\u4e8e\u6b63\u5f0f GUI \u5bfc\u51fa\u6240\u4f7f\u7528\u7684\u540e\u7aef\u8def\u5f84\uff08\u4ec5\u7f3a webview \u70b9\u51fb\u5c42\uff09\u3002\u73af\u5883\u65e0\u6cd5\u89e3\u6790 DataFactory \u65f6\u8df3\u8fc7\u3002
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
	cols := []string{"value"}

	xlsxPath := filepath.Join(t.TempDir(), "real.xlsx")
	err := b.ExportRowsFormatted(cols, rows, xlsxPath, "xlsx", "\u63a7\u5236\u5668");
	if err != nil {
		t.Fatalf("xlsx real-chain export: %v", err)
	}
	info, err := os.Stat(xlsxPath)
	if err != nil || info.Size() == 0 {
		t.Fatalf("xlsx not produced: err=%v", err)
	}
	t.Logf("xlsx size = %d bytes", info.Size())

	csvPath := filepath.Join(t.TempDir(), "real.csv")
	err := b.ExportRowsFormatted(cols, rows, csvPath, "csv", "");
	if err != nil {
		t.Fatalf("csv real-chain export: %v", err)
	}
	csvData, _ := os.ReadFile(csvPath)
	// prediction \u6a21\u677f\uff1atimeStamp \u5217\u5728\u7b2c\u4e00\u5217\uff0c\u539f\u59cb value\uff08\u4e0d\u7f29\u653e\uff09\uff0c\u4e0d\u5141\u8bb8 _cycle / _sim_time \u6cc4\u6f0f
	csvText := string(csvData)
	if !strings.Contains(csvText, "timeStamp,value") {
		t.Fatalf("csv missing timeStamp header: %q", csvText)
	}
	if strings.Contains(csvText, "_cycle") {
		t.Fatalf("csv leaked _cycle: %q", csvText)
	}
	if !strings.Contains(csvText, "1.25") {
		t.Fatalf("csv missing raw value: %q", csvText)
	}
}

func TestExportFileDialogSpec(t *testing.T) {
	name, pat, def, err := exportFileDialogSpec("csv")
	if err != nil || name == "" || pat != "*.csv" || def != "result.csv" {
		t.Fatalf("csv: err=%v name=%q pat=%q def=%q", err, name, pat, def)
	}
	if _, _, _, err := exportFileDialogSpec("xlsx"); err != nil {
		t.Fatalf("xlsx: unexpected err %v", err)
	}
	if _, _, _, err := exportFileDialogSpec("XLSX"); err != nil {
		t.Fatalf("uppercase xlsx: unexpected err %v", err)
	}
	if _, _, _, err := exportFileDialogSpec(" xls "); err == nil ||
		!strings.Contains(err.Error(), "\u5f53\u524d\u7248\u672c\u6682\u4e0d\u652f\u6301 xls") {
		t.Fatalf("xls (trim): %v", err)
	}
	if _, _, _, err := exportFileDialogSpec("pdf"); err == nil ||
		!strings.Contains(err.Error(), "\u4e0d\u652f\u6301\u7684\u5bfc\u51fa\u683c\u5f0f") {
		t.Fatalf("unknown format: %v", err)
	}
}

func TestExportBatchFormattedXLSNoSubprocess(t *testing.T) {
	b := NewSystemBinding()
	// \u82e5 xls \u6f0f\u8fc7\u683c\u5f0f\u95e8\u7981\u5e76\u89e6\u8fbe\u5b50\u8fdb\u7a0b\u8def\u5f84\uff0c\u5c06 panic \u5931\u8d25\u3002
	b.setCommandFactory(func(name string, arg ...string) *exec.Cmd {
		t.Fatalf("subprocess must not be launched for xls: %s %v", name, arg)
		return exec.Command(name, arg...)
	})
	out := filepath.Join(t.TempDir(), "out.xls")
	err := b.ExportBatchFormatted("cfg.yaml", 100, out, "xls", []string{"a"}, "")
	if err == nil {
		t.Fatal("expected error for xls")
	}
	if !strings.Contains(err.Error(), "\u5f53\u524d\u7248\u672c\u6682\u4e0d\u652f\u6301 xls") {
		t.Fatalf("expected xls error, got: %v", err)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Fatalf("xls must not create a file: %v", err)
	}
	b.mu.Lock()
	active := b.activeBatches
	b.mu.Unlock()
	if active != 0 {
		t.Fatalf("xls must not take a batch lease, activeBatches=%d", active)
	}

	// \u5e26\u7a7a\u683c\u7684 xls \u4ecd\u987b\u5728\u542f\u52a8\u5b50\u8fdb\u7a0b\u524d\u8fd4\u56de\u540c\u4e00\u9519\u8bef\u3002
	b.setCommandFactory(func(name string, arg ...string) *exec.Cmd {
		t.Fatalf("subprocess must not be launched for trimmed xls: %s %v", name, arg)
		return exec.Command(name, arg...)
	})
	if err := b.ExportBatchFormatted("cfg.yaml", 100, filepath.Join(t.TempDir(), "trim.xls"), " xls ", nil, ""); err == nil ||
		!strings.Contains(err.Error(), "\u5f53\u524d\u7248\u672c\u6682\u4e0d\u652f\u6301 xls") {
		t.Fatalf("trimmed xls: %v", err)
	}
}

// TestBuildBatchExportArgsNormalizesFormat \u9a8c\u8bc1\u6700\u7ec8 CLI \u53c2\u6570\u4e2d\u7684 --format \u4e0d\u5e26\u524d\u540e\u7a7a\u683c\u3002
// \u8c03\u7528\u65b9\u5df2\u89c4\u8303\u5316\uff0c\u4f46\u51fd\u6570\u81ea\u8eab\u4ecd\u505a\u9632\u5fa1\u6027 trim + lowercase\uff0c\u4fdd\u8bc1\u900f\u4f20\u7ed9 Python argparse \u7684\u662f\u7cbe\u786e\u5339\u914d\u7684\u5408\u6cd5\u503c\u3002
func TestBuildBatchExportArgsNormalizesFormat(t *testing.T) {
	got := buildBatchExportArgs("cfg.yaml", 100, "out.xlsx", " xLsX ", []string{"a"}, "")
	want := []string{
		"-c", "cfg.yaml",
		"--batch", "100",
		"--export", "out.xlsx",
		"--format", "xlsx",
		"--columns", "a",
	}
	if !equalStrings(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}

	got2 := buildBatchExportArgs("cfg.yaml", 50, "out.csv", "  CSV ", nil, "")
	want2 := []string{
		"-c", "cfg.yaml",
		"--batch", "50",
		"--export", "out.csv",
		"--format", "csv",
	}
	if !equalStrings(got2, want2) {
		t.Fatalf("got %v, want %v", got2, want2)
	}
}

// TestParseBatchCell \u9a8c\u8bc1\u5185\u90e8\u9690\u85cf\u5217 (_sim_time / _need_sample) \u4e0e\u4e1a\u52a1\u5217\u7684\u89e3\u6790\u89c4\u5219\u3002
func TestParseBatchCell(t *testing.T) {
	// _sim_time \u5fc5\u987b\u89e3\u6790\u4e3a float64\uff1b\u7a7a / \u975e\u6570 / \u975e\u6709\u9650 \u2192 \u9519\u8bef
	for _, raw := range []string{"1000.5", "  1000.5  "} {
		v, err := parseBatchCell("_sim_time", raw)
		if err != nil {
			t.Fatalf("_sim_time valid %q: %v", raw, err)
		}
		if f, ok := v.(float64); !ok || f != 1000.5 {
			t.Fatalf("_sim_time %q got %v (%T)", raw, v, v)
		}
	}
	for _, bad := range []string{"", "abc", "NaN", "Inf", "-Inf"} {
		if _, err := parseBatchCell("_sim_time", bad); err == nil {
			t.Fatalf("_sim_time %q should be rejected", bad)
		}
	}
	// _need_sample \u63a5\u53d7 true/false/1/0 \u5404\u79cd\u5927\u5c0f\u5199
	for _, p := range []struct {
		raw   string
		want  bool
	}{
		{"true", true}, {"True", true}, {"TRUE", true}, {"1", true}, {"  true  ", true},
		{"false", false}, {"False", false}, {"FALSE", false}, {"0", false}, {"  0  ", false},
	} {
		v, err := parseBatchCell("_need_sample", p.raw)
		if err != nil {
			t.Fatalf("_need_sample %q should parse: %v", p.raw, err)
		}
		if b, ok := v.(bool); !ok || b != p.want {
			t.Fatalf("_need_sample %q got %v (%T)", p.raw, v, v)
		}
	}
	for _, bad := range []string{"", "yes", "no", "2", "TrueFalse"} {
		if _, err := parseBatchCell("_need_sample", bad); err == nil {
			t.Fatalf("_need_sample %q should be rejected", bad)
		}
	}
	if v, err := parseBatchCell("pid2.PV", "0.1"); err != nil || v.(float64) != 0.1 {
		t.Fatalf("business float: %v %v", v, err)
	}
	if v, err := parseBatchCell("text", "hello"); err != nil || v.(string) != "hello" {
		t.Fatalf("business text: %v %v", v, err)
	}
}

// TestBuildConvertExportArgsIncludesPredictionTemplate \u9a8c\u8bc1 --template prediction \u663e\u5f0f\u4f20\u9012\u3002
func TestBuildConvertExportArgsIncludesPredictionTemplate(t *testing.T) {
	rows := "rows.json"
	out := "out.csv"
	got := buildConvertExportArgs(rows, out, "csv", "")
	want := []string{
		"--convert-export",
		"--rows-json", rows,
		"--export", out,
		"--format", "csv",
		"--template", "prediction",
	}
	if !equalStrings(got, want) {
		t.Fatalf("csv got %v, want %v", got, want)
	}
	got2 := buildConvertExportArgs(rows, "out.xlsx", "xlsx", "\u63a7\u5236\u5668")
	want2 := []string{
		"--convert-export",
		"--rows-json", rows,
		"--export", "out.xlsx",
		"--format", "xlsx",
		"--template", "prediction",
		"--sheet-name", "\u63a7\u5236\u5668",
	}
	if !equalStrings(got2, want2) {
		t.Fatalf("xlsx got %v, want %v", got2, want2)
	}
	// xlsx \u4e0d\u4f20 sheet-name \u65f6\u4e0d\u4f20 --sheet-name\uff08\u907f\u514d Python \u4f7f\u7528\u9884\u6d4b\u9ed8\u8ba4\u503c\uff09
	got3 := buildConvertExportArgs(rows, "out.xlsx", "xlsx", "")
	for _, a := range got3 {
		if a == "--sheet-name" {
			t.Fatalf("xlsx without sheet-name must not include --sheet-name: %v", got3)
		}
	}
}

// TestParseCSVHiddenFields \u9a8c\u8bc1 parseCSV \u628a _sim_time \u89e3\u6790\u4e3a float64\u3001_need_sample \u89e3\u6790\u4e3a bool\u3002
func TestParseCSVHiddenFields(t *testing.T) {
	dir := t.TempDir()
	csvPath := filepath.Join(dir, "result.csv")
	body := "_sim_time,_need_sample,pid2.PV\n" +
		"1000.5,True,0.8\n" +
		"1001.0,False,0.9\n"
	if err := os.WriteFile(csvPath, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	res, err := parseCSV(csvPath)
	if err != nil {
		t.Fatalf("parseCSV: %v", err)
	}
	if len(res.Rows) != 2 {
		t.Fatalf("rows len got %d, want 2", len(res.Rows))
	}
	if v, ok := res.Rows[0]["_sim_time"].(float64); !ok || v != 1000.5 {
		t.Fatalf("row0 _sim_time got %v (%T)", res.Rows[0]["_sim_time"], res.Rows[0]["_sim_time"])
	}
	if v, ok := res.Rows[0]["_need_sample"].(bool); !ok || v != true {
		t.Fatalf("row0 _need_sample got %v (%T)", res.Rows[0]["_need_sample"], res.Rows[0]["_need_sample"])
	}
	if v, ok := res.Rows[1]["_sim_time"].(float64); !ok || v != 1001.0 {
		t.Fatalf("row1 _sim_time got %v (%T)", res.Rows[1]["_sim_time"], res.Rows[1]["_sim_time"])
	}
	if v, ok := res.Rows[1]["_need_sample"].(bool); !ok || v != false {
		t.Fatalf("row1 _need_sample got %v (%T)", res.Rows[1]["_need_sample"], res.Rows[1]["_need_sample"])
	}
	if res.Rows[0]["_cycle"].(int) != 0 {
		t.Fatalf("row0 _cycle: %v", res.Rows[0]["_cycle"])
	}
	if res.Rows[1]["_cycle"].(int) != 1 {
		t.Fatalf("row1 _cycle: %v", res.Rows[1]["_cycle"])
	}
}

// TestParseCSVInvalidSimTime \u9a8c\u8bc1 _sim_time \u4e3a\u7a7a\u65f6\u8fd4\u56de\u660e\u786e\u9519\u8bef\u3002
func TestParseCSVInvalidSimTime(t *testing.T) {
	dir := t.TempDir()
	csvPath := filepath.Join(dir, "result.csv")
	body := "_sim_time,_need_sample,pid2.PV\n" +
		",True,0.8\n"
	if err := os.WriteFile(csvPath, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := parseCSV(csvPath); err == nil {
		t.Fatal("expected error for empty _sim_time")
	} else if !strings.Contains(err.Error(), "\u7f3a\u5c11\u6709\u6548 _sim_time") {
		t.Fatalf("expected _sim_time error, got: %v", err)
	}
}

// TestExportRowsFormattedUnifiedCommand \u9a8c\u8bc1 csv/xlsx \u90fd\u8d70 --convert-export\uff08\u542b --template prediction\uff09\uff0c
// \u4e14 ExportRowsFormatted \u4e0d\u518d\u56de\u9000\u5230\u65e7 ExportCSVRows \u8def\u5f84\u3002
func TestExportRowsFormattedUnifiedCommand(t *testing.T) {
	// \u8ba9 ensureDataFactory \u80fd\u89e3\u6790\u5230 review3/standalone_main.py\uff08\u4e0e TestExportRowsFormattedRealChain \u76f8\u540c\u6a21\u5f0f\uff09
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
	// \u6ce8\u5165\u4f1a exec \u7684 cmd\uff0c\u5e76\u5199\u51fa output \u6587\u4ef6\uff0c\u907f\u514d ExportRowsFormatted \u62a5"\u6587\u4ef6\u672a\u751f\u6210"
	b.setCommandFactory(func(name string, arg ...string) *exec.Cmd {
		if len(arg) > 0 {
			_ = os.WriteFile(arg[len(arg)-1], []byte("ok\n"), 0o644)
		}
		return exec.Command(name, arg...)
	})
	rows := []map[string]any{
		{"_sim_time": 1000.0, "_need_sample": true, "pid2.PV": 0.1},
	}
	outCSV := filepath.Join(t.TempDir(), "out.csv")
	err := b.ExportRowsFormatted([]string{"pid2.PV"}, rows, outCSV, "csv", "");
	if err != nil {
		t.Fatalf("csv export: %v", err)
	}
	if _, err := os.Stat(outCSV); err != nil {
		t.Fatalf("csv file not created: %v", err)
	}
	outXLSX := filepath.Join(t.TempDir(), "out.xlsx")
	err := b.ExportRowsFormatted([]string{"pid2.PV"}, rows, outXLSX, "xlsx", "\u63a7\u5236\u5668");
	if err != nil {
		t.Fatalf("xlsx export: %v", err)
	}
	if _, err := os.Stat(outXLSX); err != nil {
		t.Fatalf("xlsx file not created: %v", err)
	}
}
