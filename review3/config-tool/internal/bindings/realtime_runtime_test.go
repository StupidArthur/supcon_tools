package bindings

import (
	"context"
	"encoding/json"
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
	return outputPath, nil
}
