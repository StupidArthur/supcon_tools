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
