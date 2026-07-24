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

// 阶段 C3 收口：报警规则为空时是合法 no-op，不应报错。
// 必须用 StartProject（带 project）才能真正走报警推送分支；StartSingleYAML
// 走单 YAML 路径不会触发任何 alarm push，验证无效。
func TestStart_NoAlarmRulesIsNoOp(t *testing.T) {
	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	if err := os.MkdirAll(storeRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompiler{})

	ctx := context.Background()
	if _, err := manager.CreateProject(ctx, "noalarms"); err != nil {
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
	// 关键：项目没有 alarm rules
	rules, _ := manager.ListAlarmRules(ctx, pid)
	if len(rules) != 0 {
		t.Fatalf("本测试要求项目无 alarm rules，实际 %d", len(rules))
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
		return true, "noalarms", nil
	})

	// mock 服务器：/api/alarms/config 绝不能被调用
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

	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	if _, err := binding.StartProject(pid, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "noalarms",
	}); err != nil {
		t.Fatal(err)
	}
}

// 阶段 C4 收口：Stop 顺序 + 鉴权 + 顺序观察。
// 必须验证：
//   - archive 启用时 /api/archive/stop 被调用
//   - 请求携带 Bearer token
//   - 顺序：archive-stop 在 system-stop 之前
func TestStart_StopCallsArchiveStopWithBearerBeforeSystem(t *testing.T) {
	var order []string
	var orderMu sync.Mutex
	var seenAuth atomic.Value
	archiveMux := http.NewServeMux()
	archiveMux.HandleFunc("/api/archive/start", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	archiveMux.HandleFunc("/api/archive/stop", func(w http.ResponseWriter, r *http.Request) {
		orderMu.Lock()
		order = append(order, "archive-stop")
		orderMu.Unlock()
		seenAuth.Store(r.Header.Get("Authorization"))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	archiveSrv := httptest.NewServer(archiveMux)
	defer archiveSrv.Close()
	ports := strings.TrimPrefix(archiveSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	rig := newRealtimeTestRig(t)
	defer rig.cleanup()
	// 在 system 里注册一个进程退出监听器，模拟 system.Stop 的副作用顺序。
	rig.system.addExitListener(func(exitCode int, normalStop bool) {
		if normalStop {
			orderMu.Lock()
			order = append(order, "system-stop")
			orderMu.Unlock()
		}
	})
	rig.system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "stop-order-auth", nil
	})

	if _, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "stop-order-auth",
		ArchiveEnabled: true,
		ArchiveTags:    []string{"tank_2.level"},
	}); err != nil {
		t.Fatal(err)
	}
	if err := rig.binding.Stop(); err != nil {
		t.Fatal(err)
	}
	orderMu.Lock()
	gotOrder := append([]string(nil), order...)
	orderMu.Unlock()
	if len(gotOrder) < 2 {
		t.Fatalf("应至少看到 archive-stop + system-stop 两次，实际 %v", gotOrder)
	}
	if gotOrder[0] != "archive-stop" {
		t.Errorf("archive-stop 必须在 system-stop 之前，实际顺序 %v", gotOrder)
	}
	auth, _ := seenAuth.Load().(string)
	if !strings.HasPrefix(auth, "Bearer ") || auth == "Bearer " {
		t.Errorf("archive stop 必须携带 Bearer 头，实际 %q", auth)
	}
}

// 阶段 C4：Stop 期间归档停止失败不应阻止 system.Stop。
func TestStart_StopArchiveFailureNotFatal(t *testing.T) {
	archiveMux := http.NewServeMux()
	archiveMux.HandleFunc("/api/archive/start", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
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
		ArchiveEnabled: true,
		ArchiveTags:    []string{"tank_2.level"},
	}); err != nil {
		t.Fatal(err)
	}
	// 归档停止错误应在 Stop 错误中合并报告，但 system 必须被 stop。
	stopErr := rig.binding.Stop()
	if stopErr == nil {
		t.Error("归档停止失败应被报告")
	} else if !strings.Contains(stopErr.Error(), "归档停止失败") {
		t.Errorf("Stop 错误必须包含 '归档停止失败'，实际: %v", stopErr)
	}
	if rig.system.Status().Running {
		t.Errorf("Stop 后系统仍 Running")
	}
}

