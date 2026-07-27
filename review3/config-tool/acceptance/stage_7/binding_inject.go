package stage7_acceptance_test

// Reviewer-owned helpers to inject fake DataFactory into SystemBinding without
// changing business APIs. Uses reflect/unsafe on unexported test seams that
// already exist for internal/bindings unit tests.

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
	"reflect"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
	"unsafe"

	"config-tool/internal/bindings"
)

func projectRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve caller")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", ".."))
}

func fakeDataFactoryScript(t *testing.T) string {
	t.Helper()
	path := filepath.Join(
		projectRoot(t),
		"tools", "stage_verification", "acceptance", "stage_7", "helpers", "fake_datafactory.py",
	)
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("STAGE7 helper missing: %v", err)
	}
	return path
}

func pythonExecutable() string {
	if runtime.GOOS == "windows" {
		return "python"
	}
	return "python3"
}

func setUnexported(t *testing.T, target any, field string, value any) {
	t.Helper()
	v := reflect.ValueOf(target)
	if v.Kind() != reflect.Ptr {
		t.Fatalf("inject target must be pointer, got %s", v.Kind())
	}
	f := v.Elem().FieldByName(field)
	if !f.IsValid() {
		t.Fatalf("field %s not found on %T", field, target)
	}
	ptr := reflect.NewAt(f.Type(), unsafe.Pointer(f.UnsafeAddr())).Elem()
	val := reflect.ValueOf(value)
	if !val.Type().AssignableTo(f.Type()) {
		// Convert via Convert when underlying types match (named func types).
		if val.Type().ConvertibleTo(f.Type()) {
			val = val.Convert(f.Type())
		} else {
			t.Fatalf("cannot assign %s to field %s (%s)", val.Type(), field, f.Type())
		}
	}
	ptr.Set(val)
}

// wireFakeDataFactory points SystemBinding at the reviewer fake executable.
func wireFakeDataFactory(t *testing.T, b *bindings.SystemBinding, workDir string) {
	t.Helper()
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		t.Fatal(err)
	}
	sentinel := filepath.Join(workDir, "DataFactory.exe")
	if err := os.WriteFile(sentinel, []byte("fake"), 0o644); err != nil {
		t.Fatal(err)
	}
	script := fakeDataFactoryScript(t)
	py := pythonExecutable()
	setUnexported(t, b, "dataFactoryPath", sentinel)
	factory := func(name string, arg ...string) *exec.Cmd {
		args := append([]string{script}, arg...)
		cmd := exec.Command(py, args...)
		cmd.Dir = workDir
		cmd.Env = append([]string{}, os.Environ()...)
		return cmd
	}
	setUnexported(t, b, "commandFactory", factory)
	ready := func(ctx context.Context, apiHost string, apiPort int, token string) (bool, string, error) {
		return true, "acceptance_runtime", nil
	}
	setUnexported(t, b, "readinessChecker", ready)
	setUnexported(t, b, "readyPollInterval", 20*time.Millisecond)
	setUnexported(t, b, "readyTimeout", 2*time.Second)
	setUnexported(t, b, "stopTimeout", 2*time.Second)
}

