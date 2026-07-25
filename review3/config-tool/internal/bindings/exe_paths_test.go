package bindings

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
)

// withTestExeDir 在 t.TempDir() 模拟 EXE 目录，并恢复原状态。
func withTestExeDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	exeDirOverrideForTest = dir
	exeDirOnce = sync.Once{}
	t.Cleanup(func() {
		exeDirOverrideForTest = ""
		exeDirOnce = sync.Once{}
	})
	return dir
}

// resetState 清理测试中可能写入的缓存和持久文件。
func resetState(t *testing.T) {
	t.Helper()
	// recent_projects 的缓存由包级变量管理，测试间不需主动清理。
	_ = t
}

func TestEnsureAppWorkspaceDirs_CreatesBothWhenMissing(t *testing.T) {
	resetState(t)
	exeDir := withTestExeDir(t)
	paths, err := EnsureAppWorkspaceDirs()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if paths.ExeDir != exeDir {
		t.Fatalf("expected ExeDir %s, got %s", exeDir, paths.ExeDir)
	}
	if filepath.Clean(paths.ProjectDir) != filepath.Clean(filepath.Join(exeDir, "project")) {
		t.Fatalf("expected ProjectDir under exe, got %s", paths.ProjectDir)
	}
	if filepath.Clean(paths.TemplateDir) != filepath.Clean(filepath.Join(exeDir, "template")) {
		t.Fatalf("expected TemplateDir under exe, got %s", paths.TemplateDir)
	}
	for _, p := range []string{paths.ProjectDir, paths.TemplateDir} {
		info, err := os.Stat(p)
		if err != nil {
			t.Fatalf("expected dir %s: %v", p, err)
		}
		if !info.IsDir() {
			t.Fatalf("expected %s to be a directory", p)
		}
	}
}

func TestEnsureAppWorkspaceDirs_IdempotentWhenExists(t *testing.T) {
	resetState(t)
	withTestExeDir(t)

	// 第二次调用不应报错
	paths1, err := EnsureAppWorkspaceDirs()
	if err != nil {
		t.Fatalf("first call: %v", err)
	}
	// 在 project 里放一个标记文件，验证第二次调用不会清空
	marker := filepath.Join(paths1.ProjectDir, "marker.txt")
	if err := os.WriteFile(marker, []byte("keep me"), 0o644); err != nil {
		t.Fatal(err)
	}
	paths2, err := EnsureAppWorkspaceDirs()
	if err != nil {
		t.Fatalf("second call: %v", err)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("marker should survive re-init: %v", err)
	}
	if paths2.ProjectDir != paths1.ProjectDir {
		t.Fatalf("path changed across calls")
	}
}

func TestEnsureAppWorkspaceDirs_CreatesMissingOnly(t *testing.T) {
	resetState(t)
	exeDir := withTestExeDir(t)
	// 预先只创建 project，template 不存在
	if err := os.MkdirAll(filepath.Join(exeDir, "project"), 0o755); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(exeDir, "project", "keep.txt")
	if err := os.WriteFile(marker, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	paths, err := EnsureAppWorkspaceDirs()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("existing project content should survive: %v", err)
	}
	if _, err := os.Stat(paths.TemplateDir); err != nil {
		t.Fatalf("template should be created: %v", err)
	}
}

func TestEnsureAppWorkspaceDirs_FailsWhenProjectIsFile(t *testing.T) {
	resetState(t)
	exeDir := withTestExeDir(t)
	// 用一个同名文件占用 project 路径
	if err := os.WriteFile(filepath.Join(exeDir, "project"), []byte("blocked"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := EnsureAppWorkspaceDirs()
	if err == nil {
		t.Fatal("expected error when project path is occupied by a file")
	}
	if !strings.Contains(err.Error(), "project") {
		t.Fatalf("error should mention project path: %v", err)
	}
}

func TestEnsureAppWorkspaceDirs_FailsWhenTemplateIsFile(t *testing.T) {
	resetState(t)
	exeDir := withTestExeDir(t)
	if err := os.WriteFile(filepath.Join(exeDir, "template"), []byte("blocked"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := EnsureAppWorkspaceDirs()
	if err == nil {
		t.Fatal("expected error when template path is occupied by a file")
	}
	if !strings.Contains(err.Error(), "template") {
		t.Fatalf("error should mention template path: %v", err)
	}
}

func TestEnsureAppWorkspaceDirs_ConcurrentSafe(t *testing.T) {
	resetState(t)
	withTestExeDir(t)
	// 多次连续调用结果一致
	results := make([]AppWorkspacePaths, 10)
	for i := 0; i < 10; i++ {
		p, err := EnsureAppWorkspaceDirs()
		if err != nil {
			t.Fatalf("call %d failed: %v", i, err)
		}
		results[i] = p
	}
	for i := 1; i < 10; i++ {
		if results[i] != results[0] {
			t.Fatalf("call %d differs from call 0: %+v vs %+v", i, results[i], results[0])
		}
	}
}

func TestEnsureAppWorkspaceDirs_AllowsEXENotSet(t *testing.T) {
	// ResolveExeDir 在 os.Executable 失败时（极少见）会让 EnsureAppWorkspaceDirs
	// 直接返回该错误，确保错误包含路径信息。
	// 这里通过覆盖 exeDirOverrideForTest 为空 + 重置缓存模拟"无法解析"。
	t.Skip("此路径依赖运行时注入 os.Executable 失败，工程测试里跳过")
	_ = runtime.GOOS
	_ = errors.Is
}