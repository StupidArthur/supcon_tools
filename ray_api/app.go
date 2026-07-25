package main

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"raymonitor/alert"
	"raymonitor/collector"
	"raymonitor/config"
	"raymonitor/logx"
	"raymonitor/model"
	"raymonitor/storage"
)

type App struct {
	ctx context.Context

	mu      sync.Mutex
	cfg     config.Config
	store   *storage.Store
	manager *collector.CollectorManager
	alerts  *alert.Manager

	cleanupCancel context.CancelFunc
}

func NewApp() *App {
	return &App{}
}

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

	logPath, err := logx.Init(cfg.LogDir)
	if err != nil {
		dbg = append(dbg, "logx.Init FAILED: "+err.Error())
		slog.Default().Warn("init log failed (will use fallback)", "err", err)
	} else {
		dbg = append(dbg, "logx.Init ok, logPath="+logPath)
	}

	dbPath := a.resolveDBPath(cfg.DBPath)
	logx.L().Info("app starting", "clusters", len(cfg.Clusters), "dbPath", dbPath)

	store, err := storage.Open(dbPath)
	if err != nil {
		dbg = append(dbg, "storage.Open FAILED: "+err.Error())
		logx.L().Error("open store failed", "err", err, "dbPath", dbPath)
	} else {
		dbg = append(dbg, "storage.Open ok, path="+dbPath)
		a.store = store
	}

	if a.store != nil {
		a.manager = collector.NewManager(a.store, cfg)
		a.alerts = alert.NewManager(a.store, cfg.RecoverConsecutive)
		a.manager.SetAlertChecker(a.alerts)
		dbg = append(dbg, "manager created, clusters="+itoa(len(cfg.Clusters)))

		a.startCleanupLoop(cfg)
	} else {
		dbg = append(dbg, "manager NOT created (store nil)")
	}

	if err := dumpDebug(dbg); err != nil {
		slog.Default().Error("dumpDebug failed", "err", err)
	}
}

func (a *App) resolveDBPath(dbPath string) string {
	baseDir := ""
	if exe, err := os.Executable(); err == nil {
		baseDir = filepath.Dir(exe)
	} else {
		baseDir = "."
	}
	resolved := config.ResolveRuntimePath(dbPath, baseDir)
	if dir := filepath.Dir(resolved); dir != "." {
		_ = os.MkdirAll(dir, 0o755)
	}
	return resolved
}

func (a *App) startCleanupLoop(cfg config.Config) {
	cleanupCtx, cancel := context.WithCancel(a.ctx)
	a.cleanupCancel = cancel

	retentionDays := cfg.EffectiveRetentionDays()
	everyHours := cfg.EffectiveCleanupEveryHours()

	go func() {
		a.runCleanup(retentionDays)

		ticker := time.NewTicker(time.Duration(everyHours) * time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-cleanupCtx.Done():
				return
			case <-ticker.C:
				a.runCleanup(retentionDays)
			}
		}
	}()
}

func (a *App) runCleanup(retentionDays int) {
	if a.store == nil {
		return
	}
	cutoff := time.Now().AddDate(0, 0, -retentionDays).UnixMilli()
	start := time.Now()
	result, err := a.store.CleanupBefore(cutoff)
	if err != nil {
		logx.L().Warn("retention cleanup failed", "err", err, "cutoff", cutoff)
		return
	}
	logx.L().Info("retention cleanup done",
		"cutoff", cutoff, "ms", time.Since(start).Milliseconds(),
		"nodeMetric", result.NodeMetric, "workerSnapshot", result.WorkerSnapshot,
		"actorSnapshot", result.ActorSnapshot, "jobSnapshot", result.JobSnapshot,
		"clusterMetric", result.ClusterMetric)
}

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

func (a *App) shutdown(ctx context.Context) {
	if a.cleanupCancel != nil {
		a.cleanupCancel()
	}
	if a.manager != nil {
		a.manager.StopAll()
	}
	if a.store != nil {
		_ = a.store.Close()
	}
	logx.L().Info("app shutdown")
}

// ---- 采集控制 ----

func (a *App) StartAll() {
	if a.manager == nil {
		return
	}
	a.manager.StartAll()
}

func (a *App) StopAll() {
	if a.manager == nil {
		return
	}
	a.manager.StopAll()
}

func (a *App) StartCluster(clusterID string) {
	if a.manager == nil {
		return
	}
	a.manager.StartCluster(clusterID)
}

func (a *App) StopCluster(clusterID string) {
	if a.manager == nil {
		return
	}
	a.manager.StopCluster(clusterID)
}

func (a *App) ListClusterIDs() []string {
	if a.manager == nil {
		return nil
	}
	return a.manager.ListClusterIDs()
}

func (a *App) GetClusterStatus(clusterID string) model.CollectorStatus {
	if a.manager == nil {
		return model.CollectorStatus{}
	}
	return a.manager.Status(clusterID)
}

