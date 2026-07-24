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

// SessionManagerCompat is the minimal SessionManager interface used by
// RealtimeRuntimeBinding. It exists so tests can swap in a wrapper that
// simulates write failures (e.g. session.json write fail after archive start).
type SessionManagerCompat interface {
	CreateSessionDir() (sessionID, dir string, err error)
	CompiledPath(dir string) string
	WriteSessionJSON(dir string, rec realtime.SessionRecord) error
	RemoveSessionDir(dir string)
	ReadSessionRecord(dir string) (realtime.SessionRecord, bool)
	CleanupOrphans(activeDir string)
}

type RealtimeRuntimeBinding struct {
	ctx            context.Context
	manager        *realtime.Manager
	system         *SystemBinding
	sessionManager SessionManagerCompat

	mu sync.Mutex
	// current / curDir 描述当前活跃 session。异常退出 / 主动 Stop / 启动失败
	// 都会把这两个清空，Session 状态由 monitorProcess 派发的 onSystemProcessExit
	// 统一处理。
	current       *realtime.RealtimeRunSession
	curDir        string
	archiveActive bool // 当前 session 是否已成功启动 /api/archive/start

	// 阶段 H 收口：orchestratedStop 标识 Stop() 事务正在执行。
	// 受 b.mu 保护。onSystemProcessExit 检测到此标志时不得争抢状态清理，
	// 由 Stop() 事务统一负责 archive stop / session dir / 内存状态。
	orchestratedStop bool

	// 阶段 B2 收口：exitListenerOnce 保证 SetContext 多次调用只注册一次监听器，
	// 避免 runtime 事件循环/页面重渲时累积空壳回调。
	exitListenerOnce sync.Once
	removeExitListener func()
}

func NewRealtimeRuntimeBinding(
	manager *realtime.Manager,
	system *SystemBinding,
	sessionManager SessionManagerCompat,
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
	// sync.Once 防止 SetContext 重复注册（容器 / Lifecycle 可能多次调用）。
	b.exitListenerOnce.Do(func() {
		b.removeExitListener = b.system.addExitListener(b.onSystemProcessExit)
	})
	b.sessionManager.CleanupOrphans("")
}

// onSystemProcessExit 由 SystemBinding 在 monitorProcess 内同步调用。
// 无论进程是否正常停止，都必须：
//   - 尝试关闭归档（如已启用；进程正在退出，最佳努力）
//   - 清空 current / curDir / archiveActive
//   - 删除 session 临时目录
//   - 保留 system.lastError 供前端 GetSession 读取
//   - 幂等：多次调用安全
//
// 阶段 H 收口：如果 Stop() 事务正在执行（orchestratedStop=true），
// 本回调不得争抢状态清理 —— 由 Stop() 统一负责 archive/session/内存。
func (b *RealtimeRuntimeBinding) onSystemProcessExit(exitCode int, normalStop bool) {
	b.mu.Lock()
	if b.orchestratedStop {
		// Stop() 事务正在执行，不干预。
		b.mu.Unlock()
		return
	}
	s := b.current
	dir := b.curDir
	archiveActive := b.archiveActive
	b.current = nil
	b.curDir = ""
	b.archiveActive = false
	b.mu.Unlock()

	if s != nil {
		s.State = realtime.StateExited
		if archiveActive {
			archiveErr := b.stopArchiveOnShutdown(*s)
			if archiveErr != nil {
				// archive flush 失败：保留 session dir 作为恢复记录
				if dir != "" {
					rec, _ := b.sessionManager.ReadSessionRecord(dir)
					rec.State = realtime.StateRecoveryRequired
					if writeErr := b.sessionManager.WriteSessionJSON(dir, rec); writeErr != nil {
						fmt.Fprintf(os.Stderr, "[realtime] onSystemProcessExit: write recovery record failed: %v\n", writeErr)
					}
				}
				fmt.Fprintf(os.Stderr, "[realtime] onSystemProcessExit: archive stop failed, recovery record preserved: %v\n", archiveErr)
				return // 不删除 session dir
			}
		}
	}
	if dir != "" {
		b.sessionManager.RemoveSessionDir(dir)
	}
}