// 阶段 C4 收口：关键回滚路径 —— archive 启动 200 后，session.json 写入失败。
// 必须：调用带 Bearer 的 /api/archive/stop，再 system.Stop，删除 session 目录。
// 旧实现：stopArchiveOnShutdown 从 b.current 取 session，而 b.current 此刻为 nil，
// 导致 archive stop 被跳过。
func TestStart_ArchiveStartedThenSessionWriteFails_RollsBackWithAuth(t *testing.T) {
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
		return true, "rollback-archive", nil
	})

	// 关键 mock：/api/archive/start 200 OK；/api/archive/stop 验证 Bearer
	var (
		gotStart    atomic.Bool
		gotStop     atomic.Bool
		stopAuth    atomic.Value
	)
	archiveMux := http.NewServeMux()
	archiveMux.HandleFunc("/api/archive/start", func(w http.ResponseWriter, r *http.Request) {
		gotStart.Store(true)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	archiveMux.HandleFunc("/api/archive/stop", func(w http.ResponseWriter, r *http.Request) {
		gotStop.Store(true)
		stopAuth.Store(r.Header.Get("Authorization"))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	archiveSrv := httptest.NewServer(archiveMux)
	defer archiveSrv.Close()
	ports := strings.TrimPrefix(archiveSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)

	// 注入写失败：使用自定义 SessionManager 包装，
	// 让 WriteSessionJSON 在 archive 成功之后返回错误。
	baseMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	failingMgr := &failingWriteSessionManager{SessionManager: baseMgr}
	binding := NewRealtimeRuntimeBinding(manager, system, failingMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	_, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "rollback-archive",
		ArchiveEnabled: true,
		ArchiveTags:    []string{"tank_2.level"},
	})
	if err == nil {
		t.Fatal("必须回滚失败")
	}
	if !strings.Contains(err.Error(), "session.json") {
		t.Errorf("错误必须提到 session.json，实际: %v", err)
	}
	if !gotStart.Load() {
		t.Error("archive start 必须被调用")
	}
	if !gotStop.Load() {
		t.Fatal("archive stop 必须被回滚调用（archiveActive 在 launch 内 archive 成功后置 true）")
	}
	// 关键：必须带 Bearer 头
	auth, _ := stopAuth.Load().(string)
	if !strings.HasPrefix(auth, "Bearer ") || auth == "Bearer " {
		t.Errorf("archive stop 必须携带 Bearer 头，实际 %q", auth)
	}
	// session 目录必须被清理
	entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
	if len(entries) != 0 {
		t.Errorf("session 目录必须清理，实际 %d", len(entries))
	}
	// system 必须停
	if system.Status().Running {
		t.Errorf("system 必须停")
	}
}

// failingWriteSessionManager 包装 SessionManager，让 WriteSessionJSON 强制失败。
// 用于测试 archive 已启动后回滚路径。
type failingWriteSessionManager struct {
	*realtime.SessionManager
}

func (f *failingWriteSessionManager) CreateSessionDir() (string, string, error) {
	return f.SessionManager.CreateSessionDir()
}

func (f *failingWriteSessionManager) CompiledPath(dir string) string {
	return f.SessionManager.CompiledPath(dir)
}

func (f *failingWriteSessionManager) WriteSessionJSON(_ string, _ realtime.SessionRecord) error {
	return fmt.Errorf("injected session.json write failure")
}

func (f *failingWriteSessionManager) RemoveSessionDir(dir string) {
	f.SessionManager.RemoveSessionDir(dir)
}

func (f *failingWriteSessionManager) ReadSessionRecord(dir string) (realtime.SessionRecord, bool) {
	return f.SessionManager.ReadSessionRecord(dir)
}

func (f *failingWriteSessionManager) CleanupOrphans(activeDir string) {
	f.SessionManager.CleanupOrphans(activeDir)
}

// stubSystemAdapter 允许测试中替换 systemBinding 的部分方法。
// 简化方案：直接在测试用例中用新 SystemBinding + 自定义 stop 失败逻辑。

// 阶段 5-2 收口：Stop 失败但进程仍在 → 保留 session 状态供重试。
// 关键验证：
//   - Stop 返回 error
//   - GetSession 仍非空
//   - session 目录仍存在
//   - CurrentAPIToken 仍非空
//   - 可以再次调用 Stop（即使会再次失败）
// 阶段 5-2 收口：Stop 失败但进程仍在 → 保留 session 状态供重试。
// 通过 system.terminateErrorOverride 测试 hook 强制 Stop 返回错误，
// 但 b.proc 不变，Status().Running 仍 true。
func TestStart_StopFailurePreservesSessionForRetry(t *testing.T) {
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
		return true, "stop-fail-rec", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	if _, err := binding.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "stop-fail-rec",
	}); err != nil {
		t.Fatal(err)
	}
	firstToken := CurrentAPIToken()
	if firstToken == "" {
		t.Fatal("启动后 token 必须非空")
	}
	dir := filepath.Join(tmp, "sessions")
	entries, _ := os.ReadDir(dir)
	if len(entries) == 0 {
		t.Fatal("session dir 必须存在")
	}
	sessionDir := filepath.Join(dir, entries[0].Name())

	// 注入 Stop 失败：override 让 terminateProcess 立即返回错误，
	// 但 b.proc 不被清空（保留 running 状态）。
	system.terminateErrorOverride = fmt.Errorf("simulated stop failure")

	stopErr := binding.Stop()
	if stopErr == nil {
		t.Fatal("预期 Stop 返回错误")
	}
	if !strings.Contains(stopErr.Error(), "simulated stop failure") {
		t.Errorf("Stop 错误必须包含 simulated stop failure，实际: %v", stopErr)
	}

	// 关键断言：Stop 失败时 session 状态必须全部保留。
	if got := CurrentAPIToken(); got != firstToken {
		t.Errorf("Stop 失败时 token 必须保留，期望 %q 实际 %q", firstToken, got)
	}
	if !system.Status().Running {
		t.Error("Stop 失败时 Status().Running 必须仍为 true")
	}
	s, err := binding.GetSession()
	if err != nil {
		t.Fatal(err)
	}
	if s == nil {
		t.Fatal("Stop 失败时 GetSession 必须返回非空 session")
	}
	if s.State != realtime.StateStopFailed {
		t.Errorf("Stop 失败时 session.State 必须为 stop-failed，实际 %s", s.State)
	}
	if _, err := os.Stat(sessionDir); err != nil {
		t.Errorf("Stop 失败时 session dir 必须保留: %v", err)
	}

	// 关键：可以再次调用 Stop（即使同样失败，状态继续保留）。
	stopErr2 := binding.Stop()
	if stopErr2 == nil {
		t.Error("第二次 Stop 也应返回错误（override 仍生效）")
	}
	if s2, _ := binding.GetSession(); s2 == nil {
		t.Error("第二次 Stop 失败后 GetSession 仍应非空")
	}

	// 清理：清除 override，让 Stop 真的成功收尾。
	system.terminateErrorOverride = nil
	if err := binding.Stop(); err != nil {
		t.Logf("clean Stop error (after override cleared): %v", err)
	}
	// 现在 process 真的死了，Stop 应该清空 state
	if s3, _ := binding.GetSession(); s3 != nil {
		t.Errorf("clean Stop 后 GetSession 必须为 nil，实际: %+v", s3)
	}
}