func (a *App) GetPerf(clusterID string) model.PerfMetrics {
	if a.manager == nil {
		return model.PerfMetrics{}
	}
	return a.manager.Perf(clusterID)
}

func (a *App) GetGlobalPerf() model.GlobalPerf {
	if a.manager == nil {
		return model.GlobalPerf{}
	}
	return a.manager.GlobalPerf()
}

// ---- 告警 ----

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

// ---- 当前态查询 ----

func (a *App) GetSnapshot(clusterID string) *collector.Snapshot {
	if a.manager == nil {
		return nil
	}
	return a.manager.Snapshot(clusterID)
}

func (a *App) GetNodes(clusterID string) []model.NodeMetric {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Nodes
}

func (a *App) GetWorkers(clusterID string) []model.WorkerSnapshot {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Workers
}

func (a *App) GetActors(clusterID string) []model.ActorSnapshot {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Actors
}

func (a *App) GetJobs(clusterID string) []model.JobSnapshot {
	snap := a.GetSnapshot(clusterID)
	if snap == nil {
		return nil
	}
	return snap.Jobs
}

// ---- 历史查询 ----

type HistoryRange struct {
	From int64 `json:"from"`
	To   int64 `json:"to"`
}

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

func (a *App) GetConfig() config.Config {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.cfg
}

type SaveConfigResult struct {
	Success bool   `json:"success"`
	Error   string `json:"error"`
}

func (a *App) SaveConfig(cfg config.Config) SaveConfigResult {
	if err := config.Validate(cfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}

	a.mu.Lock()
	old := a.cfg
	a.mu.Unlock()

	if err := config.Save(cfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}

	if a.manager != nil {
		needReload := old.SampleEvery != cfg.SampleEvery ||
			old.TimeoutSec != cfg.TimeoutSec ||
			old.Concurrency != cfg.Concurrency ||
			old.GlobalConcurrency != cfg.GlobalConcurrency
		if needReload {
			a.manager.ReloadAll(cfg)
		} else {
			a.manager.SyncClusters(old.Clusters, cfg.Clusters)
		}
	}

	a.mu.Lock()
	a.cfg = cfg
	a.mu.Unlock()

	logx.L().Info("config saved", "clusters", len(cfg.Clusters), "sampleEvery", cfg.SampleEvery)
	return SaveConfigResult{Success: true}
}

func (a *App) AddCluster(cl config.ClusterConfig) SaveConfigResult {
	a.mu.Lock()
	newCfg := a.cfg
	newCfg.Clusters = make([]config.ClusterConfig, len(a.cfg.Clusters), len(a.cfg.Clusters)+1)
	copy(newCfg.Clusters, a.cfg.Clusters)
	newCfg.Clusters = append(newCfg.Clusters, cl)
	a.mu.Unlock()

	if err := config.Validate(newCfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}
	if err := config.Save(newCfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}

	a.mu.Lock()
	a.cfg = newCfg
	a.mu.Unlock()

	if a.manager != nil {
		a.manager.AddCluster(cl)
	}
	return SaveConfigResult{Success: true}
}

func (a *App) RemoveCluster(id string) SaveConfigResult {
	a.mu.Lock()
	newCfg := a.cfg
	out := make([]config.ClusterConfig, 0, len(a.cfg.Clusters))
	for _, c := range a.cfg.Clusters {
		if c.ID != id {
			out = append(out, c)
		}
	}
	newCfg.Clusters = out
	a.mu.Unlock()

	if err := config.Save(newCfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}

	a.mu.Lock()
	a.cfg = newCfg
	a.mu.Unlock()

	if a.manager != nil {
		a.manager.RemoveCluster(id)
	}
	return SaveConfigResult{Success: true}
}

func (a *App) UpdateCluster(cl config.ClusterConfig) SaveConfigResult {
	a.mu.Lock()
	newCfg := a.cfg
	newCfg.Clusters = make([]config.ClusterConfig, len(a.cfg.Clusters))
	copy(newCfg.Clusters, a.cfg.Clusters)
	found := false
	for i, c := range newCfg.Clusters {
		if c.ID == cl.ID {
			newCfg.Clusters[i] = cl
			found = true
			break
		}
	}
	a.mu.Unlock()

	if !found {
		return SaveConfigResult{Error: "cluster not found: " + cl.ID}
	}
	if err := config.Validate(newCfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}
	if err := config.Save(newCfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}

	a.mu.Lock()
	a.cfg = newCfg
	a.mu.Unlock()

	if a.manager != nil {
		a.manager.UpdateCluster(cl)
	}
	return SaveConfigResult{Success: true}
}

func (a *App) OpenInFolder(path string) {
	openInFolder(a.ctx, path)
}

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

func (a *App) GetDBPath() string {
	return a.resolveDBPath(a.cfg.DBPath)
}
