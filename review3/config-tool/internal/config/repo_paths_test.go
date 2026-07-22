package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolveRepoRootFromEnv(t *testing.T) {
	root := t.TempDir()
	writeBuiltinTemplateFixture(t, root)
	t.Setenv("SUPCON_TOOL_REPO_ROOT", root)

	got, err := ResolveRepoRoot()
	if err != nil {
		t.Fatalf("ResolveRepoRoot: %v", err)
	}
	if got != root {
		t.Fatalf("root=%q want %q", got, root)
	}
}

func TestResolveConfigDirFromEnv(t *testing.T) {
	root := t.TempDir()
	writeBuiltinTemplateFixture(t, root)
	t.Setenv("SUPCON_TOOL_REPO_ROOT", root)

	got, err := ResolveConfigDir()
	if err != nil {
		t.Fatalf("ResolveConfigDir: %v", err)
	}
	want := filepath.Join(root, "config")
	if got != want {
		t.Fatalf("config dir=%q want %q", got, want)
	}
}

func writeBuiltinTemplateFixture(t *testing.T, root string) {
	t.Helper()
	path := filepath.Join(root, BuiltinTemplateRelativePath)
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("programs: []\n"), 0644); err != nil {
		t.Fatal(err)
	}
}
