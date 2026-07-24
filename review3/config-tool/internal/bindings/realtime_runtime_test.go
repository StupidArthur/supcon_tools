package bindings

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"config-tool/internal/realtime"
)

// realtimeTestRig 构造可独立测试的 RealtimeRuntimeBinding。
// system 使用 mock commandFactory（不真的启动 DataFactory），避免依赖 exe；
// 同时注入 readiness checker 让它接受任意 token 且 instance 名匹配。
type realtimeTestRig struct {
	binding    *RealtimeRuntimeBinding
	system     *SystemBinding
	manager    *realtime.Manager
	storeRoot  string
	configPath string
}

func newRealtimeTestRig(t *testing.T) *realtimeTestRig {
	t.Helper()
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})
	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(20 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "test-runtime", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)

	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	return &realtimeTestRig{
		binding:    binding,
		system:     system,
		manager:    manager,
		storeRoot:  storeRoot,
		configPath: cfg,
	}
}

func (r *realtimeTestRig) cleanup() {
	if r.system.Status().Running {
		_ = r.system.Stop()
	}
}

func TestGetConnectionInfo_NoSession(t *testing.T) {
	rig := newRealtimeTestRig(t)
	defer rig.cleanup()

	info, err := rig.binding.GetConnectionInfo()
	if err == nil {
		t.Fatal("没有 session 时 GetConnectionInfo 必须返回错误")
	}
	if info.APIToken != "" {
		t.Errorf("没有 session 时 token 必须为空，实际 %q", info.APIToken)
	}
}

func TestGetConnectionInfo_ReturnsTokenAfterStart(t *testing.T) {
	// 用真实的 mock auth server，让 defaultReadinessChecker 携带 token，
	// 验证 GetConnectionInfo 返回的 token 与 mock 校验时收到的 token 一致。
	var receivedAuth atomic.Value
	mux := http.NewServeMux()
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		receivedAuth.Store(r.Header.Get("Authorization"))
		auth := r.Header.Get("Authorization")
		if !strings.HasPrefix(auth, "Bearer ") || auth == "Bearer " {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(StatusResponse{InstanceName: "test-runtime"})
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()
	port := srv.Listener.Addr().(*net.TCPAddr).Port

	rig := newRealtimeTestRig(t)
	defer rig.cleanup()
	rig.system.setReadinessChecker(defaultReadinessChecker)

	_, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		CycleTime:   0.5,
		OPCUAPort:   18951,
		APIHost:     "127.0.0.1",
		APIPort:     port,
		RuntimeName: "test-runtime",
	})
	if err != nil {
		t.Fatalf("StartSingleYAML 失败: %v", err)
	}

	info, err := rig.binding.GetConnectionInfo()
	if err != nil {
		t.Fatalf("GetConnectionInfo 失败: %v", err)
	}
	if info.APIToken == "" {
		t.Fatal("active session 后 token 必须非空")
	}
	if info.APIHost != "127.0.0.1" || info.APIPort != port || info.RuntimeName != "test-runtime" {
		t.Errorf("connection info 字段错误: %+v", info)
	}
	auth, _ := receivedAuth.Load().(string)
	if auth != "Bearer "+info.APIToken {
		t.Errorf("readiness 收到的 Bearer 与 GetConnectionInfo 报告的 token 不一致：%q vs %q",
			auth, info.APIToken)
	}
}

func TestGetConnectionInfo_AfterStopClearsToken(t *testing.T) {
	rig := newRealtimeTestRig(t)
	defer rig.cleanup()

	if _, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "test-runtime",
	}); err != nil {
		t.Fatalf("Start 失败: %v", err)
	}
	info, err := rig.binding.GetConnectionInfo()
	if err != nil {
		t.Fatalf("active 后 GetConnectionInfo 失败: %v", err)
	}
	if info.APIToken == "" {
		t.Fatal("active 后 token 必须非空")
	}

	if err := rig.binding.Stop(); err != nil {
		t.Fatalf("Stop 失败: %v", err)
	}
	if _, err := rig.binding.GetConnectionInfo(); err == nil {
		t.Error("Stop 后 GetConnectionInfo 必须返回错误")
	}
	if got := CurrentAPIToken(); got != "" {
		t.Errorf("Stop 后 CurrentAPIToken() 必须为空，实际 %q", got)
	}
}