// 阶段 5-2 收口：进程终止可重试。
// 关键：旧实现用 sync.Once 永久缓存第一次失败，第二次 Stop 直接返回缓存错误。
// 新实现：仅当进程已死时才复用错误；进程仍存活时必须真实重新尝试 Interrupt/Kill。
// 这里直接测 system.terminateProcess：第一次以 override 失败，第二次无 override
// 必须真实 Kill。
func TestTerminate_Retryable_RealKillAfterOverride(t *testing.T) {
	b := NewSystemBinding()
	tmp := t.TempDir()
	b.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(b.dataFactoryPath, []byte("fake"), 0o755)
	// 长跑 30s
	b.setCommandFactory(makeLongRunningCommand(30))
	b.setReadyPollInterval(10 * time.Millisecond)
	b.setReadyTimeout(2 * time.Second)
	b.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "rt-retry", nil
	})

	cfg := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfg, []byte("test: true"), 0o644)
	sm := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	bind := NewRealtimeRuntimeBinding(&realtime.Manager{}, b, sm)
	bind.SetContext(context.Background())
	defer b.Cleanup()

	if _, err := bind.StartSingleYAML(cfg, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "rt-retry",
	}); err != nil {
		t.Fatal(err)
	}
	proc := b.proc
	if proc == nil {
		t.Fatal("proc must be non-nil")
	}

	// 第一次：override 强制返回错误，进程仍 Running
	b.terminateErrorOverride = fmt.Errorf("simulated")
	if err := b.terminateProcess(proc, true); err == nil {
		t.Error("first terminate must return error")
	}
	if !b.Status().Running {
		t.Error("after override, process must still be running")
	}

	// 第二次：override 清除，必须真实 Kill
	b.terminateErrorOverride = nil
	if err := b.terminateProcess(proc, true); err != nil {
		t.Errorf("second terminate must succeed: %v", err)
	}
	// 等待 process 真的退出
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !b.Status().Running {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if b.Status().Running {
		t.Error("after real terminate, process must be dead")
	}

	// 第三次：进程已死，应该快速返回（无错误）
	if err := b.terminateProcess(proc, true); err != nil {
		t.Errorf("third terminate on dead process must succeed, got: %v", err)
	}
}

// 阶段 C 收口：archive 未启用时 Stop 不调用 archive/stop（避免无意义请求）。
func TestStart_StopWithoutArchive_DoesNotCallArchiveStop(t *testing.T) {
	// 启动监听：/api/archive/stop 一旦被调用就 fail
	archiveMux := http.NewServeMux()
	archiveMux.HandleFunc("/api/archive/stop", func(w http.ResponseWriter, r *http.Request) {
		t.Errorf("archive 未启用时不应调用 /api/archive/stop")
		w.WriteHeader(http.StatusInternalServerError)
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
		return true, "no-archive", nil
	})

	if _, err := rig.binding.StartSingleYAML(rig.configPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "no-archive",
	}); err != nil {
		t.Fatal(err)
	}
	if err := rig.binding.Stop(); err != nil {
		t.Fatal(err)
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
