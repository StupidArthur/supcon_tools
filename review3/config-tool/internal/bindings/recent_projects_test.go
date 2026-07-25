package bindings

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func setupRecentProjectsTestEnv(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	exeDirOverrideForTest = dir
	exeDirOnce = sync.Once{}
	recentMu.Lock()
	recentCache = nil
	recentLoaded = false
	recentMu.Unlock()
	return dir
}

func TestRecentProjects_AddAndList(t *testing.T) {
	dir := setupRecentProjectsTestEnv(t)
	exeDir := dir
	_ = exeDir
	projectFile := filepath.Join(dir, "a", "project.yaml")
	if err := os.MkdirAll(filepath.Dir(projectFile), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(projectFile, []byte("version: 1\nid: a\nname: A\nsources: []\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	b := &RealtimeProjectBinding{}
	if err := b.AddRecentProject(projectFile); err != nil {
		t.Fatal(err)
	}
	entries, err := b.ListRecentProjects()
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(entries))
	}
	if entries[0].ProjectFile != projectFile {
		t.Fatalf("expected %s, got %s", projectFile, entries[0].ProjectFile)
	}
	if entries[0].LastOpened == "" {
		t.Fatal("expected non-empty LastOpened")
	}
}

func TestRecentProjects_AddDuplicatePromotesToFront(t *testing.T) {
	dir := setupRecentProjectsTestEnv(t)
	p1 := filepath.Join(dir, "first", "project.yaml")
	p2 := filepath.Join(dir, "second", "project.yaml")
	for _, p := range []string{p1, p2} {
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	b := &RealtimeProjectBinding{}
	if err := b.AddRecentProject(p1); err != nil {
		t.Fatal(err)
	}
	if err := b.AddRecentProject(p2); err != nil {
		t.Fatal(err)
	}
	if err := b.AddRecentProject(p1); err != nil {
		t.Fatal(err)
	}
	entries, _ := b.ListRecentProjects()
	if len(entries) != 2 {
		t.Fatalf("expected 2 entries (no duplicates), got %d", len(entries))
	}
	if !strings.EqualFold(entries[0].ProjectFile, p1) {
		t.Fatalf("expected first entry to be p1 after promotion, got %s", entries[0].ProjectFile)
	}
}

func TestRecentProjects_ListFiltersMissingFiles(t *testing.T) {
	dir := setupRecentProjectsTestEnv(t)
	p := filepath.Join(dir, "present", "project.yaml")
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	missing := filepath.Join(dir, "missing", "project.yaml")

	b := &RealtimeProjectBinding{}
	if err := b.AddRecentProject(p); err != nil {
		t.Fatal(err)
	}
	// 直接写 json 来注入已删除的项
	recentMu.Lock()
	recentCache = append(recentCache, RecentProjectEntry{ProjectFile: missing, LastOpened: "2024-01-01T00:00:00Z"})
	recentMu.Unlock()
	entries, _ := b.ListRecentProjects()
	for _, e := range entries {
		if e.ProjectFile == missing {
			t.Fatal("missing entry should have been filtered out")
		}
	}
}

func TestRecentProjects_Remove(t *testing.T) {
	dir := setupRecentProjectsTestEnv(t)
	p := filepath.Join(dir, "x", "project.yaml")
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	b := &RealtimeProjectBinding{}
	if err := b.AddRecentProject(p); err != nil {
		t.Fatal(err)
	}
	if err := b.RemoveRecentProject(p); err != nil {
		t.Fatal(err)
	}
	entries, _ := b.ListRecentProjects()
	for _, e := range entries {
		if e.ProjectFile == p {
			t.Fatal("entry should have been removed")
		}
	}
}