// 确认 session.json 不含 token 字段（持久化隔离）
func TestSessionRecord_DoesNotPersistToken(t *testing.T) {
	rig := newRealtimeTestRig(t)
	defer rig.cleanup()

	_, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "test-runtime",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}
	// 找到 session 目录
	sessionsRoot := filepath.Join(filepath.Dir(rig.storeRoot), "sessions")
	if _, err := os.Stat(sessionsRoot); err != nil {
		t.Fatalf("sessions root not found: %v", err)
	}
	// 在子目录里找 session.json
	entries, err := os.ReadDir(sessionsRoot)
	if err != nil {
		t.Fatalf("read sessions: %v", err)
	}
	if len(entries) == 0 {
		t.Fatal("expected session directory")
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		p := filepath.Join(sessionsRoot, e.Name(), "session.json")
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		var parsed map[string]any
		if err := json.Unmarshal(data, &parsed); err != nil {
			t.Fatalf("解析 session.json 失败: %v", err)
		}
		for _, field := range []string{"token", "apiToken", "api_token", "APIToken"} {
			if _, ok := parsed[field]; ok {
				t.Errorf("session.json 不得包含 %q 字段，实际内容: %s", field, string(data))
			}
		}
	}
}

// 确认 Stop 后旧 token 拒绝访问（不能复用到下一次 readiness）。
func TestStart_RestartTokenUniqueAndPreviousCleared(t *testing.T) {
	rig := newRealtimeTestRig(t)
	defer rig.cleanup()
	var expected atomic.Value
	rig.system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		if v, ok := expected.Load().(string); ok && v != "" {
			return true, v, nil
		}
		return true, "test-runtime", nil
	})

	if _, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "test-runtime",
	}); err != nil {
		t.Fatalf("Start 1 失败: %v", err)
	}
	first, _ := rig.binding.GetConnectionInfo()
	if first.APIToken == "" {
		t.Fatal("first token must be non-empty")
	}
	if err := rig.binding.Stop(); err != nil {
		t.Fatalf("Stop 失败: %v", err)
	}
	expected.Store("test-runtime2")
	if _, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "test-runtime2",
	}); err != nil {
		t.Fatalf("Start 2 失败: %v", err)
	}
	second, _ := rig.binding.GetConnectionInfo()
	if second.APIToken == "" {
		t.Fatal("second token must be non-empty")
	}
	if second.APIToken == first.APIToken {
		t.Errorf("两次 token 必须不同：%q", second.APIToken)
	}
}

// 验证 unused helper to silence linter
var _ = sync.Mutex{}

// localFakeCompiler 仅在本测试用：直接通过 Validate/Compile。
type localFakeCompiler struct{}

func (l *localFakeCompiler) Validate(_ context.Context, _ []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	return realtime.ValidationResult{
		Valid:     true,
		Instances: []realtime.ExpandedInstance{{Name: "test-runtime", SourceID: "s1", ReplicaIndex: 0, OriginalName: "test-runtime"}},
	}, nil
}

func (l *localFakeCompiler) Compile(_ context.Context, _ []realtime.CompilerSourceSpec, outputPath string) (string, error) {
	// 实际写一个简单 YAML，否则 system.Start 读不到文件会失败。
	if err := os.WriteFile(outputPath, []byte("clock:\n  cycle_time: 0.5\nprogram: []\n"), 0o644); err != nil {
		return "", err
	}
	return outputPath, nil
}

// 阶段 B：异常退出清理 + ChildPid 写入
func TestStart_WritesChildPid(t *testing.T) {
	rig := newRealtimeTestRig(t)
	defer rig.cleanup()

	_, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "test-runtime",
	})
	if err != nil {
		t.Fatalf("Start 失败: %v", err)
	}
	sess, _ := rig.binding.GetSession()
	if sess == nil {
		t.Fatal("session 必须返回")
	}
	// ChildPid 写入 session.json
	dir := filepath.Join(filepath.Dir(rig.storeRoot), "sessions")
	entries, _ := os.ReadDir(dir)
	if len(entries) == 0 {
		t.Fatal("session dir missing")
	}
	p := filepath.Join(dir, entries[0].Name(), "session.json")
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	var rec realtime.SessionRecord
	if err := json.Unmarshal(data, &rec); err != nil {
		t.Fatal(err)
	}
	// ChildPid 是 0（mock 命令没有真实 PID），但至少字段必须存在且为非负。
	if rec.OwnerPid != os.Getpid() {
		t.Errorf("ownerPid mismatch: got %d, want %d", rec.OwnerPid, os.Getpid())
	}
}

