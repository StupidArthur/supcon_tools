package collector

import (
	"context"
	"errors"
	"fmt"
	"runtime"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	"raymonitor/logx"
	"raymonitor/model"
)

// EnableHeavyHistoryStorage 控制是否写入 worker_snapshot / actor_snapshot /
// cluster_metric / job_event 四张大表。生产验证版本暂时关闭以降低 I/O 压力。
// 保留写入：node_metric / actor_event / job_snapshot / alert / alert_event。
const EnableHeavyHistoryStorage = false

var heavyStorageLogged atomic.Bool

type Store interface {
	WriteNodeMetrics(clusterID string, ns []model.NodeMetric) error
	WriteWorkers(clusterID string, ws []model.WorkerSnapshot) error
	WriteActors(clusterID string, as []model.ActorSnapshot) error
	WriteJobs(clusterID string, js []model.JobSnapshot) error
	WriteCluster(clusterID string, c model.ClusterMetric) error
	WriteActorEvents(clusterID string, es []model.ActorEvent) error
	WriteJobEvents(clusterID string, es []model.JobEvent) error
}

type Snapshot struct {
	Cluster model.ClusterMetric    `json:"cluster"`
	Nodes   []model.NodeMetric     `json:"nodes"`
	Workers []model.WorkerSnapshot `json:"workers"`
	Actors  []model.ActorSnapshot  `json:"actors"`
	Jobs    []model.JobSnapshot    `json:"jobs"`
	Health  model.CollectionHealth `json:"health"`
}

type CollectorOpts struct {
	ClusterID    string
	ClusterName  string // 用户可编辑的集群名，用于日志显示
	PlatformURL  string
	Cookie       string
	TimeoutSec   int
	Concurrency  int
}

type RequestLimiter interface {
	Acquire(ctx context.Context) error
	Release()
	Capacity() int
}

type AlertCallback func(
	clusterID string,
	nodes []model.NodeMetric,
	workers []model.WorkerSnapshot,
	staleNodes map[string]bool,
)

type Collector struct {
	client  *Client
	store   Store
	opts    CollectorOpts
	limiter RequestLimiter

	detailLock RequestLimiter // capacity=1，集群间 detail 排队
	apiLog     *APILog         // 共享 ring buffer，生命周期事件记这里
	onCycleEnd func()         // 通知 Manager 标记本轮数据已更新

	mu     sync.RWMutex
	status model.CollectorStatus
	snap   *Snapshot
	perf   model.PerfMetrics
	health model.CollectionHealth

	workersByNode map[string][]model.WorkerSnapshot
	actorsByNode  map[string][]model.ActorSnapshot
	nodeState     map[string]*model.NodeCollectionState

	prevActorsByNode map[string]map[string]model.ActorSnapshot
	prevJobs         map[string]model.JobSnapshot

	clusterStale bool
	jobsStale    bool
	prevCluster  model.ClusterMetric
	prevJobsList []model.JobSnapshot

	alertMu sync.RWMutex
	onAlert AlertCallback
}

func (c *Collector) SetOnAlert(fn AlertCallback) {
	c.alertMu.Lock()
	c.onAlert = fn
	c.alertMu.Unlock()
}

func (c *Collector) alertCallback() AlertCallback {
	c.alertMu.RLock()
	fn := c.onAlert
	c.alertMu.RUnlock()
	return fn
}

func NewCollector(client *Client, store Store, opts CollectorOpts) *Collector {
	return &Collector{
		client:           client,
		store:            store,
		opts:             opts,
		workersByNode:    map[string][]model.WorkerSnapshot{},
		actorsByNode:     map[string][]model.ActorSnapshot{},
		nodeState:        map[string]*model.NodeCollectionState{},
		prevActorsByNode: map[string]map[string]model.ActorSnapshot{},
		prevJobs:         map[string]model.JobSnapshot{},
	}
}

// SetAPILog 注入共享的 ring buffer，由 manager 在创建 collector 时设置。
func (c *Collector) SetAPILog(l *APILog) {
	c.apiLog = l
}

// SetOnCycleEnd 设置每轮采集结束后的回调（manager 用来标记数据更新时间）。
func (c *Collector) SetOnCycleEnd(fn func()) {
	c.onCycleEnd = fn
}

// logEvent 便捷方法：nil buffer 时静默忽略。
func (c *Collector) logEvent(phase, message string) {
	if c.apiLog != nil {
		name := c.opts.ClusterName
		if name == "" {
			name = c.opts.ClusterID
		}
		c.apiLog.Append("backend", name, phase, message)
	}
}

func (c *Collector) SetLimiter(l RequestLimiter) {
	c.limiter = l
}

func (c *Collector) SetDetailLock(l RequestLimiter) {
	c.detailLock = l
}

func (c *Collector) Status() model.CollectorStatus {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.status
}

