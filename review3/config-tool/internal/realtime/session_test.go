package realtime

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func setupProjectWithSource(t *testing.T, m *Manager, yamlContent string) (projectID, sourceID string) {
	t.Helper()
	ctx := context.Background()
	p, err := m.CreateProject(ctx, "proj")
	if err != nil {
		t.Fatal(err)
	}
	yamlPath := writeYAML(t, t.TempDir(), "tank.yaml", yamlContent)
	view, err := m.AddSource(ctx, p.ID, yamlPath)
	if err != nil {
		t.Fatal(err)
	}
	return p.ID, view.Project.Sources[0].ID
}

func TestRuntimeRevisionDeterministic(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	projectID, _ := setupProjectWithSource(t, m, tankYAML)

	r1, err := m.RuntimeRevision(projectID)
	if err != nil {
		t.Fatal(err)
	}
	r2, err := m.RuntimeRevision(projectID)
	if err != nil {
		t.Fatal(err)
	}
	if r1 != r2 {
		t.Fatalf("revision not deterministic: %s != %s", r1, r2)
	}
	if len(r1) != 12 {
		t.Fatalf("expected 12-char revision, got %d", len(r1))
	}
}

func TestRuntimeRevisionChangesWithReplicas(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	projectID, sourceID := setupProjectWithSource(t, m, tankYAML)

	before, _ := m.RuntimeRevision(projectID)
	if _, err := m.UpdateReplicas(context.Background(), projectID, sourceID, 3); err != nil {
		t.Fatal(err)
	}
	after, _ := m.RuntimeRevision(projectID)
	if before == after {
		t.Fatal("revision should change when replicas change")
	}
}

func TestRuntimeRevisionUnchangedByRename(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	projectID, _ := setupProjectWithSource(t, m, tankYAML)

	before, _ := m.RuntimeRevision(projectID)
	if _, err := m.RenameProject(context.Background(), projectID, "新名字"); err != nil {
		t.Fatal(err)
	}
	after, _ := m.RuntimeRevision(projectID)
	if before != after {
		t.Fatal("revision should NOT change on rename")
	}
}

func TestRuntimeRevisionChangesWithSourceContent(t *testing.T) {
	m := newTestManager(t, &fakeCompiler{result: validResult()})
	projectID, sourceID := setupProjectWithSource(t, m, tankYAML)

	before, _ := m.RuntimeRevision(projectID)
	// 直接改写已存储的 source 文件内容
	srcPath := m.storage.SourceAbsPath(projectID, sourceID)
	if err := os.WriteFile(srcPath, []byte("clock:\n  cycle_time: 1.0\nprogram: []\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	after, _ := m.RuntimeRevision(projectID)
	if before == after {
		t.Fatal("revision should change when source content changes")
	}
}

func TestSessionDirUnique(t *testing.T) {
	sm := NewSessionManager(t.TempDir())
	id1, dir1, err := sm.CreateSessionDir()
	if err != nil {
		t.Fatal(err)
	}
	id2, dir2, err := sm.CreateSessionDir()
	if err != nil {
		t.Fatal(err)
	}
	if id1 == id2 || dir1 == dir2 {
		t.Fatal("session dirs must be unique")
	}
}

func TestCleanupOrphansKeepsActiveAndAlive(t *testing.T) {
	root := t.TempDir()
	sm := NewSessionManager(root)

	// active dir：当前会话，不应删除
	_, activeDir, _ := sm.CreateSessionDir()

	// owner 为当前进程（存活），不应删除
	_, aliveDir, _ := sm.CreateSessionDir()
	_ = sm.WriteSessionJSON(aliveDir, SessionRecord{OwnerPid: os.Getpid(), State: StateRunning})

	// owner 为死亡 pid，应删除
	_, deadDir, _ := sm.CreateSessionDir()
	_ = sm.WriteSessionJSON(deadDir, SessionRecord{OwnerPid: 99999999, State: StateRunning})

	// 无 session.json 的遗留目录，应删除
	strayDir := filepath.Join(root, "stray-dir")
	_ = os.MkdirAll(strayDir, 0o755)

	sm.CleanupOrphans(activeDir)

	if _, err := os.Stat(activeDir); err != nil {
		t.Fatal("active dir should be kept")
	}
	if _, err := os.Stat(aliveDir); err != nil {
		t.Fatal("alive owner dir should be kept")
	}
	if _, err := os.Stat(deadDir); !os.IsNotExist(err) {
		t.Fatal("dead owner dir should be removed")
	}
	if _, err := os.Stat(strayDir); !os.IsNotExist(err) {
		t.Fatal("stray dir should be removed")
	}
}

func TestSessionJSONRoundTrip(t *testing.T) {
	sm := NewSessionManager(t.TempDir())
	_, dir, _ := sm.CreateSessionDir()
	rec := SessionRecord{
		SessionID: "abc",
		OwnerPid:  os.Getpid(),
		State:     StateRunning,
		CreatedAt: nowISO(),
	}
	if err := sm.WriteSessionJSON(dir, rec); err != nil {
		t.Fatal(err)
	}
	got, ok := sm.readRecord(dir)
	if !ok {
		t.Fatal("read record failed")
	}
	if got.SessionID != "abc" || got.State != StateRunning {
		t.Fatalf("round trip mismatch: %+v", got)
	}
}
