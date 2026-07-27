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

func TestTailFile_ReturnsLastNLines(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "service-stderr.log")
	content := "line0\nline1\nline2\nline3\nline4\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	got := tailFile(path, 3)
	want := "line2\nline3\nline4"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestTailFile_EmptyAndMissing(t *testing.T) {
	if tailFile("Z:/non-existent-path/should-not-exist.log", 10) != "" {
		t.Fatal("expected empty string for missing file")
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "empty.log")
	if err := os.WriteFile(path, []byte(""), 0o644); err != nil {
		t.Fatal(err)
	}
	if tailFile(path, 5) != "" {
		t.Fatal("expected empty string for empty file")
	}
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

func TestConfigureBackgroundProcess_Compiles(t *testing.T) {
	_ = configureBackgroundProcess
}

// 保留 strings import，避免外部 import 路径误删
var _ = strings.Contains
