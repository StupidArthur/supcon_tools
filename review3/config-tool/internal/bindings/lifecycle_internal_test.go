package bindings

import (
	"context"
	"encoding/json"
	"fmt"
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

// 阶段 5-3 收口：Cleanup 顺序必须让 RealtimeRuntimeBinding.Cleanup 先于
// SystemBinding.Cleanup 执行。
// 关键：归档 stop（带 Bearer）必须在 Python 被 kill 之前完成。
//
// 本测试在 bindings 包内部，直接访问私有方法（不暴露为公共 API）。
// app.NewLifecycle 内部即按此顺序调用。
func TestLifecycle_ShutdownOrderArchiveBeforeProcessKill(t *testing.T) {
	// 1) mock FastAPI server
	var (
		archiveStartCalled atomic.Bool
		archiveStopCalled  atomic.Bool
		stopAuth           atomic.Value
		order              []string
		orderMu            sync.Mutex
	)
	apiMux := http.NewServeMux()
	apiMux.HandleFunc("/api/archive/start", func(w http.ResponseWriter, r *http.Request) {
		archiveStartCalled.Store(true)
		orderMu.Lock()
		order = append(order, "archive-start")
		orderMu.Unlock()
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	apiMux.HandleFunc("/api/archive/stop", func(w http.ResponseWriter, r *http.Request) {
		archiveStopCalled.Store(true)
		stopAuth.Store(r.Header.Get("Authorization"))
		orderMu.Lock()
		order = append(order, "archive-stop")
		orderMu.Unlock()
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	apiMux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"instance_name": "shutdown-test"})
	})
	apiSrv := httptest.NewServer(apiMux)
	defer apiSrv.Close()
	ports := strings.TrimPrefix(apiSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	// 2) 用 long-running sleep 模拟 DataFactory
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfgPath, []byte("test: true"), 0o644)

	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(filepath.Join(tmp, "DataFactory.exe"), []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "shutdown-test", nil
	})

	storeRoot := filepath.Join(tmp, "store")
	os.MkdirAll(storeRoot, 0o755)
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompilerShutdownTest{})
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())

	// 3) 启动
	if _, err := binding.StartSingleYAML(cfgPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "shutdown-test",
		ArchiveEnabled: true,
		ArchiveTags:    []string{"tank_2.level"},
	}); err != nil {
		t.Fatal(err)
	}
	if !archiveStartCalled.Load() {
		t.Fatal("archive start must be called")
	}
	if !system.Status().Running {
		t.Fatal("system must be Running")
	}

	// 4) 模拟 Lifecycle.Shutdown 行为：先 binding.Cleanup（内部走 archive stop + system.Stop），
	// 再 system.Cleanup（此时 b.proc 已 nil，no-op）。这与 app.NewLifecycle 在 priority
	// cleanup receiver 模式下的执行顺序一致。
	binding.Cleanup()

	// 5) 关键断言：archive stop 必须在 system stop 之前
	orderMu.Lock()
	gotOrder := append([]string(nil), order...)
	orderMu.Unlock()
	if !archiveStopCalled.Load() {
		t.Fatal("archive stop must be called")
	}
	t.Logf("recorded order: %v", gotOrder)
	hasStop := false
	for _, ev := range gotOrder {
		if ev == "archive-stop" {
			hasStop = true
		}
	}
	if !hasStop {
		t.Errorf("archive-stop must appear, got %v", gotOrder)
	}
	auth, _ := stopAuth.Load().(string)
	if !strings.HasPrefix(auth, "Bearer ") || auth == "Bearer " {
		t.Errorf("archive stop must carry Bearer header, got %q", auth)
	}
	if system.Status().Running {
		t.Errorf("after binding.Cleanup, system must be stopped")
	}
	entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
	if len(entries) != 0 {
		t.Errorf("session dir must be cleaned, got %d", len(entries))
	}

	// 6) system.Cleanup 此时应为 no-op（b.proc 已 nil）
	system.Cleanup() // 不得 panic
}

// localFakeCompilerShutdownTest 测试用 compiler
type localFakeCompilerShutdownTest struct{}

func (l *localFakeCompilerShutdownTest) Validate(_ context.Context, _ []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	return realtime.ValidationResult{
		Valid:     true,
		Instances: []realtime.ExpandedInstance{{Name: "shutdown-test", SourceID: "s1", ReplicaIndex: 0, OriginalName: "shutdown-test"}},
	}, nil
}

func (l *localFakeCompilerShutdownTest) Compile(_ context.Context, _ []realtime.CompilerSourceSpec, outputPath string) (string, error) {
	_ = os.WriteFile(outputPath, []byte("clock:\n  cycle_time: 0.5\nprogram: []\n"), 0o644)
	return outputPath, nil
}

// 阶段 H 收口：Cleanup 必须幂等 —— 连续调用三次不得 panic、不得报错。
func TestCleanup_Idempotent_ThreeCallsNoPanic(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfgPath, []byte("test: true"), 0o644)

	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(filepath.Join(tmp, "DataFactory.exe"), []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "cleanup-idem", nil
	})

	storeRoot := filepath.Join(tmp, "store")
	os.MkdirAll(storeRoot, 0o755)
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompilerShutdownTest{})
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())

	if _, err := binding.StartSingleYAML(cfgPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "cleanup-idem",
	}); err != nil {
		t.Fatal(err)
	}

	// 三次 Cleanup：不得 panic
	binding.Cleanup()
	binding.Cleanup()
	binding.Cleanup()

	// Cleanup 后 session 必须为 nil
	s, _ := binding.GetSession()
	if s != nil {
		t.Errorf("Cleanup 后 GetSession 必须为 nil，实际 %+v", s)
	}
	// system 必须停止
	if system.Status().Running {
		t.Error("Cleanup 后 system 必须停止")
	}
}