func (c *Collector) Snapshot() *Snapshot {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return nil
	}
	s := &Snapshot{
		Cluster: c.snap.Cluster,
		Health:  c.snap.Health,
	}
	s.Nodes = make([]model.NodeMetric, len(c.snap.Nodes))
	copy(s.Nodes, c.snap.Nodes)
	s.Workers = make([]model.WorkerSnapshot, len(c.snap.Workers))
	copy(s.Workers, c.snap.Workers)
	s.Actors = make([]model.ActorSnapshot, len(c.snap.Actors))
	copy(s.Actors, c.snap.Actors)
	s.Jobs = make([]model.JobSnapshot, len(c.snap.Jobs))
	copy(s.Jobs, c.snap.Jobs)
	s.Health.FailedNodes = make([]model.NodeCollectionState, len(c.snap.Health.FailedNodes))
	copy(s.Health.FailedNodes, c.snap.Health.FailedNodes)
	return s
}

// Nodes 只复制节点切片，不复制 Workers/Actors/Jobs。
func (c *Collector) Nodes() []model.NodeMetric {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return nil
	}
	out := make([]model.NodeMetric, len(c.snap.Nodes))
	copy(out, c.snap.Nodes)
	return out
}

// Workers 只复制 Worker 切片。
func (c *Collector) Workers() []model.WorkerSnapshot {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return nil
	}
	out := make([]model.WorkerSnapshot, len(c.snap.Workers))
	copy(out, c.snap.Workers)
	return out
}

// Actors 只复制 Actor 切片。
func (c *Collector) Actors() []model.ActorSnapshot {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return nil
	}
	out := make([]model.ActorSnapshot, len(c.snap.Actors))
	copy(out, c.snap.Actors)
	return out
}

// Jobs 只复制 Job 切片。
func (c *Collector) Jobs() []model.JobSnapshot {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return nil
	}
	out := make([]model.JobSnapshot, len(c.snap.Jobs))
	copy(out, c.snap.Jobs)
	return out
}

// Overview 返回概览页所需的轻量数据（Cluster + Nodes + Jobs），不复制 Workers/Actors。
func (c *Collector) Overview() model.Overview {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return model.Overview{}
	}
	nodes := make([]model.NodeMetric, len(c.snap.Nodes))
	copy(nodes, c.snap.Nodes)
	jobs := make([]model.JobSnapshot, len(c.snap.Jobs))
	copy(jobs, c.snap.Jobs)
	nodeCount := 0
	for _, n := range nodes {
		if n.State == "ALIVE" {
			nodeCount++
		}
	}
	return model.Overview{
		Cluster:    c.snap.Cluster,
		Nodes:      nodes,
		NodeCount:  nodeCount,
		RecentJobs: jobs,
		UpdatedAt:  model.NowMs(),
	}
}

// Health 只复制健康状态。
func (c *Collector) Health() model.CollectionHealth {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return model.CollectionHealth{}
	}
	h := c.snap.Health
	h.FailedNodes = make([]model.NodeCollectionState, len(c.snap.Health.FailedNodes))
	copy(h.FailedNodes, c.snap.Health.FailedNodes)
	return h
}

func (c *Collector) Perf() model.PerfMetrics {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.perf
}

func (c *Collector) nodeConcurrency() int {
	if c.opts.Concurrency <= 0 {
		return DefaultDetailNodeConcurrency
	}
	return c.opts.Concurrency
}

// concurrency 保留旧名供向后兼容，内部委托 nodeConcurrency。
func (c *Collector) concurrency() int {
	return c.nodeConcurrency()
}

// assessRisk 串行模型下没有固定周期，按绝对阈值判断：
//   - 单次 detail > 3s 视为"忙"（之前看的是占周期的 80%）
//   - 进程内存 > 500MB 视为内存压力
func assessRisk(p model.PerfMetrics) string {
	if p.DetailMaxNodeMs > 3000 || p.ProcMemBytes > 500*1024*1024 {
		return "warn"
	}
	return "ok"
}

func (c *Collector) Start(ctx context.Context) {
	defer func() {
		if r := recover(); r != nil {
			logx.L().Error("collector panic", "cluster", c.opts.ClusterID, "panic", r)
			logx.Event("error", "collector_panic", "cluster", c.opts.ClusterID, "panic", fmt.Sprint(r))
		}
	}()
	c.mu.Lock()
	c.status.Running = true
	c.mu.Unlock()
	logx.L().Info("collector started", "cluster", c.opts.ClusterID)

	cycle := func() bool {
		if ctx.Err() != nil {
			return false
		}
		// 整轮（summary + detail）在同一把集群间锁下串行
		if c.detailLock != nil {
			if err := c.detailLock.Acquire(ctx); err != nil {
				return false
			}
			defer c.detailLock.Release()
		}
		c.logEvent("周期", "开始")
		c.collectSummary(ctx)
		c.collectDetail(ctx)
		c.logEvent("周期", "结束")
		// 通知 Manager 记录数据更新时间，供前端显示"数据来自 Xs 前"
		if c.onCycleEnd != nil {
			c.onCycleEnd()
		}
		return true
	}

	// 立即跑一次首轮
	cycle()

	defer func() {
		c.mu.Lock()
		c.status.Running = false
		c.mu.Unlock()
		logx.L().Info("collector stopped", "cluster", c.opts.ClusterID)
	}()

	// 连续循环：跑完一轮立即跑下一轮，无 tick 间隔。
	// 如果一轮耗时 0（不太可能），用 50ms 退避避免空转。
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		if !cycle() {
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(50 * time.Millisecond):
		}
	}
}

