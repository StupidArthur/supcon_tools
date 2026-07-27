package main

import (
	"context"
	"encoding/csv"
	"fmt"
	"log/slog"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"raymonitor/alert"
	"raymonitor/collector"
	"raymonitor/config"
	"raymonitor/logx"
	"raymonitor/model"
	"raymonitor/storage"
	"raymonitor/wecom"
)

// DefaultRetentionDays 是节点/worker/actor/job/cluster 时序快照的保留天数。
// 未对用户暴露，需要调整时改这里。
const DefaultRetentionDays = 90

// DefaultCleanupEveryHours 是后台清理任务的执行间隔（小时）。
// 未对用户暴露，需要调整时改这里。
const DefaultCleanupEveryHours = 6

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
	logx.Event("app", "app_starting",
		"clusters", len(cfg.Clusters),
		"cluster_ids", clusterIDs(cfg.Clusters),
		"sample_every_sec", cfg.SampleInterval(),
		"timeout_sec", cfg.RequestTimeoutSec,
		"concurrency", cfg.DetailNodeConcurrency,
		"global_concurrency", collector.DefaultGlobalConcurrency,
		"recover_consecutive", alert.DefaultRecoverConsecutive,
		"retention_days", DefaultRetentionDays,
		"cleanup_every_hours", DefaultCleanupEveryHours,
		"db_path", dbPath)

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
		a.alerts = alert.NewManager(a.store)
		a.manager.SetAlertChecker(a.alerts)
		dbg = append(dbg, "manager created, clusters="+itoa(len(cfg.Clusters)))

		a.startCleanupLoop()
		logx.Event("app", "runtime_initialized", "store_ok", true, "collectors", len(cfg.Clusters))
	} else {
		dbg = append(dbg, "manager NOT created (store nil)")
		logx.Event("error", "runtime_initialization_failed", "store_ok", false, "db_path", dbPath)
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

func (a *App) startCleanupLoop() {
	cleanupCtx, cancel := context.WithCancel(a.ctx)
	a.cleanupCancel = cancel

	go func() {
		a.runCleanup(cleanupCtx, DefaultRetentionDays)

		ticker := time.NewTicker(time.Duration(DefaultCleanupEveryHours) * time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-cleanupCtx.Done():
				return
			case <-ticker.C:
				a.runCleanup(cleanupCtx, DefaultRetentionDays)
			}
		}
	}()
}