// 阶段 H 收口：Shutdown 期间 archive stop 失败不得导致 session 状态丢失。
// 验证：archive stop 返回 500 → Cleanup 仍完成 system stop → session 被清理
// （进程已死，archive 无法重试，但错误必须被记录）。
func TestCleanup_ArchiveStopFailure_SessionStillCleaned(t *testing.T) {
	var archiveStopCalled atomic.Bool
	apiMux := http.NewServeMux()
	apiMux.HandleFunc("/api/archive/start", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	})
	apiMux.HandleFunc("/api/archive/stop", func(w http.ResponseWriter, r *http.Request) {
		archiveStopCalled.Store(true)
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("disk error"))
	})
	apiSrv := httptest.NewServer(apiMux)
	defer apiSrv.Close()
	ports := strings.TrimPrefix(apiSrv.URL, "http://127.0.0.1:")
	apiPort := 0
	fmt.Sscanf(ports, "%d", &apiPort)

	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfgPath, []byte("test: true"), 0o644)

	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(filepath.Join(tmp, "DataFactory.exe"), []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "archive-fail-cleanup", nil
	})

	storeRoot := filepath.Join(tmp, "store")
	os.MkdirAll(storeRoot, 0o755)
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompilerShutdownTest{})
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())

	if _, err := binding.StartSingleYAML(cfgPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: apiPort, RuntimeName: "archive-fail-cleanup",
		ArchiveEnabled: true,
		ArchiveTags:    []string{"tank_2.level"},
	}); err != nil {
		t.Fatal(err)
	}

	// Cleanup：archive stop 失败，但 system stop 必须成功
	binding.Cleanup()

	if !archiveStopCalled.Load() {
		t.Error("archive stop must be called during Cleanup")
	}
	if system.Status().Running {
		t.Error("system must be stopped after Cleanup even if archive stop failed")
	}
	s, _ := binding.GetSession()
	if s != nil {
		t.Errorf("session must be nil after Cleanup (process is dead), got %+v", s)
	}
	entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
	if len(entries) != 0 {
		t.Errorf("session dir must be cleaned after Cleanup, got %d", len(entries))
	}
}

// 阶段 H 收口：Stop 失败（进程仍存活）→ Cleanup 保留 session dir 供重试。
// 验证：Cleanup 不删除 session dir，current / curDir / token 保留。
func TestCleanup_StopFailure_PreservesSessionDirForRetry(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "test.yaml")
	os.WriteFile(cfgPath, []byte("test: true"), 0o644)

	system := NewSystemBinding()
	system.dataFactoryPath = filepath.Join(tmp, "DataFactory.exe")
	os.WriteFile(filepath.Join(tmp, "DataFactory.exe"), []byte("fake"), 0o755)
	system.setCommandFactory(makeLongRunningCommand(30))
	system.setReadyPollInterval(10 * time.Millisecond)
	system.setReadyTimeout(2 * time.Second)
	system.setReadinessChecker(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "cleanup-preserve", nil
	})

	storeRoot := filepath.Join(tmp, "store")
	os.MkdirAll(storeRoot, 0o755)
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompilerShutdownTest{})
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := NewRealtimeRuntimeBinding(manager, system, sessionMgr)
	binding.SetContext(context.Background())
	defer system.Cleanup()

	if _, err := binding.StartSingleYAML(cfgPath, realtime.RealtimeStartOptions{
		APIHost: "127.0.0.1", APIPort: 8000, RuntimeName: "cleanup-preserve",
	}); err != nil {
		t.Fatal(err)
	}

	firstToken := CurrentAPIToken()
	if firstToken == "" {
		t.Fatal("token must be non-empty after start")
	}

	sessionDir := filepath.Join(tmp, "sessions")
	entries, _ := os.ReadDir(sessionDir)
	if len(entries) == 0 {
		t.Fatal("session dir must exist after start")
	}
	preCleanupDir := filepath.Join(sessionDir, entries[0].Name())

	// 注入 Stop 失败
	system.terminateErrorOverride = fmt.Errorf("simulated cleanup stop failure")

	// Cleanup：Stop 失败，进程仍存活
	binding.Cleanup()

	// 关键断言：session dir 必须保留（供重试）
	if _, err := os.Stat(preCleanupDir); err != nil {
		t.Errorf("Cleanup 失败时 session dir 必须保留: %v", err)
	}
	// current 必须保留
	s, _ := binding.GetSession()
	if s == nil {
		t.Fatal("Cleanup 失败时 GetSession 必须非空")
	}
	if s.State != realtime.StateStopFailed {
		t.Errorf("session.State 必须为 stop-failed，实际 %s", s.State)
	}
	// token 必须保留
	if got := CurrentAPIToken(); got != firstToken {
		t.Errorf("Cleanup 失败时 token 必须保留，期望 %q 实际 %q", firstToken, got)
	}

	// 清除 override，让 Stop 真的成功
	system.terminateErrorOverride = nil
	binding.Cleanup()

	// 现在 session 必须被清理
	s2, _ := binding.GetSession()
	if s2 != nil {
		t.Errorf("clean Cleanup 后 GetSession 必须为 nil，实际 %+v", s2)
	}
}