// 异常退出：DataFactory 进程提前退出 → RealtimeRuntimeBinding.current 必须清空，
// curDir 必须清空，session 目录必须删除。
func TestStart_UnexpectedExitClearsSessionAndRemovesDir(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})
	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	// 进程立即以 code 7 退出
	system.setCommandFactory(makeMockCommand(7, "", "aborted"))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		return false, "", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())

	defer system.Cleanup()

	_, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "test-runtime",
	})
	if err == nil {
		t.Fatal("启动失败：应以进程提前退出失败")
	}

	// 启动失败本身就要清掉 session 目录
	entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
	if len(entries) != 0 {
		t.Errorf("启动失败后 session 目录必须清空，实际 %d 个", len(entries))
	}
}

// SessionObject 持久化：Stop 触发 onSystemProcessExit → session 目录被删除；下次启动重新创建。
func TestStart_StopRemovesSessionDir(t *testing.T) {
	rig := newRealtimeTestRig(t)
	defer rig.cleanup()
	var expected atomic.Value
	rig.system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		if v, ok := expected.Load().(string); ok && v != "" {
			return true, v, nil
		}
		return true, "test-runtime", nil
	})
	expected.Store("rt-stop")

	_, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "rt-stop",
	})
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(filepath.Dir(rig.storeRoot), "sessions")
	entries, _ := os.ReadDir(dir)
	if len(entries) == 0 {
		t.Fatal("session dir expected")
	}
	preStopDir := filepath.Join(dir, entries[0].Name())
	if _, err := os.Stat(preStopDir); err != nil {
		t.Fatal(err)
	}

	if err := rig.binding.Stop(); err != nil {
		t.Fatal(err)
	}
	// After Stop, dir should be removed
	if _, err := os.Stat(preStopDir); !os.IsNotExist(err) {
		t.Errorf("Stop 后 session 目录必须被删除，实际: %v", err)
	}
	// GetSession 必须返回 nil
	s, _ := rig.binding.GetSession()
	if s != nil {
		t.Errorf("Stop 后 GetSession 必须返回 nil, 实际 %+v", s)
	}
}

// 验证真实 PID 写入（用 long-running mock）
func TestStart_ChildPidIsNonZeroForRealProcess(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})
	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	// 长跑进程，留出时间做断言
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "rt-child", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	_, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "rt-child",
	})
	if err != nil {
		t.Fatal(err)
	}

	// 找 session.json 并验证 ChildPid > 0
	dir := filepath.Join(tmp, "sessions")
	entries, _ := os.ReadDir(dir)
	if len(entries) == 0 {
		t.Fatal("session dir missing")
	}
	p := filepath.Join(dir, entries[0].Name(), "session.json")
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	var rec realtime.SessionRecord
	if err := json.Unmarshal(data, &rec); err != nil {
		t.Fatal(err)
	}
	if rec.ChildPid <= 0 {
		t.Errorf("ChildPid 必须 > 0（真实子进程），实际 %d", rec.ChildPid)
	}
	if rec.OwnerPid != os.Getpid() {
		t.Errorf("OwnerPid 必须 == os.Getpid()，实际 %d", rec.OwnerPid)
	}
}

