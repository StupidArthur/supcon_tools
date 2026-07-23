package bindings

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"config-tool/internal/realtime"
)

type RealtimeRuntimeBinding struct {
	ctx            context.Context
	manager        *realtime.Manager
	system         *SystemBinding
	sessionManager *realtime.SessionManager

	mu      sync.Mutex
	current *realtime.RealtimeRunSession
	curDir  string
}

func NewRealtimeRuntimeBinding(
	manager *realtime.Manager,
	system *SystemBinding,
	sessionManager *realtime.SessionManager,
) *RealtimeRuntimeBinding {
	return &RealtimeRuntimeBinding{
		manager:        manager,
		system:         system,
		sessionManager: sessionManager,
	}
}

func (b *RealtimeRuntimeBinding) SetContext(ctx context.Context) {
	b.ctx = ctx
	b.sessionManager.CleanupOrphans("")
}

func (b *RealtimeRuntimeBinding) Cleanup() {
	b.mu.Lock()
	dir := b.curDir
	b.mu.Unlock()
	if b.system.Status().Running {
		_ = b.system.Stop()
	}
	b.sessionManager.RemoveSessionDir(dir)
	b.mu.Lock()
	b.current = nil
	b.curDir = ""
	b.mu.Unlock()
}

func (b *RealtimeRuntimeBinding) GetProjectRevision(projectID string) (string, error) {
	return b.manager.RuntimeRevision(projectID)
}

func (b *RealtimeRuntimeBinding) GetSession() (*realtime.RealtimeRunSession, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.current == nil {
		return nil, nil
	}
	cp := *b.current
	return &cp, nil
}

func (b *RealtimeRuntimeBinding) StartProject(projectID string, options realtime.RealtimeStartOptions) (realtime.RealtimeRunSession, error) {
	opts := options.WithDefaults()

	status := b.system.Status()
	if status.Running {
		return realtime.RealtimeRunSession{}, fmt.Errorf("已有实时进程在运行")
	}
	if status.BatchRunning || status.ActiveBatches > 0 {
		return realtime.RealtimeRunSession{}, fmt.Errorf("批量任务正在运行，无法启动实时工程")
	}

	revision, err := b.manager.RuntimeRevision(projectID)
	if err != nil {
		return realtime.RealtimeRunSession{}, err
	}
	project, err := b.manager.OpenProject(context.Background(), projectID)
	if err != nil {
		return realtime.RealtimeRunSession{}, err
	}

	sessionID, dir, err := b.sessionManager.CreateSessionDir()
	if err != nil {
		return realtime.RealtimeRunSession{}, err
	}
	compiledPath := b.sessionManager.CompiledPath(dir)

	if _, err := b.manager.CompileProject(context.Background(), projectID, compiledPath); err != nil {
		b.sessionManager.RemoveSessionDir(dir)
		return realtime.RealtimeRunSession{}, fmt.Errorf("编译工程失败: %w", err)
	}

	return b.launch(sessionID, dir, compiledPath, realtime.RealtimeRunSession{
		SessionID:          sessionID,
		SourceKind:         realtime.RuntimeSourceProject,
		ProjectID:          project.ID,
		ProjectName:        project.Name,
		RuntimeRevision:    revision,
		CompiledConfigPath: compiledPath,
		RuntimeName:        opts.RuntimeName,
		CycleTime:          opts.CycleTime,
		OPCUAPort:          opts.OPCUAPort,
		APIHost:            opts.APIHost,
		APIPort:            opts.APIPort,
		State:              realtime.StateStarting,
	}, opts)
}

func (b *RealtimeRuntimeBinding) StartSingleYAML(configPath string, options realtime.RealtimeStartOptions) (realtime.RealtimeRunSession, error) {
	opts := options.WithDefaults()

	status := b.system.Status()
	if status.Running {
		return realtime.RealtimeRunSession{}, fmt.Errorf("已有实时进程在运行")
	}
	if status.BatchRunning || status.ActiveBatches > 0 {
		return realtime.RealtimeRunSession{}, fmt.Errorf("批量任务正在运行，无法启动实时仿真")
	}

	sessionID, dir, err := b.sessionManager.CreateSessionDir()
	if err != nil {
		return realtime.RealtimeRunSession{}, err
	}

	return b.launch(sessionID, dir, configPath, realtime.RealtimeRunSession{
		SessionID:          sessionID,
		SourceKind:         realtime.RuntimeSourceSingleYAML,
		SourcePath:         configPath,
		RuntimeRevision:    "",
		CompiledConfigPath: configPath,
		RuntimeName:        opts.RuntimeName,
		CycleTime:          opts.CycleTime,
		OPCUAPort:          opts.OPCUAPort,
		APIHost:            opts.APIHost,
		APIPort:            opts.APIPort,
		State:              realtime.StateStarting,
	}, opts)
}

func (b *RealtimeRuntimeBinding) launch(
	sessionID, dir, configPath string,
	session realtime.RealtimeRunSession,
	opts realtime.RealtimeStartOptions,
) (realtime.RealtimeRunSession, error) {
	err := b.system.Start(StartParams{
		ConfigPath:  configPath,
		Mode:        "REALTIME",
		CycleTime:   opts.CycleTime,
		Port:        opts.OPCUAPort,
		APIPort:     opts.APIPort,
		APIHost:     opts.APIHost,
		RuntimeName: opts.RuntimeName,
		EnableOpcUa: true,
	})
	if err != nil {
		b.sessionManager.RemoveSessionDir(dir)
		return realtime.RealtimeRunSession{}, err
	}

	st := b.system.Status()
	session.ConfigHash = st.ConfigHash
	session.StartedAt = st.StartedAt
	session.State = realtime.StateRunning

	_ = b.sessionManager.WriteSessionJSON(dir, sessionRecordFor(session))

	if session.SourceKind == realtime.RuntimeSourceProject {
		b.pushAlarmConfig(session)
	}

	if opts.ArchiveEnabled {
		b.startArchive(session, opts.ArchiveTags)
	}

	b.mu.Lock()
	b.current = &session
	b.curDir = dir
	b.mu.Unlock()

	return session, nil
}