// wireMockService 创建 mock DataFactoryService 并注入 SystemBinding。
// 返回 cleanup 函数。
// mock 服务支持新异步 batch API：/api/batch/run, /api/batch/runs/{id},
// /api/batch/runs/{id}/rows, /api/batch/runs/{id}/cancel, /api/export/convert。
func wireMockService(t *testing.T, b *bindings.SystemBinding) func() {
	t.Helper()
	var batchMu sync.Mutex
	var batchRunning bool
	var currentBatchId string

	mux := http.NewServeMux()

	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"ok":              true,
			"protocolVersion": 1,
			"serviceState":    "ready",
			"runtimeState":    "stopped",
		})
	})

	mux.HandleFunc("/api/batch/run", func(w http.ResponseWriter, r *http.Request) {
		batchMu.Lock()
		if batchRunning {
			batchMu.Unlock()
			w.WriteHeader(http.StatusConflict)
			json.NewEncoder(w).Encode(map[string]any{"detail": "已有批量任务正在运行"})
			return
		}
		var req struct {
			ConfigPath string `json:"configPath"`
			Cycles     int    `json:"cycles"`
		}
		json.NewDecoder(r.Body).Decode(&req)
		if req.Cycles <= 0 {
			batchMu.Unlock()
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]any{"detail": "cycles 必须大于 0"})
			return
		}
		batchRunning = true
		currentBatchId = fmt.Sprintf("mock-batch-%d", time.Now().UnixNano())
		batchMu.Unlock()

		// 模拟 batch 处理耗时，确保并发请求能触发互斥
		time.Sleep(50 * time.Millisecond)

		batchMu.Lock()
		batchRunning = false
		batchMu.Unlock()

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"ok":      true,
			"batchId": currentBatchId,
			"status":  "running",
		})
	})

	// 状态查询：mock 立即返回 completed
	mux.HandleFunc("/api/batch/runs/", func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Path
		// /api/batch/runs/{batchId}
		// /api/batch/runs/{batchId}/rows
		// /api/batch/runs/{batchId}/cancel
		parts := strings.Split(strings.TrimPrefix(path, "/api/batch/runs/"), "/")
		bid := parts[0]
		if bid == "" {
			w.WriteHeader(http.StatusNotFound)
			return
		}

		if r.Method == "GET" && len(parts) == 1 {
			// 状态查询
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{
				"ok":               true,
				"batchId":          bid,
				"status":           "completed",
				"cyclesRequested":  10,
				"cyclesCompleted":  10,
				"columns":          []string{"value"},
				"displayColumns":   []string{"value"},
				"plotScales":       map[string]float64{},
				"error":            nil,
			})
			return
		}

		if r.Method == "GET" && len(parts) == 2 && parts[1] == "rows" {
			// 预览行
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{
				"ok":      true,
				"batchId": bid,
				"rows": []map[string]any{
					{"_cycle": 0, "_sim_time": 0.0, "_need_sample": true, "value": 1.0},
					{"_cycle": 1, "_sim_time": 1.0, "_need_sample": true, "value": 2.0},
				},
				"offset": 0,
				"limit":  200,
				"total":  2,
			})
			return
		}

		if r.Method == "POST" && len(parts) == 2 && parts[1] == "cancel" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{"ok": true, "batchId": bid, "status": "cancelled"})
			return
		}

		if r.Method == "DELETE" && len(parts) == 1 {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{"ok": true, "batchId": bid})
			return
		}

		w.WriteHeader(http.StatusNotFound)
	})

	mux.HandleFunc("/api/export/convert", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			BatchId    string   `json:"batchId"`
			Columns    []string `json:"columns"`
			ExportPath string   `json:"exportPath"`
			Format     string   `json:"format"`
		}
		json.NewDecoder(r.Body).Decode(&req)

		// 写入简单文件（模拟服务端行为）
		if req.ExportPath != "" {
			os.MkdirAll(filepath.Dir(req.ExportPath), 0o755)
			cols := req.Columns
			if len(cols) == 0 {
				cols = []string{"value"}
			}
			var sb strings.Builder
			sb.WriteString(strings.Join(cols, ","))
			sb.WriteString("\n")
			sb.WriteString("1.0\n2.0\n")
			os.WriteFile(req.ExportPath, []byte(sb.String()), 0o644)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"ok":     true,
			"path":   req.ExportPath,
			"rows":   2,
			"format": req.Format,
		})
	})

	srv := httptest.NewServer(mux)
	port := srv.Listener.Addr().(*net.TCPAddr).Port
	client := bindings.NewDataFactoryServiceClient("127.0.0.1", port, "test-token")
	b.SetServiceClient(client)
	ctx := context.Background()
	setUnexported(t, b, "ctx", ctx)

	return func() { srv.Close() }
}