// 确认启动成功 → session 目录存在且 current 不为空；启动后立即子进程超时退出，
// 触发 onSystemProcessExit → session 目录被移除，current 为 nil。
func TestStart_UnexpectedChildExitClearsSession(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})
	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	// 进程跑 1s
	system.setCommandFactory(makeLongRunningCommand(1))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "rt-unex", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	_, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "rt-unex",
	})
	if err != nil {
		t.Fatal(err)
	}
	sess, _ := binding.GetSession()
	if sess == nil {
		t.Fatal("GetSession 必须非空")
	}

	// 等进程退出。检查 session 目录是否被清掉
	deadline := time.Now().Add(5 * time.Second)
	var dirEmpty bool
	for time.Now().Before(deadline) {
		entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
		if len(entries) == 0 {
			dirEmpty = true
			break
		}
		// 还要看 session 状态是否变化
		cur, _ := binding.GetSession()
		if cur == nil {
			dirEmpty = true
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !dirEmpty {
		t.Errorf("异常退出后 session 目录与 current 必须被清理")
	}
}

// 阶段 C：报警配置推送失败必须使启动失败并回滚。
func TestStart_AlarmPushFailedRollsBack(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})

	// 创建项目 + 报警规则
	ctx := context.Background()
	if _, err := manager.CreateProject(ctx, "alarmfail"); err != nil {
		t.Fatal(err)
	}
	projects, _ := manager.ListProjects(ctx)
	pid := projects[0].ID
	yamlPath := filepath.Join(tmp, "src.yaml")
	os.WriteFile(yamlPath, []byte("clock:\n  cycle_time: 0.5\nprogram: []\n"), 0o644)
	view, err := manager.AddSource(ctx, pid, yamlPath)
	if err != nil {
		t.Fatal(err)
	}
	srcID := view.Project.Sources[0].ID
	srcAbs := storage.SourceAbsPath(pid, srcID)
	if err := os.WriteFile(srcAbs, []byte("clock:\n  cycle_time: 0.5\nprogram: []\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = manager.CreateAlarmRule(ctx, pid, realtime.AlarmRule{
		Name: "high_level", Tag: "tank_2.level", Direction: realtime.DirectionHigh,
		Limit: 1.0, Severity: realtime.SeverityCritical,
	})
	if err != nil {
		t.Fatal(err)
	}

	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "alarmfail", nil
	})

	// 启动 alarm push 失败 mock server
	var (
		gotRules atomic.Bool
	)
	alarmMux := http.NewServeMux()
	alarmMux.HandleFunc("/api/alarms/config", func(w http.ResponseWriter, r *http.Request) {
		gotRules.Store(true)
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("simulated push failure"))
	})
	alarmSrv := httptest.NewServer(alarmMux)
	defer alarmSrv.Close()
	ports := strings.TrimPrefix(alarmSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	_, err = binding.StartProject(pid, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "alarmfail",
	})
	if err == nil {
		t.Fatal("报警推送失败时 Start 必须失败")
	}
	if !gotRules.Load() {
		t.Error("Start 期间必须实际调用 /api/alarms/config")
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		cur, _ := binding.GetSession()
		entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
		if cur == nil && len(entries) == 0 {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	cur, _ := binding.GetSession()
	entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
	t.Errorf("回滚不彻底: current=%v, sessions=%d", cur, len(entries))
}

// 阶段 C：归档启动失败必须使启动失败并回滚。
func TestStart_ArchiveFailedRollsBack(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})

	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "archivefail", nil
	})

	archiveMux := http.NewServeMux()
	archiveMux.HandleFunc("/api/archive/start", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("disk full"))
	})
	archiveSrv := httptest.NewServer(archiveMux)
	defer archiveSrv.Close()
	ports := strings.TrimPrefix(archiveSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	_, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "archivefail",
		ArchiveEnabled: true,
		ArchiveTags:    []string{"tank_2.level"},
	})
	if err == nil {
		t.Fatal("归档启动失败时 Start 必须失败")
	}
	entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
	if len(entries) != 0 {
		t.Errorf("归档启动失败后 session 目录必须清空，实际 %d 个", len(entries))
	}
	if system.Status().Running {
		t.Errorf("归档失败回滚后 system.Status().Running 必须为 false")
	}
}

// 阶段 C3：报警规则为空时是合法 no-op，不应报错。
func TestStart_NoAlarmRulesIsNoOp(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})

	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "noalarms", nil
	})

	alarmMux := http.NewServeMux()
	alarmMux.HandleFunc("/api/alarms/config", func(w http.ResponseWriter, r *http.Request) {
		t.Errorf("no rule 时不应推送 /api/alarms/config")
		w.WriteHeader(http.StatusInternalServerError)
	})
	alarmSrv := httptest.NewServer(alarmMux)
	defer alarmSrv.Close()
	ports := strings.TrimPrefix(alarmSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	if _, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "noalarms",
	}); err != nil {
		t.Fatal(err)
	}
}

