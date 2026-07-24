package realtime

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"syscall"
	"time"

	"github.com/google/uuid"
)

type RuntimeSourceKind string

const (
	RuntimeSourceProject    RuntimeSourceKind = "project"
	RuntimeSourceSingleYAML RuntimeSourceKind = "single-yaml"
)

const (
	StatePreparing        = "preparing"
	StateStarting         = "starting"
	StateRunning          = "running"
	StateStopping         = "stopping"
	StateFailed           = "failed"
	StateExited           = "exited"
	StateStopFailed       = "stop-failed"        // Stop 失败但进程仍在，需要重试
	StateRecoveryRequired = "recovery-required" // 异常状态，需要用户主动清理
)

type RealtimeRunSession struct {
	SessionID          string            `json:"sessionId"`
	SourceKind         RuntimeSourceKind `json:"sourceKind"`
	ProjectID          string            `json:"projectId,omitempty"`
	ProjectName        string            `json:"projectName,omitempty"`
	SourcePath         string            `json:"sourcePath,omitempty"`
	RuntimeRevision    string            `json:"runtimeRevision"`
	CompiledConfigPath string            `json:"compiledConfigPath"`
	ConfigHash         string            `json:"configHash"`
	RuntimeName        string            `json:"runtimeName"`
	CycleTime          float64           `json:"cycleTime"`
	OPCUAPort          int               `json:"opcUaPort"`
	APIHost            string            `json:"apiHost"`
	APIPort            int               `json:"apiPort"`
	StartedAt          string            `json:"startedAt"`
	State              string            `json:"state"`
}

type RealtimeStartOptions struct {
	CycleTime      float64  `json:"cycleTime"`
	OPCUAPort      int      `json:"opcUaPort"`
	APIHost        string   `json:"apiHost"`
	APIPort        int      `json:"apiPort"`
	RuntimeName    string   `json:"runtimeName"`
	ArchiveEnabled bool     `json:"archiveEnabled"`
	ArchiveTags    []string `json:"archiveTags"`
}

func (o RealtimeStartOptions) WithDefaults() RealtimeStartOptions {
	if o.CycleTime <= 0 {
		o.CycleTime = 0.5
	}
	if o.OPCUAPort <= 0 {
		o.OPCUAPort = 18951
	}
	if o.APIHost == "" {
		o.APIHost = "127.0.0.1"
	}
	if o.APIPort <= 0 {
		o.APIPort = 8000
	}
	if o.RuntimeName == "" {
		o.RuntimeName = "default"
	}
	return o
}

// RuntimeRevision computes the project runtime revision hash.
//
// Includes: project ID, source order, each source ID, replicas, each source
// file byte hash, and alarms.yaml when present (phase 7).
// Excludes: display name, dashboard, user preferences.
// Encoding is deterministic and does not depend on map order or file mtime.
func (m *Manager) RuntimeRevision(projectID string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.runtimeRevisionLocked(projectID)
}

func (m *Manager) runtimeRevisionLocked(projectID string) (string, error) {
	p, err := m.storage.LoadProject(projectID)
	if err != nil {
		return "", err
	}
	h := sha256.New()
	fmt.Fprintf(h, "project:%s\n", p.ID)
	for _, s := range p.Sources {
		fmt.Fprintf(h, "source:%s|replicas:%d\n", s.ID, s.Replicas)
		data, err := os.ReadFile(m.storage.SourceAbsPath(projectID, s.ID))
		if err != nil {
			return "", fmt.Errorf("read source file failed %s: %w", s.ID, err)
		}
		fh := sha256.Sum256(data)
		fmt.Fprintf(h, "filehash:%s\n", hex.EncodeToString(fh[:]))
	}
	if alarmsPath, ok := m.storage.AlarmsPath(projectID); ok {
		if data, err := os.ReadFile(alarmsPath); err == nil {
			ah := sha256.Sum256(data)
			fmt.Fprintf(h, "alarms:%s\n", hex.EncodeToString(ah[:]))
		}
	}
	return hex.EncodeToString(h.Sum(nil))[:12], nil
}

// SessionRecord is the persisted session.json content.
type SessionRecord struct {
	SessionID          string `json:"sessionId"`
	OwnerPid           int    `json:"ownerPid"`
	ChildPid           int    `json:"childPid"`
	SourceKind         string `json:"sourceKind"`
	ProjectID          string `json:"projectId,omitempty"`
	RuntimeRevision    string `json:"runtimeRevision"`
	CompiledConfigPath string `json:"compiledConfigPath"`
	CreatedAt          string `json:"createdAt"`
	State              string `json:"state"`
}

// SessionManager manages run session directory lifecycle.
type SessionManager struct {
	root string
}

