package bindings

import (
	"os"
	"path/filepath"
	"testing"

	"config-tool/internal/config"
)

func TestResolveDataFactoryLaunchFromStandaloneMain(t *testing.T) {
	root := t.TempDir()
	writeBuiltinTemplateFixture(t, root)
	entry := filepath.Join(root, standaloneEntry)
	if err := os.WriteFile(entry, []byte("# stub\n"), 0644); err != nil {
		t.Fatal(err)
	}

	t.Setenv("SUPCON_DATAFACTORY_PATH", "")
	t.Setenv("SUPCON_TOOL_REPO_ROOT", root)
	t.Setenv(envPythonPath, os.Args[0])

	launch, err := resolveDataFactoryLaunch()
	if err != nil {
		t.Fatalf("resolveDataFactoryLaunch: %v", err)
	}
	if launch.exe != os.Args[0] {
		t.Fatalf("exe=%q want %q", launch.exe, os.Args[0])
	}
	if len(launch.prefixArgs) != 1 || launch.prefixArgs[0] != entry {
		t.Fatalf("prefixArgs=%v", launch.prefixArgs)
	}
	if launch.workDir != root {
		t.Fatalf("workDir=%q want %q", launch.workDir, root)
	}
}

func TestOpenYAMLFileDefaultConfigDirUsesRepoRoot(t *testing.T) {
	root := t.TempDir()
	writeBuiltinTemplateFixture(t, root)
	t.Setenv("SUPCON_TOOL_REPO_ROOT", root)

	dir, err := config.ResolveConfigDir()
	if err != nil {
		t.Fatalf("ResolveConfigDir: %v", err)
	}
	want := filepath.Join(root, "config")
	if dir != want {
		t.Fatalf("config dir=%q want %q", dir, want)
	}
}

func writeBuiltinTemplateFixture(t *testing.T, root string) {
	t.Helper()
	path := filepath.Join(root, config.BuiltinTemplateRelativePath)
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("programs: []\n"), 0644); err != nil {
		t.Fatal(err)
	}
}