func (a *App) runCleanup(ctx context.Context, retentionDays int) {
	if a.store == nil {
		return
	}
	cutoff := time.Now().AddDate(0, 0, -retentionDays).UnixMilli()
	start := time.Now()
	result, err := a.store.CleanupBefore(ctx, cutoff)
	if err != nil {
		if ctx.Err() != nil {
			return
		}
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
	logx.Event("app", "app_shutdown")
	logx.Close()
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
	am := a.alertManager()
	if am == nil {
		return nil
	}
	res, err := am.ListActive(clusterID)
	if err != nil {
		logx.L().Warn("list alerts failed", "err", err)
		return nil
	}
	return res
}

func (a *App) CountAlerts(clusterID string) int {
	am := a.alertManager()
	if am == nil {
		return 0
	}
	n, err := am.CountActive(clusterID)
	if err != nil {
		return 0
	}
	return n
}

func (a *App) AckAlert(alertID int64) bool {
	am := a.alertManager()
	if am == nil {
		return false
	}
	if err := am.Ack(alertID); err != nil {
		logx.L().Warn("ack alert failed", "err", err)
		return false
	}
	return true
}

func (a *App) alertManager() *alert.Manager {
	a.mu.Lock()
	am := a.alerts
	a.mu.Unlock()
	return am
}

// ---- 当前态查询 ----

func (a *App) GetSnapshot(clusterID string) *collector.Snapshot {
	if a.manager == nil {
		return nil
	}
	return a.manager.Snapshot(clusterID)
}

func (a *App) GetNodes(clusterID string) []model.NodeMetric {
	if a.manager == nil {
		return nil
	}
	return a.manager.Nodes(clusterID)
}

func (a *App) GetWorkers(clusterID string) []model.WorkerSnapshot {
	if a.manager == nil {
		return nil
	}
	return a.manager.Workers(clusterID)
}

func (a *App) GetActors(clusterID string) []model.ActorSnapshot {
	if a.manager == nil {
		return nil
	}
	return a.manager.Actors(clusterID)
}

func (a *App) GetJobs(clusterID string) []model.JobSnapshot {
	if a.manager == nil {
		return nil
	}
	return a.manager.Jobs(clusterID)
}

func (a *App) GetOverview(clusterID string) model.Overview {
	if a.manager == nil {
		return model.Overview{}
	}
	return a.manager.Overview(clusterID)
}

func (a *App) GetHealth(clusterID string) model.CollectionHealth {
	if a.manager == nil {
		return model.CollectionHealth{}
	}
	return a.manager.Health(clusterID)
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
	a.mu.Unlock()

	if err := config.Save(cfg); err != nil {
		return SaveConfigResult{Error: err.Error()}
	}

	if a.manager != nil {
		a.manager.ApplyConfig(cfg)
	}

	a.mu.Lock()
	a.cfg = cfg
	a.mu.Unlock()

	logx.L().Info("config saved", "clusters", len(cfg.Clusters), "sampleEvery", cfg.SampleEvery)
	logx.Event("app", "config_saved",
		"clusters", len(cfg.Clusters),
		"cluster_ids", clusterIDs(cfg.Clusters),
		"sample_every_sec", cfg.SampleInterval(),
		"timeout_sec", cfg.RequestTimeoutSec,
		"concurrency", cfg.DetailNodeConcurrency,
		"global_concurrency", collector.DefaultGlobalConcurrency,
		"recover_consecutive", alert.DefaultRecoverConsecutive,
		"retention_days", DefaultRetentionDays,
		"cleanup_every_hours", DefaultCleanupEveryHours)
	return SaveConfigResult{Success: true}
}

func clusterIDs(clusters []config.ClusterConfig) []string {
	ids := make([]string, 0, len(clusters))
	for _, cluster := range clusters {
		ids = append(ids, cluster.ID)
	}
	return ids
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
		a.manager.ApplyConfig(newCfg)
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
		a.manager.ApplyConfig(newCfg)
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
		a.manager.ApplyConfig(newCfg)
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

// GetRecentAPILogs 返回最近 limit 条 API 日志（最新在前）。
func (a *App) GetRecentAPILogs(limit int) []collector.APILogEntry {
	if a.manager == nil {
		return nil
	}
	return a.manager.RecentAPILogs(limit)
}

// LogFrontendEvent 由前端调用，记录用户操作/页面刷新等事件。
func (a *App) LogFrontendEvent(cluster, phase, message string) {
	if a.manager == nil {
		return
	}
	a.manager.LogFrontendEvent(cluster, phase, message)
}

// ---- Webhook 推送 ----

// webhookClient 从给定的 WebhookURL 构造 wecom 客户端。
// URL 形如 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx-xx。
// 内部从 URL 中抽出 key 并剥掉 query 再传给 wecom 包。
func (a *App) webhookClient(raw string) (*wecom.Client, error) {
	if raw == "" {
		return nil, fmt.Errorf("未配置 webhook URL")
	}
	u, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("webhook URL 解析失败: %w", err)
	}
	key := u.Query().Get("key")
	if key == "" {
		return nil, fmt.Errorf("webhook URL 必须包含 ?key= 参数")
	}
	u.RawQuery = ""
	return wecom.NewClient(key, wecom.WithWebhookURL(u.String()))
}

type TestWebhookResult struct {
	Success bool   `json:"success"`
	Error   string `json:"error"`
}

// TestWebhook 用传入的 URL 发一条"配置成功"测试消息，不需要先保存配置。
func (a *App) TestWebhook(webhookURL string) TestWebhookResult {
	client, err := a.webhookClient(webhookURL)
	if err != nil {
		return TestWebhookResult{Error: err.Error()}
	}
	ctx, cancel := context.WithTimeout(a.ctx, 30*time.Second)
	defer cancel()

	content := "## Ray 监控 - 推送配置成功\n\nWebhook 已连通，后续告警与快照将通过此通道推送。"
	payload, err := wecom.BuildMarkdown(content)
	if err != nil {
		return TestWebhookResult{Error: err.Error()}
	}
	if _, err := client.Send(ctx, payload); err != nil {
		logx.L().Warn("test webhook failed", "err", err)
		return TestWebhookResult{Error: err.Error()}
	}
	logx.Event("app", "webhook_test_sent")
	return TestWebhookResult{Success: true}
}

type PushSnapshotResult struct {
	Success   bool   `json:"success"`
	Path      string `json:"path"`
	Error     string `json:"error"`
	PushError string `json:"pushError"`
}

// ExportSnapshotAndPush 先按 ExportSnapshot 导出 CSV 到本地，再把 CSV 文件推送到企业微信。
// 导出失败不会推送；推送失败不会回滚已写入的文件。
func (a *App) ExportSnapshotAndPush(nameBase string, headers []string, rows [][]string) PushSnapshotResult {
	expRes := a.ExportSnapshot(nameBase, headers, rows)
	if !expRes.Success {
		return PushSnapshotResult{Error: expRes.Error}
	}

	a.mu.Lock()
	raw := a.cfg.WebhookURL
	a.mu.Unlock()
	client, err := a.webhookClient(raw)
	if err != nil {
		return PushSnapshotResult{Path: expRes.Path, PushError: err.Error()}
	}
	ctx, cancel := context.WithTimeout(a.ctx, 60*time.Second)
	defer cancel()

	// 1. 上传 CSV 文件拿 media_id（3 天有效）
	mediaID, err := client.UploadMedia(ctx, expRes.Path, "file")
	if err != nil {
		logx.L().Warn("snapshot upload failed", "path", expRes.Path, "err", err)
		return PushSnapshotResult{Path: expRes.Path, PushError: "上传文件失败: " + err.Error()}
	}
	// 2. 发文件消息
	if _, err := client.SendFile(ctx, mediaID); err != nil {
		logx.L().Warn("snapshot push failed", "path", expRes.Path, "mediaID", mediaID, "err", err)
		return PushSnapshotResult{Path: expRes.Path, PushError: "发送文件消息失败: " + err.Error()}
	}
	return PushSnapshotResult{Success: true, Path: expRes.Path}
}

// ---- 快照导出 ----

type ExportSnapshotResult struct {
	Success bool   `json:"success"`
	Path    string `json:"path"`
	Error   string `json:"error"`
}

// ExportSnapshot 将当前页列表导出为单页 CSV。
// nameBase 形如 "集群名_节点" 或 "全局报警"，后端追加 _{datetime}_snapshot.csv。
// 文件落到 exe 同级 snapshot 目录（不存在则新建）。返回完整路径。
func (a *App) ExportSnapshot(nameBase string, headers []string, rows [][]string) ExportSnapshotResult {
	baseDir := ""
	if exe, err := os.Executable(); err == nil {
		baseDir = filepath.Dir(exe)
	} else {
		baseDir = "."
	}
	snapshotDir := filepath.Join(baseDir, "snapshot")
	if err := os.MkdirAll(snapshotDir, 0o755); err != nil {
		return ExportSnapshotResult{Error: "create snapshot dir: " + err.Error()}
	}

	safe := sanitizeFilename(nameBase)
	stamp := time.Now().Format("20060102_150405")
	filename := fmt.Sprintf("%s_%s_snapshot.csv", safe, stamp)
	full := filepath.Join(snapshotDir, filename)

	f, err := os.Create(full)
	if err != nil {
		return ExportSnapshotResult{Error: "create file: " + err.Error()}
	}
	defer f.Close()

	// UTF-8 BOM，让 Excel 正确识别中文
	if _, err := f.Write([]byte{0xEF, 0xBB, 0xBF}); err != nil {
		return ExportSnapshotResult{Error: "write BOM: " + err.Error()}
	}
	w := csv.NewWriter(f)
	if len(headers) > 0 {
		if err := w.Write(headers); err != nil {
			return ExportSnapshotResult{Error: "write header: " + err.Error()}
		}
	}
	for _, row := range rows {
		if err := w.Write(row); err != nil {
			return ExportSnapshotResult{Error: "write row: " + err.Error()}
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return ExportSnapshotResult{Error: "flush: " + err.Error()}
	}
	logx.L().Info("snapshot exported", "path", full, "headers", len(headers), "rows", len(rows))
	return ExportSnapshotResult{Success: true, Path: full}
}

// sanitizeFilename 替换 Windows 文件名非法字符为下划线。
func sanitizeFilename(s string) string {
	repl := strings.NewReplacer(
		`\`, "_", `/`, "_", `:`, "_", `*`, "_", `?`, "_",
		`"`, "_", `<`, "_", `>`, "_", `|`, "_",
	)
	return strings.TrimSpace(repl.Replace(s))
}
