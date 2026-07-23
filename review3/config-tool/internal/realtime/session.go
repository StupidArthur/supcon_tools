package realtime

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/google/uuid"
)

type RuntimeSourceKind string

const (
	RuntimeSourceProject    RuntimeSourceKind = "project"
	RuntimeSourceSingleYAML RuntimeSourceKind = "single-yaml"
)

const (
	StatePreparing = "preparing"
	StateStarting  = "starting"
	StateRunning   = "running"
	StateStopping  = "stopping"
	StateFailed    = "failed"
	StateExited    = "exited"
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

func (sm *SessionManager) RemoveSessionDir(dir string) {
	if dir == "" {
		return
	}
	_ = os.RemoveAll(dir)
}

// CleanupOrphans removes leftover session dirs whose owner/child process is not
// alive, skipping activeDir.
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

func processAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	// Single-instance semantics: the current app process is always alive; any
	// other owner pid is treated as a leftover from a previous run. Concurrent
	// instances are not supported (single DataFactory process constraint).
	return pid == os.Getpid()
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
