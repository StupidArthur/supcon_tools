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
	"testing"

	"config-tool/internal/realtime"
)

// mockReloadServer creates mock service that captures /api/project/reload body and
// optionally returns 500 to test error propagation (todo.md §六).
type mockReloadCapture struct {
	mu          sync.Mutex
	calls       []map[string]string
	return500   bool
}

func (c *mockReloadCapture) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/project/open", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true,"projectFile":"` + r.Header.Get("X-Captured-Pf") + `","projectName":"T"}`))
	})
	mux.HandleFunc("/api/project/reload", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]string
		if r.Body != nil {
			json.NewDecoder(r.Body).Decode(&body)
		}
		c.mu.Lock()
		c.calls = append(c.calls, body)
		c.mu.Unlock()
		if c.return500 {
			w.WriteHeader(http.StatusInternalServerError)
			w.Write([]byte(`{"detail":"simulated reload failure"}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true}`))
	})
	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true,"protocolVersion":1,"serviceState":"ready","runtimeState":"stopped"}`))
	})
	mux.HandleFunc("/api/runtime/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true,"runtimeState":"stopped","serviceState":"ready"}`))
	})
	mux.HandleFunc("/api/instances/default/tags", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	})
	return mux
}

func newReloadCaptureFixture(t *testing.T, return500 bool) (*RealtimeProjectBinding, *mockReloadCapture, *httptest.Server, string) {
	t.Helper()
	cap := &mockReloadCapture{return500: return500}
	srv := httptest.NewServer(cap.handler())
	port := srv.Listener.Addr().(*net.TCPAddr).Port

	tmp := t.TempDir()
	storeRoot := filepath.Join(tmp, "store")
	os.MkdirAll(storeRoot, 0o755)
	storage := realtime.NewProjectStorage(storeRoot)

	// 生成一个最小合法 project.yaml + 一个 sources/*.yaml
	projectDir := filepath.Join(tmp, "p1")
	os.MkdirAll(filepath.Join(projectDir, "sources"), 0o755)
	yamlPath := filepath.Join(projectDir, "sources", "src.yaml")
	os.WriteFile(yamlPath, []byte("clock:\n  mode: GENERATOR\n  cycle_time: 0.5\nprogram:\n  - name: a\n    type: Variable\n    value: 1.0\n"), 0o644)
	projectFile := filepath.Join(projectDir, "project.yaml")
	projectContent := fmt.Sprintf("version: 1\nid: p1\nname: T\nsources:\n  - id: s1\n    file: sources/src.yaml\n    replicas: 1\n")
	os.WriteFile(projectFile, []byte(projectContent), 0o644)

	manager := realtime.NewManager(storage, &lazyCompiler{})

	binding := NewRealtimeProjectBinding(manager)
	binding.SetContext(context.Background())
	client := NewDataFactoryServiceClient("127.0.0.1", port, "test-token")
	binding.SetServiceClient(client)
	_, err := manager.OpenProjectFile(context.Background(), projectFile)
	if err != nil {
		t.Fatalf("setup OpenProjectFile: %v", err)
	}

	return binding, cap, srv, projectFile
}

// lazyCompiler 避免 manager 校验/编译时触碰 NoneServiceCompile。
type lazyCompiler struct{}

func (c *lazyCompiler) Validate(_ context.Context, _ []realtime.CompilerSourceSpec) (realtime.ValidationResult, error) {
	return realtime.ValidationResult{Valid: true, Instances: []realtime.ExpandedInstance{}}, nil
}

func (c *lazyCompiler) Compile(_ context.Context, _ []realtime.CompilerSourceSpec, outputPath string) (string, error) {
	if err := os.WriteFile(outputPath, []byte("merged: ok\n"), 0o644); err != nil {
		return "", err
	}
	return outputPath, nil
}

// §六 — cold open 顺序：inspect → open；
// reload body 必须含 projectFile；reload 错误不会被公开方法吞掉。
// 切换工程后 compiler 不残留旧 projectFile（本轮已不再维护 compiler.projectFile 状态）。

func TestSyncProjectReload_BodyContainsProjectFile(t *testing.T) {
	binding, cap, srv, projectFile := newReloadCaptureFixture(t, false)
	defer srv.Close()

	if err := binding.syncProjectReload(projectFile); err != nil {
		t.Fatalf("syncProjectReload: %v", err)
	}

	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.calls) != 1 {
		t.Fatalf("reload 应被调用 1 次，实际 %d", len(cap.calls))
	}
	got, ok := cap.calls[0]["projectFile"]
	if !ok || got == "" {
		t.Fatalf("reload body 必须包含 projectFile，实际 body = %v", cap.calls[0])
	}
	if got != projectFile {
		t.Fatalf("reload body projectFile = %q，期望 %q", got, projectFile)
	}
}