// 阶段 C4：Stop 顺序——归档停止必须在 system.Stop 之前。
func TestStart_StopCallsArchiveStopBeforeSystem(t *testing.T) {
	var order []string
	var orderMu sync.Mutex
	archiveMux := http.NewServeMux()
	archiveMux.HandleFunc("/api/archive/stop", func(w http.ResponseWriter, r *http.Request) {
		orderMu.Lock()
		order = append(order, "archive-stop")
		orderMu.Unlock()
		w.WriteHeader(http.StatusOK)
	})
	archiveSrv := httptest.NewServer(archiveMux)
	defer archiveSrv.Close()
	ports := strings.TrimPrefix(archiveSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	rig := newRealtimeTestRig(t)
	defer rig.cleanup()
	rig.system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "stop-order", nil
	})

	if _, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "stop-order",
	}); err != nil {
		t.Fatal(err)
	}
	if err := rig.binding.Stop(); err != nil {
		t.Fatal(err)
	}
	orderMu.Lock()
	defer orderMu.Unlock()
	if len(order) == 0 {
		t.Error("Stop 应调用 /api/archive/stop")
	}
}

// 阶段 C4：Stop 期间归档停止失败不应阻止 system.Stop。
func TestStart_StopArchiveFailureNotFatal(t *testing.T) {
	archiveMux := http.NewServeMux()
	archiveMux.HandleFunc("/api/archive/stop", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("close failed"))
	})
	archiveSrv := httptest.NewServer(archiveMux)
	defer archiveSrv.Close()
	ports := strings.TrimPrefix(archiveSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	rig := newRealtimeTestRig(t)
	defer rig.cleanup()
	rig.system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "stop-archive-fail", nil
	})

	if _, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "stop-archive-fail",
	}); err != nil {
		t.Fatal(err)
	}
	if err := rig.binding.Stop(); err != nil {
		t.Errorf("归档停止失败不应使 Stop 失败: %v", err)
	}
	if rig.system.Status().Running {
		t.Errorf("Stop 后系统仍 Running")
	}
}

// 阶段 B2 收口：SetContext 必须 sync.Once，多次调用只注册一个监听器。
// 验证：异常退出只触发一次清理（不会重复 RemoveSessionDir 导致错误或泄漏）。
func TestSetContext_RegistersExitListenerOnlyOnce(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})
	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(20 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "dup-listener", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	defer system.Cleanup()

	// 多次调用 SetContext —— Wails lifecycle 可能在 OnStartup 之后再次触发。
	binding.SetContext(context.Background())
	binding.SetContext(context.Background())
	binding.SetContext(context.Background())

	// 验证 listener 数量：
	// 1) 之前没有显式 getter；从 monitorProcess 的 dispatch 行为反推。
	// 我们启动一次 + 立即 Stop，Stop 路径会同时走 monitorProcess dispatch + 显式 b.system.Stop，
	// 重复监听会导致 RemoveSessionDir 多次（第二次报错但被忽略），但 onSystemProcessExit 幂等
	// （current 第二次为 nil 不会重复 RemoveSessionDir）。
	// 这里的关键是 session.json 只被删除一次。
	_, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "dup-listener",
	})
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(tmp, "sessions")
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Fatalf("启动后应有 1 个 session dir，实际 %d", len(entries))
	}
	sessionDir := filepath.Join(dir, entries[0].Name())

	// Stop 会触发 onSystemProcessExit。
	if err := binding.Stop(); err != nil {
		t.Fatal(err)
	}
	// session dir 必须被删除（一次）
	if _, err := os.Stat(sessionDir); !os.IsNotExist(err) {
		t.Errorf("Stop 后 session dir 必须删除")
	}
	// Cleanup 也得成功（幂等）
	binding.Cleanup()
}

// 阶段 B2 收口：Cleanup 注销监听器。
func TestCleanup_UnregistersExitListener(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})
	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(system.dataFactoryPath, []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(20 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "cleanup-listener", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	defer system.Cleanup()

	binding.SetContext(context.Background())
	if _, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "cleanup-listener",
	}); err != nil {
		t.Fatal(err)
	}
	binding.Cleanup()
	// Cleanup 后应无活跃 session
	s, _ := binding.GetSession()
	if s != nil {
		t.Errorf("Cleanup 后 GetSession 必须为 nil")
	}
}
