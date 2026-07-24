package bindings

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
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
	// 注册进程退出监听器：DataFactory 进程异常退出 / 主动 Stop / 启动期间退出
	// 都会被 monitorProcess 异步 dispatch 到这里；用于清理 realtime session 状态。
	b.system.AddExitListener(b.onSystemProcessExit)
	b.sessionManager.CleanupOrphans("")
}

// onSystemProcessExit 由 SystemBinding 在 monitorProcess 内同步调用。
// 无论进程是否正常停止，都必须：
//   - 清空 current / curDir
//   - 删除 session 临时目录
//   - 保留 system.lastError 供前端 GetSession 读取
//   - 幂等：多次调用安全
func (b *RealtimeRuntimeBinding) onSystemProcessExit(exitCode int, normalStop bool) {
	b.mu.Lock()
	s := b.current
	dir := b.curDir
	b.current = nil
	b.curDir = ""
	b.mu.Unlock()
	if s != nil {
		// 状态置为 exited / failed，由调用方按需读取
		s.State = realtime.StateExited
	}
	if dir != "" {
		b.sessionManager.RemoveSessionDir(dir)
	}
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

// RealtimeConnectionInfo 暴露给前端的当前运行期连接信息。
// 关键约束：
//   - APIToken 仅在内存中，不进入任何持久化记录（session.json / metadata.json / 日志）。
//   - 没有运行会话时调用方会得到空字符串 token，前端必须把它视为"未运行"。
//   - 进入此结构体的 token 与当前 run 的 process 一一对应；进程退出 / 异常停止会被清空。
type RealtimeConnectionInfo struct {
	APIHost     string `json:"apiHost"`
	APIPort     int    `json:"apiPort"`
	RuntimeName string `json:"runtimeName"`
	APIToken    string `json:"apiToken"`
}

// GetConnectionInfo 返回当前实时运行的连接信息（host / port / runtimeName / token）。
// 必须在 session 活跃时调用才返回有效 token；进程启动失败 / 退出 / 停止后 token 为空，
// 前端不得用空 token 继续访问 REST / WS。
func (b *RealtimeRuntimeBinding) GetConnectionInfo() (RealtimeConnectionInfo, error) {
	b.mu.Lock()
	s := b.current
	b.mu.Unlock()
	if s == nil {
		return RealtimeConnectionInfo{}, fmt.Errorf("没有运行会话")
	}
	if !b.system.Status().Running {
		return RealtimeConnectionInfo{}, fmt.Errorf("实时进程未在运行")
	}
	return RealtimeConnectionInfo{
		APIHost:     s.APIHost,
		APIPort:     s.APIPort,
		RuntimeName: s.RuntimeName,
		APIToken:    CurrentAPIToken(),
	}, nil
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
	// 阶段 C：启动事务化。
	// 顺序：
	//   1) 编译（已有；失败由上层处理）
	//   2) 启动 DataFactory + readiness
	//   3) 推送报警配置（若 SourceKind == project 且规则非空）
	//   4) 启动归档（若 opts.ArchiveEnabled）
	//   5) 写 session.json
	//   6) 设置 current / curDir
	// 任一步失败都必须回滚：停止 Python、关闭归档、清除 token、删除 session 目录。
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
	// 启动成功以后的所有失败都必须自己回滚，因为 system 已 Running。
	rollback := func(reason error) (realtime.RealtimeRunSession, error) {
		// 优先停归档（确保 SQLite / jsonl flush），再关 Engine。
		_ = b.stopArchiveOnShutdown()
		_ = b.system.Stop()
		b.sessionManager.RemoveSessionDir(dir)
		b.mu.Lock()
		b.current = nil
		b.curDir = ""
		b.mu.Unlock()
		return realtime.RealtimeRunSession{}, reason
	}

	st := b.system.Status()
	session.ConfigHash = st.ConfigHash
	session.StartedAt = st.StartedAt
	session.State = realtime.StateRunning
	// 关键：写入真实子进程 PID，供孤儿清理 / 进程验证使用。
	childPID := st.PID

	rec := sessionRecordFor(session)
	rec.ChildPid = childPID

	// 报警配置推送（C3）：规则非空时推送失败必须使启动失败。
	if session.SourceKind == realtime.RuntimeSourceProject {
		if err := b.pushAlarmConfig(session); err != nil {
			return rollback(fmt.Errorf("报警配置推送失败: %w", err))
		}
	}

	// 归档启动（C4）：用户明确启用后失败必须使启动失败。
	if opts.ArchiveEnabled {
		if err := b.startArchive(session, opts.ArchiveTags); err != nil {
			return rollback(fmt.Errorf("运行归档启动失败: %w", err))
		}
	}

	// 写 session.json：失败同样回滚。
	if err := b.sessionManager.WriteSessionJSON(dir, rec); err != nil {
		return rollback(fmt.Errorf("写入 session.json 失败: %w", err))
	}

	b.mu.Lock()
	b.current = &session
	b.curDir = dir
	b.mu.Unlock()

	return session, nil
}

// startArchive 启动运行归档。返回 error 让 launch 决定是否回滚。
// HTTP 错误 / 非 2xx 状态 / 解析错误都视为失败。
func (b *RealtimeRuntimeBinding) startArchive(session realtime.RealtimeRunSession, tags []string) error {
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
		return fmt.Errorf("序列化归档 metadata 失败: %w", err)
	}
	url := fmt.Sprintf("http://%s:%d/api/archive/start", session.APIHost, session.APIPort)
	resp, err := httpPostJSON(forceHTTPClient, url, data)
	if err != nil {
		return fmt.Errorf("POST /api/archive/start 网络错误: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("/api/archive/start HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return nil
}

// stopArchiveOnShutdown 主动调用 /api/archive/stop，确保 SQLite commit / jsonl flush / 句柄关闭。
// 错误仅记录，不影响关闭流程。
func (b *RealtimeRuntimeBinding) stopArchiveOnShutdown() error {
	b.mu.Lock()
	s := b.current
	b.mu.Unlock()
	if s == nil {
		return nil
	}
	url := fmt.Sprintf("http://%s:%d/api/archive/stop", s.APIHost, s.APIPort)
	resp, err := forceHTTPClient.Post(url, "application/json", strings.NewReader("{}"))
	if err != nil {
		return fmt.Errorf("POST /api/archive/stop 网络错误: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("/api/archive/stop HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return nil
}

// pushAlarmConfig 推送报警配置到运行中的 Engine。
// 规则为空视为合法 no-op，不报错；规则非空时推送失败返回 error。
func (b *RealtimeRuntimeBinding) pushAlarmConfig(session realtime.RealtimeRunSession) error {
	rules, err := b.manager.ListAlarmRules(context.Background(), session.ProjectID)
	if err != nil {
		return fmt.Errorf("加载报警规则失败: %w", err)
	}
	if len(rules) == 0 {
		return nil
	}
	payload := struct {
		Rules []realtime.AlarmRule `json:"rules"`
	}{Rules: rules}
	data, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("序列化报警规则失败: %w", err)
	}
	url := fmt.Sprintf("http://%s:%d/api/alarms/config", session.APIHost, session.APIPort)
	resp, err := httpPostJSON(forceHTTPClient, url, data)
	if err != nil {
		return fmt.Errorf("POST /api/alarms/config 网络错误: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("/api/alarms/config HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return nil
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
	resp, err := httpPostJSON(forceHTTPClient, base+"/api/alarms/"+alarmID+"/ack", []byte("{}"))
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
	resp, err := httpPostJSON(forceHTTPClient, base+"/api/alarms/ack-all", []byte("{}"))
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

	// 阶段 C4：归档必须在 Python 关闭前停止，确保 SQLite commit / jsonl flush / 句柄关闭。
	// 错误仅记录，不影响事件循环与 system.Stop。
	if err := b.stopArchiveOnShutdown(); err != nil {
		// 归档停止失败不应阻止用户主动停止。
		// (record into binding state for debugging if needed)
	}

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

// SetChildPid 写入真实子进程 PID（启动后由 launch 调用）。
// 该函数保留可供外部测试 / 未来其他场景使用。
func (b *RealtimeRuntimeBinding) SetChildPid(dir string, pid int) error {
	if dir == "" {
		return fmt.Errorf("session dir required")
	}
	if pid <= 0 {
		return fmt.Errorf("invalid pid: %d", pid)
	}
	rec, ok := b.sessionManager.ReadSessionRecord(dir)
	if !ok {
		return fmt.Errorf("session.json missing: %s", dir)
	}
	rec.ChildPid = pid
	return b.sessionManager.WriteSessionJSON(dir, rec)
}