func (c *Collector) recordErr(stage string, err error) {
	if errors.Is(err, context.Canceled) {
		logx.L().Debug("collect canceled", "stage", stage, "cluster", c.opts.ClusterID)
		return
	}
	c.mu.Lock()
	c.status.ErrCount++
	c.status.LastError = truncateErr(err, 300)
	c.status.LastErrorTs = model.NowMs()
	c.status.LastErrorStage = stage
	c.mu.Unlock()
	logx.L().Warn("collect failed", "stage", stage, "cluster", c.opts.ClusterID, "err", err)
	logx.Event("error", "collection_stage_failed",
		"cluster", c.opts.ClusterID, "stage", stage, "error", truncateErr(err, 500))
}

func (c *Collector) recordOK() {
	c.mu.Lock()
	c.status.LastSuccessTs = model.NowMs()
	c.mu.Unlock()
}

func truncateErr(err error, maxLen int) string {
	s := err.Error()
	if len(s) > maxLen {
		return s[:maxLen]
	}
	return s
}

func (c *Collector) acquireLimiter(ctx context.Context) error {
	if c.limiter == nil {
		return nil
	}
	return c.limiter.Acquire(ctx)
}

func (c *Collector) releaseLimiter() {
	if c.limiter != nil {
		c.limiter.Release()
	}
}

func (c *Collector) collectSummary(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}
	start := time.Now()

	if err := c.acquireLimiter(ctx); err != nil {
		if !errors.Is(err, context.Canceled) {
			c.recordErr("summary.limiter", err)
		}
		return
	}
	c.logEvent("summary", "开始")
	nodes, err := c.client.FetchNodes(ctx)
	c.releaseLimiter()

	if err != nil {
		if !errors.Is(err, context.Canceled) {
			c.recordErr("summary", err)
		}
		return
	}

	var storeErr error
	if storeErr = c.store.WriteNodeMetrics(c.opts.ClusterID, nodes); storeErr != nil {
		logx.L().Warn("summary store failed", "cluster", c.opts.ClusterID, "err", storeErr)
		c.mu.Lock()
		c.health.CurrentStorageError = true
		c.health.LastStorageErrorTs = model.NowMs()
		c.health.LastStorageError = truncateErr(storeErr, 300)
		c.mu.Unlock()
	} else {
		c.mu.Lock()
		c.health.CurrentStorageError = false
		c.mu.Unlock()
	}

	summaryMs := time.Since(start).Milliseconds()
	c.recordOK()
	c.refreshSnapshotNodes(nodes)
	c.logEvent("summary", fmt.Sprintf("完成 (%dms, %d 节点)", summaryMs, len(nodes)))

	c.mu.Lock()
	c.perf.SummaryMs = summaryMs
	c.perf.NodeCount = len(nodes)
	c.perf.Risk = assessRisk(c.perf)
	c.mu.Unlock()

	logx.L().Info("summary collected", "cluster", c.opts.ClusterID, "nodes", len(nodes), "ms", summaryMs)
	logx.Event("collection", "summary_completed",
		"cluster", c.opts.ClusterID,
		"nodes", len(nodes),
		"partial_nodes", countPartialNodes(nodes),
		"duration_ms", summaryMs,
		"storage_ok", storeErr == nil)

	if fn := c.alertCallback(); fn != nil {
		c.mu.RLock()
		ns := append([]model.NodeMetric(nil), nodes...)
		var ws []model.WorkerSnapshot
		staleNodes := map[string]bool{}
		if c.snap != nil {
			ws = make([]model.WorkerSnapshot, len(c.snap.Workers))
			copy(ws, c.snap.Workers)
		}
		for nid, st := range c.nodeState {
			if st.CurrentStale {
				staleNodes[nid] = true
			}
		}
		c.mu.RUnlock()
		fn(c.opts.ClusterID, ns, ws, staleNodes)
	}
}