func (b *RealtimeRuntimeBinding) startArchive(session realtime.RealtimeRunSession, tags []string) {
	payload := map[string]any{
		"sessionId": session.SessionID,
		"tags":      tags,
		"metadata": map[string]any{
			"projectId":       session.ProjectID,
			"projectName":     session.ProjectName,
			"runtimeRevision": session.RuntimeRevision,
			"configHash":      session.ConfigHash,
			"sourceKind":      string(session.SourceKind),
		},
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return
	}
	url := fmt.Sprintf("http://%s:%d/api/archive/start", session.APIHost, session.APIPort)
	resp, err := forceHTTPClient.Post(url, "application/json", bytes.NewReader(data))
	if err != nil {
		return
	}
	defer resp.Body.Close()
}

func (b *RealtimeRuntimeBinding) pushAlarmConfig(session realtime.RealtimeRunSession) {
	rules, err := b.manager.ListAlarmRules(context.Background(), session.ProjectID)
	if err != nil || len(rules) == 0 {
		return
	}
	payload := struct {
		Rules []realtime.AlarmRule `json:"rules"`
	}{Rules: rules}
	data, err := json.Marshal(payload)
	if err != nil {
		return
	}
	url := fmt.Sprintf("http://%s:%d/api/alarms/config", session.APIHost, session.APIPort)
	resp, err := forceHTTPClient.Post(url, "application/json", bytes.NewReader(data))
	if err != nil {
		return
	}
	defer resp.Body.Close()
}

func (b *RealtimeRuntimeBinding) apiBase() (string, error) {
	b.mu.Lock()
	s := b.current
	b.mu.Unlock()
	if s == nil {
		return "", fmt.Errorf("没有运行会话")
	}
	return fmt.Sprintf("http://%s:%d", s.APIHost, s.APIPort), nil
}

func (b *RealtimeRuntimeBinding) GetAlarms() (map[string]any, error) {
	base, err := b.apiBase()
	if err != nil {
		return nil, err
	}
	return httpGetJSON(forceHTTPClient, base+"/api/alarms")
}

func (b *RealtimeRuntimeBinding) GetAlarmEvents(limit int) (map[string]any, error) {
	base, err := b.apiBase()
	if err != nil {
		return nil, err
	}
	url := base + "/api/alarm-events"
	if limit > 0 {
		url += fmt.Sprintf("?limit=%d", limit)
	}
	return httpGetJSON(forceHTTPClient, url)
}

func (b *RealtimeRuntimeBinding) AckAlarm(alarmID string) error {
	base, err := b.apiBase()
	if err != nil {
		return err
	}
	resp, err := forceHTTPClient.Post(base+"/api/alarms/"+alarmID+"/ack", "application/json", bytes.NewReader([]byte("{}")))
	if err != nil {
		return err
	}
	return decodeForceResponse(resp, nil)
}

func (b *RealtimeRuntimeBinding) AckAllAlarms() error {
	base, err := b.apiBase()
	if err != nil {
		return err
	}
	resp, err := forceHTTPClient.Post(base+"/api/alarms/ack-all", "application/json", bytes.NewReader([]byte("{}")))
	if err != nil {
		return err
	}
	return decodeForceResponse(resp, nil)
}

func resolveHistoryDir() (string, error) {
	cacheDir, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(cacheDir, "DataFactory", "run_history"), nil
}

func (b *RealtimeRuntimeBinding) ListRunHistory() ([]map[string]any, error) {
	dir, err := resolveHistoryDir()
	if err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return []map[string]any{}, nil
	}
	var runs []map[string]any
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		metaPath := filepath.Join(dir, e.Name(), "metadata.json")
		data, err := os.ReadFile(metaPath)
		if err != nil {
			continue
		}
		var meta map[string]any
		if json.Unmarshal(data, &meta) != nil {
			continue
		}
		runs = append(runs, meta)
	}
	if runs == nil {
		runs = []map[string]any{}
	}
	return runs, nil
}

func (b *RealtimeRuntimeBinding) DeleteRunHistory(sessionID string) error {
	if strings.Contains(sessionID, "..") || strings.ContainsAny(sessionID, "/\\") {
		return fmt.Errorf("非法会话 ID")
	}
	dir, err := resolveHistoryDir()
	if err != nil {
		return err
	}
	target := filepath.Join(dir, sessionID)
	if _, err := os.Stat(target); err != nil {
		return fmt.Errorf("历史运行不存在")
	}
	return os.RemoveAll(target)
}

func (b *RealtimeRuntimeBinding) Stop() error {
	b.mu.Lock()
	dir := b.curDir
	b.mu.Unlock()

	if b.system.Status().Running {
		if err := b.system.Stop(); err != nil {
			return err
		}
	}

	b.sessionManager.RemoveSessionDir(dir)
	b.mu.Lock()
	b.current = nil
	b.curDir = ""
	b.mu.Unlock()
	return nil
}

func sessionRecordFor(s realtime.RealtimeRunSession) realtime.SessionRecord {
	return realtime.SessionRecord{
		SessionID:          s.SessionID,
		OwnerPid:           os.Getpid(),
		SourceKind:         string(s.SourceKind),
		ProjectID:          s.ProjectID,
		RuntimeRevision:    s.RuntimeRevision,
		CompiledConfigPath: s.CompiledConfigPath,
		CreatedAt:          s.StartedAt,
		State:              s.State,
	}
}
