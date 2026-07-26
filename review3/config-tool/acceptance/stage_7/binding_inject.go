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
// mock 服务支持 /api/health, /api/batch/run, /api/export/convert，
// batch 互斥（同时只允许一个 batch）。
func wireMockService(t *testing.T, b *bindings.SystemBinding) func() {
	t.Helper()
	var batchMu sync.Mutex
	var batchRunning bool

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
		batchRunning = true
		batchMu.Unlock()
		defer func() {
			batchMu.Lock()
			batchRunning = false
			batchMu.Unlock()
		}()

		// 模拟 batch 处理耗时，确保并发请求能触发互斥
		time.Sleep(50 * time.Millisecond)

		var req struct {
			ConfigPath string `json:"configPath"`
			Cycles     int    `json:"cycles"`
		}
		json.NewDecoder(r.Body).Decode(&req)
		if req.Cycles <= 0 {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]any{"detail": "cycles 必须大于 0"})
			return
		}
		// 返回简单结果
		baseName := strings.TrimSuffix(filepath.Base(req.ConfigPath), ".yaml")
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"ok":      true,
			"columns": []string{"_cycle", "value"},
			"rows": []map[string]any{
				{"_cycle": 0, "value": float64(req.Cycles)},
				{"_cycle": 1, "value": float64(req.Cycles) + 1},
			},
			"displayColumns": []string{"_cycle", "value"},
			"plotScales":     map[string]float64{},
			"cycles":         req.Cycles,
			"_marker":        baseName,
		})
	})

	mux.HandleFunc("/api/export/convert", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Columns   []string        `json:"columns"`
			Rows      []map[string]any `json:"rows"`
			ExportPath string         `json:"exportPath"`
			Format    string          `json:"format"`
		}
		json.NewDecoder(r.Body).Decode(&req)

		// 写入 CSV 文件（模拟服务端行为）
		if req.ExportPath != "" && len(req.Columns) > 0 {
			os.MkdirAll(filepath.Dir(req.ExportPath), 0o755)
			var sb strings.Builder
			sb.WriteString(strings.Join(req.Columns, ","))
			sb.WriteString("\n")
			for _, row := range req.Rows {
				var vals []string
				for _, col := range req.Columns {
					if v, ok := row[col]; ok {
						vals = append(vals, fmt.Sprintf("%v", v))
					} else {
						vals = append(vals, "")
					}
				}
				sb.WriteString(strings.Join(vals, ","))
				sb.WriteString("\n")
			}
			os.WriteFile(req.ExportPath, []byte(sb.String()), 0o644)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"ok":     true,
			"path":   req.ExportPath,
			"rows":   len(req.Rows),
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