func (c *Collector) collectDetail(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}

	// 集群间锁在 Start() 层的 cycle 闭包里已经获取，本函数不再重复获取。
	// 这也意味着 collectDetail 必须从 Start() 的 cycle 调用，不能独立调用。

	detailStart := time.Now()
	now := model.NowMs()

	c.mu.RLock()
	nodes := c.currentNodeIDs()
	c.mu.RUnlock()

	if len(nodes) == 0 {
		logx.L().Warn("detail skipped: no nodes in snapshot", "cluster", c.opts.ClusterID)
		return
	}

	c.logEvent("detail", fmt.Sprintf("开始 (%d 节点, 并发=%d)", len(nodes), c.nodeConcurrency()))

	// 诊断：记录 detail 开始时的内存与 goroutine 数
	var memStart runtime.MemStats
	runtime.ReadMemStats(&memStart)
	logx.L().Info("detail starting", "cluster", c.opts.ClusterID,
		"nodes", len(nodes), "nodeConcurrency", c.nodeConcurrency(),
		"goroutines", runtime.NumGoroutine(),
		"heapMB", memStart.HeapAlloc/1024/1024)

	// 内存采样 goroutine：每秒记录一次，detail 结束或 ctx 取消后停止
	var completedNodes atomic.Int64
	var activeRequests atomic.Int64
	stopSampling := make(chan struct{})
	var samplingWg sync.WaitGroup
	samplingWg.Add(1)
	go func() {
		defer samplingWg.Done()
		ticker := time.NewTicker(1 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-stopSampling:
				return
			case <-ticker.C:
				var ms runtime.MemStats
				runtime.ReadMemStats(&ms)
				logx.L().Info("detail memory sample",
					"cluster", c.opts.ClusterID,
					"elapsedMs", time.Since(detailStart).Milliseconds(),
					"completedNodes", completedNodes.Load(),
					"activeRequests", activeRequests.Load(),
					"heapAllocMB", ms.HeapAlloc/1024/1024,
					"heapInuseMB", ms.HeapInuse/1024/1024,
					"heapSysMB", ms.HeapSys/1024/1024,
					"sysMB", ms.Sys/1024/1024,
					"goroutines", runtime.NumGoroutine(),
					"numGC", ms.NumGC)
			}
		}
	}()
	defer func() {
		close(stopSampling)
		samplingWg.Wait()
	}()

	c.mu.Lock()
	c.health.LastDetailAttemptTs = now
	c.mu.Unlock()

	type nodeResult struct {
		nodeID  string
		workers []model.WorkerSnapshot
		actors  []model.ActorSnapshot
		node    model.NodeMetric
		ok      bool
		err     error
		ms      int64
	}
	results := make([]nodeResult, len(nodes))
	sem := make(chan struct{}, c.nodeConcurrency())
	var wg sync.WaitGroup

	for i, nid := range nodes {
		wg.Add(1)
		go func(idx int, id string) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results[idx] = nodeResult{nodeID: id, ok: false, err: fmt.Errorf("panic: %v", r)}
					logx.L().Error("node detail goroutine panic", "cluster", c.opts.ClusterID, "node", id, "panic", r)
				}
			}()

			logx.L().Info("detail node started", "cluster", c.opts.ClusterID, "node", id)

			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				results[idx] = nodeResult{nodeID: id, ok: false, err: ctx.Err()}
				completedNodes.Add(1)
				return
			}
			defer func() { <-sem }()

			activeRequests.Add(1)
			defer activeRequests.Add(-1)

			// 阶段 1：HTTP 下载
			ns := time.Now()
			b, err := c.client.FetchNodeDetailRaw(ctx, id)
			downloadMs := time.Since(ns).Milliseconds()
			if err != nil {
				logx.L().Warn("detail node finished", "cluster", c.opts.ClusterID, "node", id,
					"elapsedMs", downloadMs, "err", err)
				results[idx] = nodeResult{nodeID: id, ok: false, err: err, ms: downloadMs}
				completedNodes.Add(1)
				return
			}
			logx.L().Info("detail node response read", "cluster", c.opts.ClusterID, "node", id,
				"elapsedMs", downloadMs, "responseBytes", len(b))

			// 阶段 2：JSON 解析
			ps := time.Now()
			d, err := parseNodeDetail(b, id)
			parseMs := time.Since(ps).Milliseconds()
			if err != nil {
				logx.L().Warn("detail node finished", "cluster", c.opts.ClusterID, "node", id,
					"elapsedMs", time.Since(ns).Milliseconds(), "err", err)
				results[idx] = nodeResult{nodeID: id, ok: false, err: err, ms: time.Since(ns).Milliseconds()}
				completedNodes.Add(1)
				return
			}
			logx.L().Info("detail node parsed", "cluster", c.opts.ClusterID, "node", id,
				"parseMs", parseMs, "workers", len(d.Workers), "actors", len(d.Actors))

			// 阶段 3：完成
			totalMs := time.Since(ns).Milliseconds()
			logx.L().Info("detail node finished", "cluster", c.opts.ClusterID, "node", id,
				"elapsedMs", totalMs, "responseBytes", len(b),
				"workers", len(d.Workers), "actors", len(d.Actors))
			results[idx] = nodeResult{nodeID: id, workers: d.Workers, actors: d.Actors, node: d.Node, ok: true, ms: totalMs}
			completedNodes.Add(1)
		}(i, nid)
	}
	wg.Wait()

	// 统计结果用于事件
	var doneCount, failedCount int
	for _, r := range results {
		if r.ok {
			doneCount++
		} else {
			failedCount++
		}
	}
	detailElapsed := time.Since(detailStart).Milliseconds()
	c.logEvent("detail", fmt.Sprintf("完成 (%dms, %d 成功, %d 失败)", detailElapsed, doneCount, failedCount))

	if ctx.Err() != nil {
		return
	}

	var freshWorkers []model.WorkerSnapshot
	var freshActors []model.ActorSnapshot
	var freshNodes []model.NodeMetric
	var actorEvents []model.ActorEvent
	var storeErrs []error
	var maxNodeMs int64
	var slowNodeID string
	freshNodeSet := map[string]bool{}
	failedNodeSet := map[string]bool{}

	activeNodeSet := map[string]bool{}
	for _, nid := range nodes {
		activeNodeSet[nid] = true
	}

	for _, r := range results {
		if r.ms > maxNodeMs {
			maxNodeMs = r.ms
			slowNodeID = r.nodeID
		}

		st := c.getOrCreateNodeState(r.nodeID)
		st.LastAttemptTs = now

		if r.ok {
			freshNodeSet[r.nodeID] = true
			prevFailures := st.ConsecutiveFailures
			st.LastSuccessTs = now
			st.ConsecutiveFailures = 0
			st.CurrentStale = false
			st.LastError = ""
			st.HasCachedData = true

			c.workersByNode[r.nodeID] = r.workers
			c.actorsByNode[r.nodeID] = r.actors

			freshWorkers = append(freshWorkers, r.workers...)
			freshActors = append(freshActors, r.actors...)
			freshNodes = append(freshNodes, r.node)

			evts := c.diffActorsForNode(r.nodeID, r.actors)
			actorEvents = append(actorEvents, evts...)

			if prevFailures > 0 {
				logx.L().Info("node detail recovered", "cluster", c.opts.ClusterID,
					"node", r.nodeID, "previousConsecutiveFailures", prevFailures)
			}
		} else {
			if errors.Is(r.err, context.Canceled) {
				return
			}
			failedNodeSet[r.nodeID] = true
			st.ConsecutiveFailures++
			st.LastFailureTs = now
			st.LastError = truncateErr(r.err, 300)

			_, workersCached := c.workersByNode[r.nodeID]
			_, actorsCached := c.actorsByNode[r.nodeID]
			hasCached := (workersCached || actorsCached || st.LastSuccessTs > 0)
			st.HasCachedData = hasCached
			if hasCached {
				st.CurrentStale = true
				st.ReusedWorkerCount = len(c.workersByNode[r.nodeID])
				st.ReusedActorCount = len(c.actorsByNode[r.nodeID])
			} else {
				st.CurrentStale = false
				st.ReusedWorkerCount = 0
				st.ReusedActorCount = 0
			}

			logx.L().Warn("fetch node detail failed", "cluster", c.opts.ClusterID,
				"node", r.nodeID, "consecutiveFailures", st.ConsecutiveFailures,
				"hasCachedData", st.HasCachedData, "err", r.err, "ms", r.ms)
		}
	}

	for nid := range c.workersByNode {
		if !activeNodeSet[nid] {
			delete(c.workersByNode, nid)
			delete(c.actorsByNode, nid)
			delete(c.nodeState, nid)
			delete(c.prevActorsByNode, nid)
		}
	}

	var allWorkers []model.WorkerSnapshot
	var allActors []model.ActorSnapshot
	staleWorkerCount := 0
	staleActorCount := 0
	for _, nid := range nodes {
		if freshNodeSet[nid] {
			continue
		}
		if cached := c.workersByNode[nid]; cached != nil {
			allWorkers = append(allWorkers, cached...)
			staleWorkerCount += len(cached)
		}
		if cached := c.actorsByNode[nid]; cached != nil {
			allActors = append(allActors, cached...)
			staleActorCount += len(cached)
		}
	}
	allWorkers = append(allWorkers, freshWorkers...)
	allActors = append(allActors, freshActors...)

	sort.SliceStable(allWorkers, func(i, j int) bool {
		a, b := allWorkers[i], allWorkers[j]
		if a.NodeID != b.NodeID {
			return a.NodeID < b.NodeID
		}
		if a.PID != b.PID {
			return a.PID < b.PID
		}
		return a.ProcessName < b.ProcessName
	})
	sort.SliceStable(allActors, func(i, j int) bool {
		a, b := allActors[i], allActors[j]
		if a.NodeID != b.NodeID {
			return a.NodeID < b.NodeID
		}
		if a.ActorID != b.ActorID {
			return a.ActorID < b.ActorID
		}
		return a.PID < b.PID
	})

	if len(freshNodes) > 0 {
		if err := c.store.WriteNodeMetrics(c.opts.ClusterID, freshNodes); err != nil {
			storeErrs = append(storeErrs, fmt.Errorf("write node metrics (%d nodes, first=%s): %w", len(freshNodes), freshNodes[0].NodeID, err))
		}
	}
	if EnableHeavyHistoryStorage {
		if len(freshWorkers) > 0 {
			if err := c.store.WriteWorkers(c.opts.ClusterID, freshWorkers); err != nil {
				storeErrs = append(storeErrs, fmt.Errorf("write workers: %w", err))
			}
		}
		if len(freshActors) > 0 {
			if err := c.store.WriteActors(c.opts.ClusterID, freshActors); err != nil {
				storeErrs = append(storeErrs, fmt.Errorf("write actors: %w", err))
			}
		}
	} else if !heavyStorageLogged.Load() {
		heavyStorageLogged.Store(true)
		logx.L().Info("heavy history storage disabled (worker_snapshot/actor_snapshot/cluster_metric/job_event)")
	}
	if len(actorEvents) > 0 {
		if err := c.store.WriteActorEvents(c.opts.ClusterID, actorEvents); err != nil {
			storeErrs = append(storeErrs, fmt.Errorf("write actor events: %w", err))
		}
	}

	clusterFresh := false
	if err := c.acquireLimiter(ctx); err == nil {
		cm, err := c.client.FetchCluster(ctx)
		c.releaseLimiter()
		if err != nil {
			if !errors.Is(err, context.Canceled) {
				c.recordErr("cluster", err)
				c.clusterStale = true
			}
		} else {
			cm.GzipSupported = c.client.LastGzipUsed()
			c.prevCluster = cm
			c.clusterStale = false
			clusterFresh = true
			if EnableHeavyHistoryStorage {
				if err := c.store.WriteCluster(c.opts.ClusterID, cm); err != nil {
					storeErrs = append(storeErrs, fmt.Errorf("write cluster: %w", err))
				}
			}
		}
	} else if !errors.Is(err, context.Canceled) {
		c.recordErr("cluster.limiter", err)
	}

	jobsFresh := false
	var jobEvents []model.JobEvent
	if err := c.acquireLimiter(ctx); err == nil {
		jobs, err := c.client.FetchJobs(ctx)
		c.releaseLimiter()
		if err != nil {
			if !errors.Is(err, context.Canceled) {
				c.recordErr("jobs", err)
				c.jobsStale = true
			}
		} else {
			c.prevJobsList = jobs
			c.jobsStale = false
			jobsFresh = true
			jobEvents = c.diffJobs(jobs)
			if err := c.store.WriteJobs(c.opts.ClusterID, jobs); err != nil {
				storeErrs = append(storeErrs, fmt.Errorf("write jobs: %w", err))
			}
			if EnableHeavyHistoryStorage && len(jobEvents) > 0 {
				if err := c.store.WriteJobEvents(c.opts.ClusterID, jobEvents); err != nil {
					storeErrs = append(storeErrs, fmt.Errorf("write job events: %w", err))
				}
			}
		}
	} else if !errors.Is(err, context.Canceled) {
		c.recordErr("jobs.limiter", err)
	}

	incomplete := len(failedNodeSet) > 0 || c.clusterStale || c.jobsStale
	storageOK := len(storeErrs) == 0

	if len(storeErrs) > 0 {
		joined := errors.Join(storeErrs...)
		logx.L().Warn("detail storage errors", "cluster", c.opts.ClusterID, "err", joined)
	}

	completeSuccess := !incomplete && storageOK

	c.mu.Lock()
	if incomplete {
		c.health.LastIncompleteTs = now
		c.health.CurrentIncomplete = true
		c.status.CurrentIncomplete = true
	} else {
		c.health.CurrentIncomplete = false
		c.status.CurrentIncomplete = false
	}
	if completeSuccess {
		c.health.LastCompleteDetailSuccessTs = now
		c.status.LastCompleteDetailTs = now
		c.status.LastError = ""
	}
	if storageOK {
		c.health.CurrentStorageError = false
	} else {
		c.health.CurrentStorageError = true
		c.health.LastStorageErrorTs = model.NowMs()
		c.health.LastStorageError = truncateErr(errors.Join(storeErrs...), 500)
	}

	c.health.TotalNodeCount = len(nodes)
	c.health.FreshNodeCount = len(freshNodeSet)
	c.health.FailedNodeCount = len(failedNodeSet)
	c.health.StaleNodeCount = 0
	c.health.MissingNodeCount = 0
	c.health.StaleWorkerCount = staleWorkerCount
	c.health.StaleActorCount = staleActorCount
	c.health.ClusterDataStale = c.clusterStale
	c.health.JobsDataStale = c.jobsStale

	var failedNodes []model.NodeCollectionState
	for _, nid := range nodes {
		if st, ok := c.nodeState[nid]; ok && (st.CurrentStale || (!st.HasCachedData && failedNodeSet[nid])) {
			failedNodes = append(failedNodes, *st)
			if st.CurrentStale {
				c.health.StaleNodeCount++
			} else if !st.HasCachedData {
				c.health.MissingNodeCount++
			}
		}
	}
	c.health.FailedNodes = failedNodes

	if c.snap == nil {
		c.snap = &Snapshot{}
	}
	if len(freshNodes) > 0 {
		nodeByID := map[string]int{}
		for i, n := range c.snap.Nodes {
			nodeByID[n.NodeID] = i
		}
		for _, fn := range freshNodes {
			if idx, ok := nodeByID[fn.NodeID]; ok {
				c.snap.Nodes[idx] = fn
			} else {
				c.snap.Nodes = append(c.snap.Nodes, fn)
			}
		}
	}
	if clusterFresh {
		c.snap.Cluster = c.prevCluster
	} else if c.clusterStale {
		c.snap.Cluster = c.prevCluster
	}
	if jobsFresh {
		c.snap.Jobs = c.prevJobsList
	} else if c.jobsStale {
		c.snap.Jobs = c.prevJobsList
	}
	c.snap.Workers = allWorkers
	c.snap.Actors = allActors
	c.snap.Health = c.health
	c.mu.Unlock()

	c.recordOK()

	detailMs := time.Since(detailStart).Milliseconds()
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)
	p := model.PerfMetrics{
		SummaryMs:       c.perf.SummaryMs,
		DetailMs:        detailMs,
		DetailMaxNodeMs: maxNodeMs,
		NodeCount:       len(nodes),
		WorkerCount:     len(allWorkers),
		ActorCount:      len(allActors),
		DetailReqs:      len(nodes) + 2,
		ProcMemBytes:    memStats.HeapAlloc,
		ProcGoroutine:   runtime.NumGoroutine(),
		Concurrency:     c.nodeConcurrency(),
		SlowNodeID:      slowNodeID,
		SlowNodeMs:      maxNodeMs,
	}
	p.Risk = assessRisk(p)
	c.mu.Lock()
	c.perf = p
	c.mu.Unlock()

	logx.L().Info("detail collected", "cluster", c.opts.ClusterID,
		"totalNodes", len(nodes), "freshNodes", len(freshNodeSet),
		"failedNodes", len(failedNodeSet), "staleNodes", len(failedNodeSet),
		"freshWorkers", len(freshWorkers), "totalDisplayedWorkers", len(allWorkers),
		"reusedWorkers", staleWorkerCount,
		"freshActors", len(freshActors), "totalDisplayedActors", len(allActors),
		"reusedActors", staleActorCount,
		"jobsFresh", jobsFresh, "clusterFresh", clusterFresh,
		"detailMs", detailMs, "maxNodeMs", maxNodeMs, "slowNodeID", slowNodeID,
		"complete", completeSuccess, "storageOK", storageOK)
	logx.Event("collection", "detail_completed",
		"cluster", c.opts.ClusterID,
		"total_nodes", len(nodes),
		"fresh_nodes", len(freshNodeSet),
		"failed_nodes", len(failedNodeSet),
		"stale_nodes", c.health.StaleNodeCount,
		"missing_nodes", c.health.MissingNodeCount,
		"fresh_workers", len(freshWorkers),
		"displayed_workers", len(allWorkers),
		"reused_workers", staleWorkerCount,
		"fresh_actors", len(freshActors),
		"displayed_actors", len(allActors),
		"reused_actors", staleActorCount,
		"cluster_fresh", clusterFresh,
		"jobs_fresh", jobsFresh,
		"jobs_count", len(c.prevJobsList),
		"storage_ok", storageOK,
		"complete", completeSuccess,
		"duration_ms", detailMs,
		"max_node_ms", maxNodeMs,
		"slow_node_id", slowNodeID)

	if fn := c.alertCallback(); fn != nil {
		c.mu.RLock()
		var ns []model.NodeMetric
		ws := append([]model.WorkerSnapshot(nil), freshWorkers...)
		if c.snap != nil {
			ns = make([]model.NodeMetric, len(c.snap.Nodes))
			copy(ns, c.snap.Nodes)
		}
		staleNodes := map[string]bool{}
		for nid, st := range c.nodeState {
			if st.CurrentStale {
				staleNodes[nid] = true
			}
		}
		c.mu.RUnlock()
		fn(c.opts.ClusterID, ns, ws, staleNodes)
	}
}