func TestAddSourceAt_SendsReload_WithProjectFile(t *testing.T) {
	binding, cap, srv, projectFile := newReloadCaptureFixture(t, false)
	defer srv.Close()

	// 直接调 AddSourceAt：manager 写入项目，binding 应触发 reload(body=projectFile)
	newYaml := filepath.Join(filepath.Dir(projectFile), "sources", "added.yaml")
	if err := os.WriteFile(newYaml, []byte("clock:\n  mode: GENERATOR\n  cycle_time: 0.5\nprogram:\n  - name: added\n    type: Variable\n    value: 2.0\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := binding.AddSourceAt("p1", projectFile, newYaml)
	if err != nil {
		t.Fatalf("AddSourceAt: %v", err)
	}

	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.calls) == 0 {
		t.Fatal("AddSourceAt 后应至少触发一次 reload")
	}
	last := cap.calls[len(cap.calls)-1]
	if last["projectFile"] != projectFile {
		t.Fatalf("reload body projectFile = %q，期望 %q", last["projectFile"], projectFile)
	}
}

func TestRemoveSourceAt_SendsReload_WithProjectFile(t *testing.T) {
	binding, cap, srv, projectFile := newReloadCaptureFixture(t, false)
	defer srv.Close()

	_, err := binding.RemoveSourceAt("p1", projectFile, "s1")
	if err != nil {
		t.Fatalf("RemoveSourceAt: %v", err)
	}

	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.calls) == 0 {
		t.Fatal("RemoveSourceAt 后应至少触发一次 reload")
	}
	last := cap.calls[len(cap.calls)-1]
	if last["projectFile"] != projectFile {
		t.Fatalf("reload body projectFile = %q，期望 %q", last["projectFile"], projectFile)
	}
}

func TestUpdateReplicasAt_SendsReload_WithProjectFile(t *testing.T) {
	binding, cap, srv, projectFile := newReloadCaptureFixture(t, false)
	defer srv.Close()

	_, err := binding.UpdateReplicasAt("p1", projectFile, "s1", 3)
	if err != nil {
		t.Fatalf("UpdateReplicasAt: %v", err)
	}

	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.calls) == 0 {
		t.Fatal("UpdateReplicasAt 后应至少触发一次 reload")
	}
	last := cap.calls[len(cap.calls)-1]
	if last["projectFile"] != projectFile {
		t.Fatalf("reload body projectFile = %q，期望 %q", last["projectFile"], projectFile)
	}
}

func TestUpdateRuntime_SendsReload_WithProjectFile(t *testing.T) {
	binding, cap, srv, projectFile := newReloadCaptureFixture(t, false)
	defer srv.Close()

	// UpdateRuntimeAt 校验后保存；binding.UpdateRuntime 需要 projectID+projectFile
	_, err := binding.UpdateRuntime("p1", projectFile, realtime.Runtime{
		CycleTime: 0.5,
		OPCUAHost: "127.0.0.1",
		OPCUAPort: 4840,
	})
	if err != nil {
		t.Fatalf("UpdateRuntime: %v", err)
	}

	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.calls) == 0 {
		t.Fatal("UpdateRuntime 后应至少触发一次 reload")
	}
	last := cap.calls[len(cap.calls)-1]
	if last["projectFile"] != projectFile {
		t.Fatalf("reload body projectFile = %q，期望 %q", last["projectFile"], projectFile)
	}
}

