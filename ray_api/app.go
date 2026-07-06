package main

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"sync"

	"raymonitor/alert"
	"raymonitor/collector"
	"raymonitor/config"
	"raymonitor/logx"
	"raymonitor/model"
	"raymonitor/storage"
)

// App 是 Wails 绑定层：持有采集管理器、存储、配置，暴露方法给前端。
//
// v2 多集群：用 CollectorManager 管多个集群采集器。前端方法带 clusterID 参数。
// 错误通过返回结构体的 Error 字段传递，不 panic（遵循 wails-backend 规范）。
type App struct {
	ctx context.Context

	mu      sync.Mutex
	cfg     config.Config
	store   *storage.Store
	manager *collector.CollectorManager
	alerts  *alert.Manager
}

// NewApp 构造 App。实际资源在 startup 时初始化。
func NewApp() *App {
	return &App{}
}

// startup Wails 启动回调。初始化日志、存储、采集管理器，但不自动开始采集
// （由前端调用 StartAll/StartCluster 控制）。
// 顺序：日志最先初始化，确保后续任何错误都能落盘可见。
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	dbg := []string{"=== startup diagnostic ==="}

	cfg, err := config.Load()
	if err != nil {
		dbg = append(dbg, "config load FAILED: "+err.Error())
		cfg = config.Default()
	} else {
		dbg = append(dbg, "config loaded ok, clusters="+itoa(len(cfg.Clusters)))
	}
	a.cfg = cfg

	// 日志最先初始化
	logPath, err := logx.Init(cfg.LogDir)
	if err != nil {
		dbg = append(dbg, "logx.Init FAILED: "+err.Error())
		slog.Default().Warn("init log failed (will use fallback)", "err", err)
	} else {
		dbg = append(dbg, "logx.Init ok, logPath="+logPath)
	}
	logx.L().Info("app starting", "clusters", len(cfg.Clusters), "dbPath", cfg.DBPath)

	store, err := storage.Open(cfg.DBPath)
	if err != nil {
		dbg = append(dbg, "storage.Open FAILED: "+err.Error())
		logx.L().Error("open store failed", "err", err, "dbPath", cfg.DBPath)
	} else {
		dbg = append(dbg, "storage.Open ok")
		a.store = store
	}

	if a.store != nil {
		a.manager = collector.NewManager(a.store, cfg)
		// 创建告警引擎并注入 manager
		a.alerts = alert.NewManager(a.store, cfg.RecoverConsecutive)
		a.manager.SetAlertChecker(a.alerts)
		dbg = append(dbg, "manager created, clusters="+itoa(len(cfg.Clusters)))
	} else {
		dbg = append(dbg, "manager NOT created (store nil)")
	}

	if err := dumpDebug(dbg); err != nil {
		slog.Default().Error("dumpDebug failed", "err", err)
	}
}

// itoa 简单整数转字符串（避免引入 strconv 仅为这一处）。
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}

// dumpDebug 把启动诊断写到 exe 同目录 debug.txt（绕开 logger）。
func dumpDebug(lines []string) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	dir := filepath.Dir(exe)
	content := ""
	for _, l := range lines {
		content += l + "\n"
	}
	return os.WriteFile(filepath.Join(dir, "debug.txt"), []byte(content), 0o644)
}

// shutdown Wails 关闭回调。停止所有采集、关闭存储。
func (a *App) shutdown(ctx context.Context) {
	if a.manager != nil {
		a.manager.StopAll()
	}
	if a.store != nil {
		_ = a.store.Close()
	}
	logx.L().Info("app shutdown")
}

// ---- 采集控制 ----

// StartAll 启动所有集群采集。
func (a *App) StartAll() {
	if a.manager == nil {
		return
	}
	a.manager.StartAll()
}

// StopAll 停止所有集群采集。
func (a *App) StopAll() {
	if a.manager == nil {
		return
	}
	a.manager.StopAll()
}

// StartCluster 启动单个集群采集（热加场景）。
func (a *App) StartCluster(clusterID string) {
	if a.manager == nil {
		return
	}
	a.manager.StartCluster(clusterID)
}