func countPartialNodes(nodes []model.NodeMetric) int {
	count := 0
	for _, node := range nodes {
		if node.IsPartial {
			count++
		}
	}
	return count
}

func (c *Collector) getOrCreateNodeState(nodeID string) *model.NodeCollectionState {
	st, ok := c.nodeState[nodeID]
	if !ok {
		st = &model.NodeCollectionState{NodeID: nodeID}
		c.nodeState[nodeID] = st
	}
	return st
}

func (c *Collector) currentNodeIDs() []string {
	if c.snap == nil {
		return nil
	}
	ids := make([]string, 0, len(c.snap.Nodes))
	for _, n := range c.snap.Nodes {
		if n.NodeID != "" {
			ids = append(ids, n.NodeID)
		}
	}
	return ids
}

func (c *Collector) diffActorsForNode(nodeID string, cur []model.ActorSnapshot) []model.ActorEvent {
	var events []model.ActorEvent
	ts := model.NowMs()

	prevMap := c.prevActorsByNode[nodeID]
	newMap := make(map[string]model.ActorSnapshot, len(cur))
	for _, a := range cur {
		newMap[a.ActorID] = a
		if prevMap != nil {
			if prev, ok := prevMap[a.ActorID]; ok {
				if prev.State != a.State {
					events = append(events, model.ActorEvent{
						Ts: ts, ActorID: a.ActorID, ActorClass: a.ActorClass,
						PrevState: prev.State, NewState: a.State, DeathCause: a.ExitDetail,
					})
				}
			}
		}
	}
	c.prevActorsByNode[nodeID] = newMap
	return events
}

