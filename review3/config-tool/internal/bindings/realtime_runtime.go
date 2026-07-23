package bindings

import (
	"context"
	"fmt"
	"os"
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

	b.mu.Lock()
	b.current = &session
	b.curDir = dir
	b.mu.Unlock()

	return session, nil
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
