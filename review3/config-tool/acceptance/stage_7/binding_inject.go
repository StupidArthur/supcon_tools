package stage7_acceptance_test

// Reviewer-owned helpers to inject fake DataFactory into SystemBinding without
// changing business APIs. Uses reflect/unsafe on unexported test seams that
// already exist for internal/bindings unit tests.

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
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
	ready := func(ctx context.Context, apiHost string, apiPort int) (bool, string, error) {
		return true, "acceptance_runtime", nil
	}
	setUnexported(t, b, "readinessChecker", ready)
	setUnexported(t, b, "readyPollInterval", 20*time.Millisecond)
	setUnexported(t, b, "readyTimeout", 2*time.Second)
	setUnexported(t, b, "stopTimeout", 2*time.Second)
}