func (c *Collector) diffJobs(cur []model.JobSnapshot) []model.JobEvent {
	var events []model.JobEvent
	ts := model.NowMs()
	newMap := make(map[string]model.JobSnapshot, len(cur))
	for _, j := range cur {
		newMap[j.JobID] = j
		if prev, ok := c.prevJobs[j.JobID]; ok {
			if prev.Status != j.Status {
				events = append(events, model.JobEvent{
					Ts: ts, JobID: j.JobID, PrevStatus: prev.Status,
					NewStatus: j.Status, ErrorType: j.ErrorType,
				})
			}
		}
	}
	c.prevJobs = newMap
	return events
}

func (c *Collector) refreshSnapshotNodes(nodes []model.NodeMetric) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.snap == nil {
		c.snap = &Snapshot{}
	}

	oldByID := map[string]model.NodeMetric{}
	for _, n := range c.snap.Nodes {
		oldByID[n.NodeID] = n
	}

	currentSet := map[string]bool{}
	out := make([]model.NodeMetric, 0, len(nodes))
	for _, n := range nodes {
		currentSet[n.NodeID] = true
		if old, ok := oldByID[n.NodeID]; ok {
			n.IsHead = old.IsHead
			n.GPUTotal = old.GPUTotal
			n.GPUUsed = old.GPUUsed
			if n.State == "" {
				n.State = old.State
			}
		}
		out = append(out, n)
	}

	for nid := range oldByID {
		if !currentSet[nid] {
			delete(c.workersByNode, nid)
			delete(c.actorsByNode, nid)
			delete(c.nodeState, nid)
			delete(c.prevActorsByNode, nid)
		}
	}

	filteredWorkers := c.snap.Workers[:0]
	for _, worker := range c.snap.Workers {
		if currentSet[worker.NodeID] {
			filteredWorkers = append(filteredWorkers, worker)
		}
	}
	filteredActors := c.snap.Actors[:0]
	for _, actor := range c.snap.Actors {
		if currentSet[actor.NodeID] {
			filteredActors = append(filteredActors, actor)
		}
	}
	filteredFailures := c.health.FailedNodes[:0]
	staleCount := 0
	missingCount := 0
	staleWorkers := 0
	staleActors := 0
	for _, state := range c.health.FailedNodes {
		if !currentSet[state.NodeID] {
			continue
		}
		filteredFailures = append(filteredFailures, state)
		if state.CurrentStale {
			staleCount++
			staleWorkers += state.ReusedWorkerCount
			staleActors += state.ReusedActorCount
		} else if !state.HasCachedData {
			missingCount++
		}
	}

	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.Hostname != b.Hostname {
			return a.Hostname < b.Hostname
		}
		if a.IP != b.IP {
			return a.IP < b.IP
		}
		return a.NodeID < b.NodeID
	})
	c.snap.Nodes = out
	c.snap.Workers = filteredWorkers
	c.snap.Actors = filteredActors
	c.health.TotalNodeCount = len(out)
	c.health.FailedNodes = filteredFailures
	c.health.FailedNodeCount = len(filteredFailures)
	c.health.StaleNodeCount = staleCount
	c.health.MissingNodeCount = missingCount
	c.health.StaleWorkerCount = staleWorkers
	c.health.StaleActorCount = staleActors
	c.health.CurrentIncomplete = len(filteredFailures) > 0 || c.clusterStale || c.jobsStale
	c.status.CurrentIncomplete = c.health.CurrentIncomplete
	c.snap.Health = c.health
}