// StopCluster 停止单个集群采集。
func (a *App) StopCluster(clusterID string) {
	if a.manager == nil {
		return
	}
	a.manager.StopCluster(clusterID)
}

// ListClusterIDs 所有集群 ID。
func (a *App) ListClusterIDs() []string {
	if a.manager == nil {
		return nil
	}
	return a.manager.ListClusterIDs()
}

// GetClusterStatus 某集群采集状态。
func (a *App) GetClusterStatus(clusterID string) model.CollectorStatus {
	if a.manager == nil {
		return model.CollectorStatus{}
	}
	return a.manager.Status(clusterID)
}

// GetPerf 某集群性能评估。
func (a *App) GetPerf(clusterID string) model.PerfMetrics {
	if a.manager == nil {
		return model.PerfMetrics{}
	}
	return a.manager.Perf(clusterID)
}

// GetGlobalPerf 全局负荷评估。
func (a *App) GetGlobalPerf() model.GlobalPerf {
	if a.manager == nil {
		return model.GlobalPerf{}
	}
	return a.manager.GlobalPerf()
}

// ---- 告警 ----

// ListAlerts 列出未消除报警。clusterID 为空则所有集群。
func (a *App) ListAlerts(clusterID string) []model.Alert {
	if a.alerts == nil {
		return nil
	}
	res, err := a.alerts.ListActive(clusterID)
	if err != nil {
		logx.L().Warn("list alerts failed", "err", err)
		return nil
	}
	return res
}

// CountAlerts 统计未消除报警数。clusterID 为空则全部。
func (a *App) CountAlerts(clusterID string) int {
	if a.alerts == nil {
		return 0
	}
	n, err := a.alerts.CountActive(clusterID)
	if err != nil {
		return 0
	}
	return n
}

// AckAlert 确认报警。
func (a *App) AckAlert(alertID int64) bool {
	if a.alerts == nil {
		return false
	}
	if err := a.alerts.Ack(alertID); err != nil {
		logx.L().Warn("ack alert failed", "err", err)
		return false
	}
	return true
}

// ---- 当前态查询（带 clusterID）----

// GetSnapshot 某集群当前态快照。
func (a *App) GetSnapshot(clusterID string) *collector.Snapshot {
	if a.manager == nil {
		return nil
	}
	return a.manager.Snapshot(clusterID)
}

// GetNodes 某集群当前节点列表。
func (a *App) GetNodes(clusterID string) []model.NodeMetric {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Nodes
}

// GetWorkers 某集群当前 worker 进程。
func (a *App) GetWorkers(clusterID string) []model.WorkerSnapshot {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Workers
}

// GetActors 某集群当前 Actor。
func (a *App) GetActors(clusterID string) []model.ActorSnapshot {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Actors
}

// GetJobs 某集群当前作业。
func (a *App) GetJobs(clusterID string) []model.JobSnapshot {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Jobs
}

// ---- 历史查询（带 clusterID，阶段4存储改造后生效）----

// HistoryRange 时间范围参数（毫秒时间戳）。
type HistoryRange struct {
	From int64 `json:"from"`
	To   int64 `json:"to"`
}

// GetNodeHistory 查询某集群某节点硬件时序历史。
func (a *App) GetNodeHistory(clusterID, nodeID string, r HistoryRange) []model.NodeMetric {
	if a.store == nil {
		return nil
	}
	res, err := a.store.QueryNodeHistory(clusterID, nodeID, r.From, r.To)
	if err != nil {
		logx.L().Warn("query node history failed", "err", err)
		return nil
	}
	return res
}

// GetActorEvents 查询某集群 Actor 状态变迁事件。
func (a *App) GetActorEvents(clusterID string, r HistoryRange) []model.ActorEvent {
	if a.store == nil {
		return nil
	}
	res, err := a.store.QueryActorEvents(clusterID, r.From, r.To)
	if err != nil {
		logx.L().Warn("query actor events failed", "err", err)
		return nil
	}
	return res
}

