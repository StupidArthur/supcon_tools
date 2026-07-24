package realtime

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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

// TestCleanupOrphansChildPidAlive: 子进程 PID 仍 alive 时，目录必须保留（即使 owner 已死）。
// 修复前 processAlive(pid)==os.Getpid() 永远等于 os.Getpid()，子进程判断必定为 false。
// 修复后即使 owner 已死，child alive 仍保留。
func TestCleanupOrphansChildPidAlive(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("windows: sleep 子进程对此 case 不适用，直接跳过")
	}
	root := t.TempDir()
	sm := NewSessionManager(root)

	// 启动一个长跑子进程，模拟 DataFactory 子进程
	cmd := exec.Command("sleep", "30")
	if err := cmd.Start(); err != nil {
		t.Skipf("cannot start sleep: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()

	_, aliveChildDir, _ := sm.CreateSessionDir()
	// owner 死亡，但 child alive → 保留
	_ = sm.WriteSessionJSON(aliveChildDir, SessionRecord{
		OwnerPid: 99999999,
		ChildPid: cmd.Process.Pid,
		State:    StateRunning,
	})

	sm.CleanupOrphans("")
	if _, err := os.Stat(aliveChildDir); err != nil {
		t.Fatal("alive child PID should keep dir alive even when owner dead")
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

// processAlive 必须能区分：
//   - 当前进程（owner pid）→ alive
//   - 一个不存在的 pid → dead
//   - pid <= 0 → dead
//   - 启动后立即存在的子进程 → alive
func TestProcessAlive_CurrentProcess(t *testing.T) {
	if !processAlive(os.Getpid()) {
		t.Fatalf("current PID must be alive: %d", os.Getpid())
	}
}

func TestProcessAlive_NonExistent(t *testing.T) {
	if processAlive(99999999) {
		t.Fatal("non-existent PID must be dead")
	}
}

func TestProcessAlive_ZeroOrNegative(t *testing.T) {
	if processAlive(0) {
		t.Error("pid=0 must be dead")
	}
	if processAlive(-1) {
		t.Error("pid=-1 must be dead")
	}
}

func TestProcessAlive_FreshChild(t *testing.T) {
	// 启动一个 sleep 子进程，processAlive 应当为 true。
	if runtime.GOOS == "windows" {
		t.Skip("windows 子进程用不同方式获取 pid，跳过 sleep 验证")
	}
	cmd := exec.Command("sleep", "30")
	if err := cmd.Start(); err != nil {
		t.Skipf("cannot start sleep: %v", err)
	}
	defer func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	}()
	if !processAlive(cmd.Process.Pid) {
		t.Errorf("fresh child PID %d should be alive", cmd.Process.Pid)
	}
}

// 阶段 H 收口：CleanupOrphans 不得删除 stop-failed / recovery-required 记录。
func TestCleanupOrphans_PreservesRecoveryRequiredRecord(t *testing.T) {
	tmp := t.TempDir()
	sm := NewSessionManager(tmp)

	// 创建一个 recovery-required 状态的 session（owner/child 都死亡）
	sessionID, dir, err := sm.CreateSessionDir()
	if err != nil {
		t.Fatal(err)
	}
	rec := SessionRecord{
		SessionID: sessionID,
		OwnerPid:  999999, // 不存在的 pid
		ChildPid:  999998,
		State:     StateRecoveryRequired,
	}
	if err := sm.WriteSessionJSON(dir, rec); err != nil {
		t.Fatal(err)
	}

	// CleanupOrphans 不得删除 recovery-required 记录
	sm.CleanupOrphans("")

	if _, err := os.Stat(dir); err != nil {
		t.Errorf("recovery-required session dir must be preserved: %v", err)
	}
}

// 阶段 H 收口：CleanupOrphans 不得删除 stop-failed 记录。
func TestCleanupOrphans_PreservesStopFailedRecord(t *testing.T) {
	tmp := t.TempDir()
	sm := NewSessionManager(tmp)

	sessionID, dir, err := sm.CreateSessionDir()
	if err != nil {
		t.Fatal(err)
	}
	rec := SessionRecord{
		SessionID: sessionID,
		OwnerPid:  999999,
		ChildPid:  999998,
		State:     StateStopFailed,
	}
	if err := sm.WriteSessionJSON(dir, rec); err != nil {
		t.Fatal(err)
	}

	sm.CleanupOrphans("")

	if _, err := os.Stat(dir); err != nil {
		t.Errorf("stop-failed session dir must be preserved: %v", err)
	}
}

// 阶段 H 收口：CleanupOrphans 正常清理普通死亡孤儿。
func TestCleanupOrphans_RemovesOrdinaryDeadSession(t *testing.T) {
	tmp := t.TempDir()
	sm := NewSessionManager(tmp)

	sessionID, dir, err := sm.CreateSessionDir()
	if err != nil {
		t.Fatal(err)
	}
	rec := SessionRecord{
		SessionID: sessionID,
		OwnerPid:  999999,
		ChildPid:  999998,
		State:     StateRunning, // 普通状态
	}
	if err := sm.WriteSessionJSON(dir, rec); err != nil {
		t.Fatal(err)
	}

	sm.CleanupOrphans("")

	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Errorf("ordinary dead session dir must be removed, got: %v", err)
	}
}