func TestReloadFailureIsReturnedToCaller_NotSwallowed(t *testing.T) {
	binding, cap, srv, projectFile := newReloadCaptureFixture(t, true)
	defer srv.Close()

	// AddSourceAt 已 save 项目文件但 reload 失败 → 必须返回错误（不能 _ =）
	newYaml := filepath.Join(filepath.Dir(projectFile), "sources", "added500.yaml")
	if err := os.WriteFile(newYaml, []byte("clock:\n  mode: GENERATOR\n  cycle_time: 0.5\nprogram:\n  - name: a500\n    type: Variable\n    value: 1.0\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := binding.AddSourceAt("p1", projectFile, newYaml)
	if err == nil {
		t.Fatal("reload 500 时 AddSourceAt 必须返回错误给前端")
	}
	if !strings.Contains(err.Error(), "同步到运行服务失败") {
		t.Fatalf("错误信息必须提示同步失败，实际: %v", err)
	}

	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.calls) == 0 {
		t.Fatal("reload 应至少被调用 1 次（即使返回 500）")
	}
}

func TestOpenProjectFile_ColdService_InspectsBeforeOpen(t *testing.T) {
	// 使用真实 ServiceRealtimeCompiler 验证冷启动顺序：/api/project/inspect → /api/project/open。
	// 不依赖服务已有 project context，不发送 projectFile 到 inspect（Go 只传 sources）。
	var mu sync.Mutex
	var calls []string

	mux := http.NewServeMux()

	mux.HandleFunc("/api/project/inspect", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls = append(calls, "inspect")
		var body map[string]json.RawMessage
		json.NewDecoder(r.Body).Decode(&body)
		mu.Unlock()

		// 断言没有 projectFile
		if _, ok := body["projectFile"]; ok {
			t.Error("inspect 请求不应包含 projectFile")
		}
		// 断言有 sources
		sourcesRaw, ok := body["sources"]
		if !ok {
			t.Error("inspect 请求必须包含 sources")
		} else {
			var sources []struct {
				ID       string `json:"id"`
				File     string `json:"file"`
				Replicas int    `json:"replicas"`
			}
			json.Unmarshal(sourcesRaw, &sources)
			if len(sources) == 0 {
				t.Error("sources 不得为空")
			}
			// 断言 source.file 是绝对路径
			for _, s := range sources {
				if !filepath.IsAbs(s.File) {
					t.Errorf("source.file 必须是绝对路径，实际 %q", s.File)
				}
			}
		}

		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true,"valid":true,"instances":[],"duplicates":[]}`))
	})

	mux.HandleFunc("/api/project/open", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls = append(calls, "open")
		var body map[string]string
		json.NewDecoder(r.Body).Decode(&body)
		mu.Unlock()

		if body["projectFile"] == "" {
			t.Error("/api/project/open 必须携带 projectFile")
		}
		pf := body["projectFile"]
		pfEscaped := strings.ReplaceAll(pf, `\`, `\\`)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true,"projectFile":"` + pfEscaped + `","projectName":"T","validation":{"ok":true,"valid":true,"instances":[],"duplicates":[]}}`))
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()
	port := srv.Listener.Addr().(*net.TCPAddr).Port

	client := NewDataFactoryServiceClient("127.0.0.1", port, "test-token")
	compiler := NewServiceRealtimeCompiler(client)
	storage := realtime.NewProjectStorage(t.TempDir())
	manager := realtime.NewManager(storage, compiler)
	binding := NewRealtimeProjectBinding(manager)
	binding.SetContext(context.Background())
	binding.SetServiceClient(client)

	// 准备真实 project.yaml + sources/*.yaml
	projectDir := t.TempDir()
	os.MkdirAll(filepath.Join(projectDir, "sources"), 0o755)
	yamlPath := filepath.Join(projectDir, "sources", "src.yaml")
	os.WriteFile(yamlPath, []byte("clock:\n  mode: GENERATOR\n  cycle_time: 0.5\nprogram:\n  - name: a\n    type: Variable\n    value: 1.0\n"), 0o644)
	projectFile := filepath.Join(projectDir, "project.yaml")
	projectContent := "version: 1\nid: p1\nname: T\nsources:\n  - id: s1\n    file: sources/src.yaml\n    replicas: 1\n"
	os.WriteFile(projectFile, []byte(projectContent), 0o644)

	_, err := binding.OpenProjectFile(projectFile)
	if err != nil {
		t.Fatalf("OpenProjectFile: %v", err)
	}

	mu.Lock()
	callCopy := append([]string(nil), calls...)
	mu.Unlock()

	if len(callCopy) < 2 {
		t.Fatalf("期望至少 inspect + open 两次调用，实际 %v", callCopy)
	}
	if callCopy[0] != "inspect" {
		t.Fatalf("第一个调用必须是 inspect，实际顺序 %v", callCopy)
	}
	if callCopy[1] != "open" {
		t.Fatalf("第二个调用必须是 open，实际顺序 %v", callCopy)
	}
}

func TestOpenProjectFile_InspectFailure_DoesNotOpenServiceProject(t *testing.T) {
	var mu sync.Mutex
	var calls []string

	mux := http.NewServeMux()

	mux.HandleFunc("/api/project/inspect", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls = append(calls, "inspect")
		mu.Unlock()
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"detail":"simulated inspect failure"}`))
	})

	mux.HandleFunc("/api/project/open", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls = append(calls, "open")
		mu.Unlock()
		t.Error("/api/project/open 不应该被调用（inspect 已失败）")
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()
	port := srv.Listener.Addr().(*net.TCPAddr).Port

	client := NewDataFactoryServiceClient("127.0.0.1", port, "test-token")
	compiler := NewServiceRealtimeCompiler(client)
	storage := realtime.NewProjectStorage(t.TempDir())
	manager := realtime.NewManager(storage, compiler)
	binding := NewRealtimeProjectBinding(manager)
	binding.SetContext(context.Background())
	binding.SetServiceClient(client)

	projectDir := t.TempDir()
	os.MkdirAll(filepath.Join(projectDir, "sources"), 0o755)
	yamlPath := filepath.Join(projectDir, "sources", "src.yaml")
	os.WriteFile(yamlPath, []byte("clock:\n  mode: GENERATOR\n  cycle_time: 0.5\nprogram:\n  - name: a\n    type: Variable\n    value: 1.0\n"), 0o644)
	projectFile := filepath.Join(projectDir, "project.yaml")
	os.WriteFile(projectFile, []byte("version: 1\nid: p1\nname: T\nsources:\n  - id: s1\n    file: sources/src.yaml\n    replicas: 1\n"), 0o644)

	_, err := binding.OpenProjectFile(projectFile)
	if err == nil {
		t.Fatal("inspect 400 时 OpenProjectFile 必须返回错误")
	}
	if !strings.Contains(err.Error(), "服务校验失败") {
		t.Fatalf("错误必须包含服务校验失败，实际: %v", err)
	}

	mu.Lock()
	callCopy := append([]string(nil), calls...)
	mu.Unlock()

	if len(callCopy) != 1 {
		t.Fatalf("期望只有 inspect 被调用，实际 %v", callCopy)
	}
}