// GetJobHistory 查询某集群作业历史。status 为空则不限。
func (a *App) GetJobHistory(clusterID string, r HistoryRange, status string) []model.JobSnapshot {
	if a.store == nil {
		return nil
	}
	res, err := a.store.QueryJobHistory(clusterID, r.From, r.To, status)
	if err != nil {
		logx.L().Warn("query job history failed", "err", err)
		return nil
	}
	return res
}

// ---- 配置 ----

// GetConfig 返回当前配置。
func (a *App) GetConfig() config.Config {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.cfg
}

// SaveConfigResult 保存配置结果。
type SaveConfigResult struct {
	Success bool   `json:"success"`
	Error   string `json:"error"`
}

// SaveConfig 保存全局配置。集群列表变更由 Manager 热增减；
// 采样间隔变更则重建所有采集器（应用新间隔）。
func (a *App) SaveConfig(cfg config.Config) SaveConfigResult {
	a.mu.Lock()
	old := a.cfg
	a.cfg = cfg
	a.mu.Unlock()
	if err := config.Save(cfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}
	if a.manager != nil {
		// 采样间隔变了 → 重建所有采集器应用新间隔
		if old.SampleEvery != cfg.SampleEvery {
			a.manager.ReloadAll(cfg)
		} else {
			a.manager.SyncClusters(old.Clusters, cfg.Clusters)
		}
	}
	logx.L().Info("config saved", "clusters", len(cfg.Clusters), "sampleEvery", cfg.SampleEvery)
	return SaveConfigResult{Success: true}
}

// AddCluster 添加集群（热启动）。
func (a *App) AddCluster(cl config.ClusterConfig) SaveConfigResult {
	a.mu.Lock()
	a.cfg.Clusters = append(a.cfg.Clusters, cl)
	a.mu.Unlock()
	if err := config.Save(a.cfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}
	if a.manager != nil {
		a.manager.AddCluster(cl)
	}
	return SaveConfigResult{Success: true}
}

// RemoveCluster 删除集群。
func (a *App) RemoveCluster(id string) SaveConfigResult {
	a.mu.Lock()
	out := a.cfg.Clusters[:0]
	for _, c := range a.cfg.Clusters {
		if c.ID != id {
			out = append(out, c)
		}
	}
	a.cfg.Clusters = out
	a.mu.Unlock()
	if err := config.Save(a.cfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}
	if a.manager != nil {
		a.manager.RemoveCluster(id)
	}
	return SaveConfigResult{Success: true}
}

// UpdateCluster 更新集群配置（URL/间隔/阈值变更，热重建）。
func (a *App) UpdateCluster(cl config.ClusterConfig) SaveConfigResult {
	a.mu.Lock()
	for i, c := range a.cfg.Clusters {
		if c.ID == cl.ID {
			a.cfg.Clusters[i] = cl
			break
		}
	}
	a.mu.Unlock()
	if err := config.Save(a.cfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}
	if a.manager != nil {
		a.manager.UpdateCluster(cl)
	}
	return SaveConfigResult{Success: true}
}

// OpenInFolder 打开目录（跨平台）。
func (a *App) OpenInFolder(path string) {
	openInFolder(a.ctx, path)
}

// GetLogPath 返回日志文件实际路径。
func (a *App) GetLogPath() string {
	dir := a.cfg.LogDir
	if dir == "" {
		dir = "logs"
	}
	if !filepath.IsAbs(dir) {
		if exe, err := os.Executable(); err == nil {
			dir = filepath.Join(filepath.Dir(exe), dir)
		}
	}
	return filepath.Join(dir, "ray_monitor.log")
}

// GetDBPath 返回数据库实际路径。
func (a *App) GetDBPath() string {
	dir := a.cfg.DBPath
	if filepath.IsAbs(dir) {
		return dir
	}
	if exe, err := os.Executable(); err == nil {
		return filepath.Join(filepath.Dir(exe), dir)
	}
	return dir
}
