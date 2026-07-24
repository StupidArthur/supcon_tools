package app

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

	"config-tool/internal/bindings"
	"config-tool/internal/realtime"
)

// TestHelperProcess 是 makeLongRunningCommand 使用的子进程 helper。
// 必须在 app 测试包内，使 go test ./internal/app/... 生成的 binary 中能找到这个 Test。
func TestHelperProcess(t *testing.T) {
	if os.Getenv("GO_WANT_HELPER_PROCESS") != "1" {
		return
	}
	if sleep := os.Getenv("HELPER_SLEEP"); sleep != "" {
		var seconds int
		fmt.Sscanf(sleep, "%d", &seconds)
		time.Sleep(time.Duration(seconds) * time.Second)
	}
	os.Exit(0)
}

// 阶段 5-3 收口：Lifecycle.Shutdown 必须让 RealtimeRuntimeBinding.Cleanup
// 先于 SystemBinding.Cleanup 执行。
// 关键：归档 stop（带 Bearer）必须在 Python 被 kill 之前完成。
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

	system := bindings.NewSystemBinding()
	system.SetDataFactoryPathForTest(filepath.Join(tmp, "DataFactory.exe"))
	os.WriteFile(filepath.Join(tmp, "DataFactory.exe"), []byte("fake"), 0o755)
	system.SetCommandFactoryForTest(bindings.MakeLongRunningCommandForTest(30))
	system.SetReadyPollIntervalForTest(10 * time.Millisecond)
	system.SetReadyTimeoutForTest(2 * time.Second)
	system.SetReadinessCheckerForTest(func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		if token == "" {
			return false, "", nil
		}
		return true, "shutdown-test", nil
	})

	storeRoot := filepath.Join(tmp, "store")
	os.MkdirAll(storeRoot, 0o755)
	storage := realtime.NewProjectStorage(storeRoot)
	manager := realtime.NewManager(storage, &localFakeCompilerApp{})
	sessionMgr := realtime.NewSessionManager(filepath.Join(tmp, "sessions"))
	binding := bindings.NewRealtimeRuntimeBinding(manager, system, sessionMgr)
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
		t.Fatal("archive start 必须被调用")
	}
	if !system.Status().Running {
		t.Fatal("system 必须 Running")
	}

	// 4) 启动 Lifecycle 关闭（模拟应用关闭）
	lifecycle := NewLifecycle(system, binding)
	lifecycle.Shutdown(context.Background())

	// 5) 关键断言：archive stop 必须在 system stop 之前
	orderMu.Lock()
	gotOrder := append([]string(nil), order...)
	orderMu.Unlock()
	if !archiveStopCalled.Load() {
		t.Fatal("archive stop 必须被调用")
	}
	t.Logf("recorded order: %v", gotOrder)
	hasStop := false
	for _, ev := range gotOrder {
		if ev == "archive-stop" {
			hasStop = true
		}
	}
	if !hasStop {
		t.Errorf("archive-stop 必须出现，实际 %v", gotOrder)
	}
	// auth 必须带 Bearer
	auth, _ := stopAuth.Load().(string)
	if !strings.HasPrefix(auth, "Bearer ") || auth == "Bearer " {
		t.Errorf("archive stop 必须携带 Bearer 头，实际 %q", auth)
	}
	// 进程必须真的停止
	if system.Status().Running {
		t.Errorf("Lifecycle.Shutdown 后 system 必须停止")
	}
	// session 目录必须清理
	entries, _ := os.ReadDir(filepath.Join(tmp, "sessions"))
	if len(entries) != 0 {
		t.Errorf("session 目录必须清理，实际 %d 个", len(entries))
	}
}

// localFakeCompilerApp 测试用 compiler
type localFakeCompilerApp struct{}

func (l *localFakeCompilerApp) Validate(_ context.Context, _ []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	return realtime.ValidationResult{
		Valid:     true,
		Instances: []realtime.ExpandedInstance{{Name: "shutdown-test", SourceID: "s1", ReplicaIndex: 0, OriginalName: "shutdown-test"}},
	}, nil
}

func (l *localFakeCompilerApp) Compile(_ context.Context, _ []realtime.CompilerSourceSpec, outputPath string) (string, error) {
	_ = os.WriteFile(outputPath, []byte("clock:\n  cycle_time: 0.5\nprogram: []\n"), 0o644)
	return outputPath, nil
}
