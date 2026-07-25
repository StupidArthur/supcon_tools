package bindings

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPickFreePort(t *testing.T) {
	for i := 0; i < 5; i++ {
		port, err := pickFreePort("127.0.0.1")
		if err != nil {
			t.Fatalf("attempt %d: %v", i, err)
		}
		if port <= 0 || port > 65535 {
			t.Fatalf("attempt %d: invalid port %d", i, port)
		}
	}
}

func TestLineBuffer_CapacityAndOrder(t *testing.T) {
	buf := newLineBuffer(3)
	for i := 0; i < 5; i++ {
		buf.Append("line" + string(rune('0'+i)))
	}
	got := buf.String()
	for _, want := range []string{"line2", "line3", "line4"} {
		if !strings.Contains(got, want) {
			t.Errorf("expected %q in buffer, got %q", want, got)
		}
	}
	for _, unwanted := range []string{"line0", "line1"} {
		if strings.Contains(got, unwanted) {
			t.Errorf("did not expect %q in buffer, got %q", unwanted, got)
		}
	}
}

func TestContainsOK(t *testing.T) {
	tests := []struct {
		name string
		body string
		want bool
	}{
		{"json-with-space", `{"ok": true, "x": 1}`, true},
		{"json-no-space", `{"ok":true,"x":1}`, true},
		{"negative", `{"ok": false}`, false},
		{"missing", `{"result": "yes"}`, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := containsOK([]byte(tt.body)); got != tt.want {
				t.Fatalf("containsOK(%q) = %v, want %v", tt.body, got, tt.want)
			}
		})
	}
}

func TestHideWindow_Compiles(t *testing.T) {
	// 在所有平台上验证函数存在；行为在 Windows 上才有意义
	_ = hideWindow // 编译时验证存在
}

func TestResolveRepoRootForDevService_FromTempDir(t *testing.T) {
	dir := t.TempDir()
	stub := filepath.Join(dir, "standalone_main.py")
	if err := os.WriteFile(stub, []byte("# stub for test\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := resolveRepoRootForDevService(dir)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != dir {
		t.Fatalf("expected %s, got %s", dir, got)
	}
}

func TestResolveRepoRootForDevService_NotFound(t *testing.T) {
	dir := t.TempDir()
	if _, err := resolveRepoRootForDevService(dir); err == nil {
		t.Fatal("expected error when standalone_main.py is missing")
	}
}