func (b *RealtimeRuntimeBinding) Cleanup() {
	// 阶段 5-3 收口：Cleanup 走和 Stop 一致的内部事务。
	// 关键：若 system.Stop 失败且进程仍存活，必须保留 current / curDir / token
	// 让用户可以再次 Stop 重试。此时**不注销** exit listener（继续等 monitor
	// 检测进程真实退出后触发清理）。
	stopErr := b.Stop()

	// 检查进程是否仍存活；只有真正死了才注销 listener / 删 session 目录。
	// 直接访问 system.proc（bindings 内部，无需 *ForTest 暴露）。
	stillRunning := false
	if stopErr != nil {
		b.system.mu.Lock()
		proc := b.system.proc
		b.system.mu.Unlock()
		if proc != nil {
			stillRunning = b.system.processAliveForCleanup(proc)
		}
	}

	if !stillRunning {
		// 进程已停：注销 listener（避免 Wails 应用销毁后回调仍引用 binding）
		if b.removeExitListener != nil {
			b.removeExitListener()
			b.removeExitListener = nil
		}
		// 阶段 H 收口：Stop() 已处理 archive 失败时的 session dir 保留。
		// 此处仅记录错误日志（进程已死，内存状态已由 Stop() 清除）。
		if stopErr != nil {
			fmt.Fprintf(os.Stderr, "[realtime] Cleanup: stop/archive error (process dead): %v\n", stopErr)
		}
	} else {
		// 进程仍存活：保留 current / curDir / token / session dir 让用户重试。
		// 不删除 session dir —— 下次 Stop 需要读取 session.json 写入 stop-failed 状态。
		// listener 保留（继续等待 monitor 检测进程真实退出后触发清理）。
		if stopErr != nil {
			fmt.Fprintf(os.Stderr, "[realtime] Cleanup: stop failed, process still alive, session preserved for retry: %v\n", stopErr)
		}
	}
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

// recAsSession 把 session + rec 合并成 RealtimeRunSession（用于 rollback 写 stop-failed
// 状态时复用 launch 阶段的局部 session）。
func recAsSession(s *realtime.RealtimeRunSession, r realtime.SessionRecord) *realtime.RealtimeRunSession {
	cp := *s
	cp.State = r.State
	return &cp
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
	st := b.system.Status()
	session.ConfigHash = st.ConfigHash
	session.StartedAt = st.StartedAt
	session.State = realtime.StateRunning
	// 关键：写入真实子进程 PID，供孤儿清理 / 进程验证使用。
	childPID := st.PID

	rec := sessionRecordFor(session)
	rec.ChildPid = childPID

	// 阶段 C 收口 + 阶段 5-2：rollback 必须使用 local session + 局部 archiveActive，
	// 不能依赖 b.current（仅在所有初始化成功后才会被赋值）。
	// 关键：system.Stop() 失败时**不能**清空 session / curDir / token；
	// 必须保留状态供用户重试，否则会留下"系统仍 Running 但 realtime 已失管"的孤儿进程。
	archiveActive := false
	alarmConfigured := false
	rollback := func(reason error) (realtime.RealtimeRunSession, error) {
		// 优先级 1: 停归档（保证 SQLite / jsonl flush 与文件句柄关闭）。
		if archiveActive {
			if err := b.stopArchiveOnShutdown(session); err != nil {
				reason = fmt.Errorf("%w; 归档停止失败: %v", reason, err)
			}
		}
		// 优先级 2: 关闭 Python。
		stopErr := b.system.Stop()
		// 阶段 5-2：Stop 失败且进程仍 Running → 保留 session 状态。
		if stopErr != nil {
			// 进程仍可能存在（Stop 已发信号但子进程未退出）
			stillRunning := b.system.Status().Running
			if stillRunning {
				combined := fmt.Errorf("%w; 进程停止失败: %v（进程仍在，保留会话供重试）", reason, stopErr)
				// 把 session 写入绑定状态，让前端能看到"stop-failed"，可重试 Stop。
				rec.State = realtime.StateStopFailed
				_ = b.sessionManager.WriteSessionJSON(dir, rec)
				b.mu.Lock()
				// 关键：保留 current / curDir / archiveActive，不要清 token。
				// monitorProcess 后续若检测到进程真的退出，会派发 exit listener 收尾。
				preserved := recAsSession(&session, rec)
				b.current = preserved
				b.curDir = dir
				b.archiveActive = archiveActive
				b.mu.Unlock()
				return realtime.RealtimeRunSession{}, combined
			}
			// 进程已退出（Stop 返回错误但系统记录 Running=false）→ 走正常清理。
			reason = fmt.Errorf("%w; 进程停止失败（已退出）: %v", reason, stopErr)
		}
		// 优先级 3: 写完 session.json 的目录可以删除；其它中间产物（编译产物等）
		// 已经被 CreateSessionDir 创建的目录一并清理。
		b.sessionManager.RemoveSessionDir(dir)
		// 优先级 4: 清空 in-flight 状态。注意：b.current 此刻仍为 nil（未提交），
		// 但 monitorProcess 后续会派发 exit listener 来收尾。
		b.mu.Lock()
		b.current = nil
		b.curDir = ""
		b.archiveActive = false
		b.mu.Unlock()
		return realtime.RealtimeRunSession{}, reason
	}
	_ = alarmConfigured // 当前未用作条件分支，保留扩展点

	// 报警配置推送（C3）：规则非空时推送失败必须使启动失败。
	if session.SourceKind == realtime.RuntimeSourceProject {
		if err := b.pushAlarmConfig(session); err != nil {
			return rollback(fmt.Errorf("报警配置推送失败: %w", err))
		}
		alarmConfigured = true
	}

	// 归档启动（C4）：用户明确启用后失败必须使启动失败。
	if opts.ArchiveEnabled {
		if err := b.startArchive(session, opts.ArchiveTags); err != nil {
			return rollback(fmt.Errorf("运行归档启动失败: %w", err))
		}
		archiveActive = true
	}

	// 写 session.json：失败同样回滚。
	if err := b.sessionManager.WriteSessionJSON(dir, rec); err != nil {
		return rollback(fmt.Errorf("写入 session.json 失败: %w", err))
	}

	b.mu.Lock()
	b.current = &session
	b.curDir = dir
	b.archiveActive = archiveActive
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
// 阶段 C 收口：
//   - 接受 session 作为参数，不再依赖 b.current（rollback 时 b.current 尚未提交）
//   - 通过 httpPostJSON 自动加 Bearer 鉴权头
// 错误仅记录，不影响关闭流程（调用方自行决定是否合并到总体错误）。
func (b *RealtimeRuntimeBinding) stopArchiveOnShutdown(session realtime.RealtimeRunSession) error {
	if session.SessionID == "" {
		return nil
	}
	url := fmt.Sprintf("http://%s:%d/api/archive/stop", session.APIHost, session.APIPort)
	resp, err := httpPostJSON(forceHTTPClient, url, []byte("{}"))
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
	sess := b.current
	archiveActive := b.archiveActive
	// 阶段 H 收口：标记 Stop 事务开始，阻止 onSystemProcessExit 争抢清理。
	b.orchestratedStop = true
	b.mu.Unlock()

	// 事务结束后必须清除标志（无论成功/失败）。
	defer func() {
		b.mu.Lock()
		b.orchestratedStop = false
		b.mu.Unlock()
	}()

	// 阶段 C4 收口：归档停止优先（保证 SQLite / jsonl flush / 句柄关闭），
	// 仅在确实启用归档时调用。带 Bearer 鉴权。
	// archivePending 跟踪"归档是否仍需重试"：
	//   - archive stop 成功 → archivePending = false（不再重试）
	//   - archive stop 失败 → archivePending = true（下次 Stop 重试）
	// 关键：不得在 stop-failed 恢复路径中写回旧的 archiveActive 值，
	// 否则已成功的 archive stop 会被错误地标记为仍需重试。
	var archiveErr error
	archivePending := archiveActive
	if archiveActive && sess != nil {
		archiveErr = b.stopArchiveOnShutdown(*sess)
		archivePending = archiveErr != nil
		b.mu.Lock()
		b.archiveActive = archivePending
		b.mu.Unlock()
	}

	if b.system.Status().Running {
		if stopErr := b.system.Stop(); stopErr != nil {
			// 阶段 5-2：Stop 失败但进程仍在 → 保留会话供重试。
			if b.system.Status().Running {
				combined := stopErr
				if archiveErr != nil {
					combined = fmt.Errorf("%w; 归档停止失败: %v", stopErr, archiveErr)
				}
				if sess != nil {
					// 写 stop-failed 状态
					rec, _ := b.sessionManager.ReadSessionRecord(dir)
					rec.State = realtime.StateStopFailed
					if writeErr := b.sessionManager.WriteSessionJSON(dir, rec); writeErr != nil {
						fmt.Fprintf(os.Stderr, "[realtime] Stop: write stop-failed record failed: %v\n", writeErr)
					}
					// 保留 current / curDir，标记 session.state 可见
					// 关键：archiveActive 使用 archivePending（不恢复旧值）
					stamped := *sess
					stamped.State = realtime.StateStopFailed
					b.mu.Lock()
					b.current = &stamped
					b.curDir = dir
					b.archiveActive = archivePending
					b.mu.Unlock()
				}
				return fmt.Errorf("停止 DataFactory 失败: %v", combined)
			}
			// 进程已退出但 Stop 仍报错：清理
			b.sessionManager.RemoveSessionDir(dir)
			b.mu.Lock()
			b.current = nil
			b.curDir = ""
			b.archiveActive = false
			b.mu.Unlock()
			if archiveErr != nil {
				return fmt.Errorf("停止 DataFactory 失败: %v; 归档停止失败: %v", stopErr, archiveErr)
			}
			return stopErr
		}
	}

	// 阶段 H 收口：archive flush 失败时保留 session dir 作为诊断记录。
	// 进程已死但 archive 数据可能不完整，保留 session.json 供后续分析。
	// 下次启动由 CleanupOrphans 机制处理该目录（stop-failed 状态不被自动清理）。
	if archiveErr != nil {
		rec, _ := b.sessionManager.ReadSessionRecord(dir)
		rec.State = realtime.StateStopFailed
		if writeErr := b.sessionManager.WriteSessionJSON(dir, rec); writeErr != nil {
			fmt.Fprintf(os.Stderr, "[realtime] Stop: write archive-failure record failed: %v\n", writeErr)
		}
	} else {
		b.sessionManager.RemoveSessionDir(dir)
	}
	b.mu.Lock()
	b.current = nil
	b.curDir = ""
	b.archiveActive = false
	b.mu.Unlock()
	if archiveErr != nil {
		return fmt.Errorf("归档停止失败: %v", archiveErr)
	}
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