func NewSessionManager(root string) *SessionManager {
	return &SessionManager{root: root}
}

func ResolveSessionRoot() (string, error) {
	cacheDir, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(cacheDir, "DataFactory", "realtime_runs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return dir, nil
}

func (sm *SessionManager) CreateSessionDir() (sessionID, dir string, err error) {
	sessionID = uuid.New().String()
	dir = filepath.Join(sm.root, sessionID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", "", err
	}
	return sessionID, dir, nil
}

func (sm *SessionManager) CompiledPath(dir string) string {
	return filepath.Join(dir, "compiled.yaml")
}

func (sm *SessionManager) WriteSessionJSON(dir string, rec SessionRecord) error {
	data, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	return atomicWrite(filepath.Join(dir, "session.json"), data)
}

// ReadSessionRecord 读取 session.json 内容；不存在或损坏返回 (zero, false)。
// 与 readRecord 等价但导出，供 bindings 写入 ChildPid / 状态字段使用。
func (sm *SessionManager) ReadSessionRecord(dir string) (SessionRecord, bool) {
	return sm.readRecord(dir)
}

func (sm *SessionManager) RemoveSessionDir(dir string) {
	if dir == "" {
		return
	}
	_ = os.RemoveAll(dir)
}

// CleanupOrphans removes leftover session dirs whose owner/child process is not
// alive, skipping activeDir.
// 阶段 H 收口：stop-failed / recovery-required 状态的记录不被自动清理，
// 保留为诊断证据。只有普通状态（running/preparing/starting 等）且 owner、child
// 都死亡的孤儿记录才能自动清理。
func (sm *SessionManager) CleanupOrphans(activeDir string) {
	entries, err := os.ReadDir(sm.root)
	if err != nil {
		return
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := filepath.Join(sm.root, e.Name())
		if dir == activeDir {
			continue
		}
		rec, ok := sm.readRecord(dir)
		if !ok {
			sm.RemoveSessionDir(dir)
			continue
		}
		// 保留失败/恢复记录作为诊断证据
		if rec.State == StateStopFailed || rec.State == StateRecoveryRequired {
			continue
		}
		if !processAlive(rec.OwnerPid) && !processAlive(rec.ChildPid) {
			sm.RemoveSessionDir(dir)
		}
	}
}

func (sm *SessionManager) readRecord(dir string) (SessionRecord, bool) {
	data, err := os.ReadFile(filepath.Join(dir, "session.json"))
	if err != nil {
		return SessionRecord{}, false
	}
	var rec SessionRecord
	if err := json.Unmarshal(data, &rec); err != nil {
		return SessionRecord{}, false
	}
	return rec, true
}

func atomicWrite(path string, data []byte) error {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, path)
}

// processAlive 判定 pid 是否仍是活动进程。
//   - pid <= 0 视为无效/false。
//   - Unix: 用 Signal 0（不实际发送信号，仅检查权限与存在）。
//   - Windows: OpenProcess + GetExitCodeProcess（仍 alive 时 exit code = STILL_ACTIVE = 259）。
//   - 单实例语义：当前 Wails 进程即 owner；DataFactory 子进程的 child pid 必须独立存活。
//
// 不再把非当前 PID 一律视为死亡——否则历史 session 永远被误删。
func processAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	if pid == os.Getpid() {
		return true
	}
	return platformProcessAlive(pid)
}

// platformProcessAlive 在 Unix/Windows 下分别实现 pid 存活检查。
// 任何底层错误（权限拒绝、句柄无效、查询失败）一律视为死亡，但不抛错。
func platformProcessAlive(pid int) bool {
	switch runtime.GOOS {
	case "windows":
		return windowsProcessAlive(pid)
	default:
		return unixProcessAlive(pid)
	}
}

func unixProcessAlive(pid int) bool {
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	if proc == nil {
		return false
	}
	// syscall.Signal(0) 仅做权限/存在检查，不真正发信号。
	if err := proc.Signal(syscall.Signal(0)); err != nil {
		// EPERM = 存在但权限不够（仍视为 alive）。
		if isPermissionError(err) {
			return true
		}
		return false
	}
	return true
}

// isPermissionError 简化判断：底层无 unix.Permitted 类型依赖，使用字符串匹配。
func isPermissionError(err error) bool {
	if err == nil {
		return false
	}
	s := err.Error()
	return strings.Contains(s, "permission") || strings.Contains(s, "EPERM")
}

// SortedSourceIDs returns a deterministically sorted copy of source IDs.
func SortedSourceIDs(ids []string) []string {
	out := append([]string(nil), ids...)
	sort.Strings(out)
	return out
}

func nowISO() string {
	return time.Now().Format(time.RFC3339)
}
