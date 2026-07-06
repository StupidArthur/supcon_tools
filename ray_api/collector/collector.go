// Package collector 采集调度器。
//
// 本文件 collector.go 实现双层定时采集 + 状态变迁事件生成。
// 对外接口（仅以下允许被 collector 包外调用）：
//
//   - NewCollector(client, store, cfg) *Collector
//   - (c *Collector) Start(ctx)   // 启动采集循环，ctx 取消即停止（A 模式：关窗口停）
//   - (c *Collector) Status() CollectorStatus
//   - (c *Collector) Snapshot() *Snapshot   // 当前态快照（供前端）
//
// 双层频率（设计文档 §2.2）：
//   - summary 高频（15s）：节点硬件
//   - detail/cluster/jobs 低频（60s）：workers/actors/调度资源/作业
//
// 事件生成（设计文档 §4 路线2）：
//   - 内存保留上一轮 actor/job 快照，状态变化时生成 event 交 store 落库。
//   - 两次采集间状态变两次会漏中间态——采样监控固有局限，标准未要求捕捉。
package collector

import (
	"context"
	"runtime"
	"sync"
	"time"

	"raymonitor/logx"
	"raymonitor/model"
)

// Store 存储层接口。采集器只依赖此接口，不直接依赖 storage 实现，便于测试解耦。
type Store interface {
	WriteNodeMetrics(clusterID string, ns []model.NodeMetric) error
	WriteWorkers(clusterID string, ws []model.WorkerSnapshot) error
	WriteActors(clusterID string, as []model.ActorSnapshot) error
	WriteJobs(clusterID string, js []model.JobSnapshot) error
	WriteCluster(clusterID string, c model.ClusterMetric) error
	WriteActorEvents(clusterID string, es []model.ActorEvent) error
	WriteJobEvents(clusterID string, es []model.JobEvent) error
}

// Snapshot 当前态快照，采集后推送给前端。
type Snapshot struct {
	Cluster model.ClusterMetric    `json:"cluster"`
	Nodes   []model.NodeMetric     `json:"nodes"`
	Workers []model.WorkerSnapshot `json:"workers"`
	Actors  []model.ActorSnapshot  `json:"actors"`
	Jobs    []model.JobSnapshot    `json:"jobs"`
}

// CollectorOpts 采集器运行所需配置，由 Manager 从 config.Config + ClusterConfig 解析得出。
// 解耦 collector 与全局 config 结构：collector 只依赖自己需要的字段。
type CollectorOpts struct {
	ClusterID    string
	PlatformURL  string
	Cookie       string
	SummaryEvery int
	DetailEvery  int
	TimeoutSec   int
	Concurrency  int
}

// Collector 采集调度器。
type Collector struct {
	client *Client
	store  Store
	opts   CollectorOpts

	mu          sync.RWMutex
	status      model.CollectorStatus
	snap        *Snapshot
	perf        model.PerfMetrics // 采集器自身性能评估
	prevActors  map[string]model.ActorSnapshot // 上一轮 actor 快照，用于 diff 事件
	prevJobs    map[string]model.JobSnapshot   // 上一轮 job 快照

	// onAlert: 采集后回调，供告警引擎检查阈值。注入式，解耦 collector 与 alert 包。
	// 参数：clusterID, nodes(当前快照节点), workers(当前快照worker)
	onAlert func(clusterID string, nodes []model.NodeMetric, workers []model.WorkerSnapshot)
}

// SetOnAlert 注入告警检查回调。
func (c *Collector) SetOnAlert(fn func(clusterID string, nodes []model.NodeMetric, workers []model.WorkerSnapshot)) {
	c.onAlert = fn
}

// NewCollector 构造采集器。
func NewCollector(client *Client, store Store, opts CollectorOpts) *Collector {
	return &Collector{
		client: client, store: store, opts: opts,
		prevActors: map[string]model.ActorSnapshot{},
		prevJobs:   map[string]model.JobSnapshot{},
	}
}

// Status 返回采集器状态（线程安全）。
func (c *Collector) Status() model.CollectorStatus {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.status
}

// Snapshot 返回当前态快照副本（线程安全）。尚未采集时返回 nil。
func (c *Collector) Snapshot() *Snapshot {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.snap == nil {
		return nil
	}
	s := *c.snap
	return &s
}

// Perf 返回采集器自身性能评估（线程安全）。
func (c *Collector) Perf() model.PerfMetrics {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.perf
}

// concurrency 并发上限，配置非正则兜底 10。
func (c *Collector) concurrency() int {
	if c.opts.Concurrency <= 0 {
		return 10
	}
	return c.opts.Concurrency
}

// refreshPerf 更新性能指标（锁内）。
func (c *Collector) refreshPerf(p model.PerfMetrics) {
	c.mu.Lock()
	c.perf = p
	c.mu.Unlock()
}

// assessRisk 根据性能指标自评风险等级，供前端提示是否需改架构。
// 判断依据：detail 耗时接近采集周期、单节点请求过慢、内存过高。
func assessRisk(p model.PerfMetrics, summaryEvery, detailEvery int) string {
	period := summaryEvery
	if detailEvery < period {
		period = detailEvery
	}
	periodMs := int64(period) * 1000
	// detail 耗时超过周期的 80% → 危险，可能赶不上下一轮
	if p.DetailMs > periodMs*80/100 && p.DetailMs > 0 {
		return "danger"
	}
	// 单节点请求超过 3 秒或内存超 500MB → 警告
	if p.DetailMaxNodeMs > 3000 || p.ProcMemBytes > 500*1024*1024 {
		return "warn"
	}
	return "ok"
}

// Start 启动双层采集循环，阻塞至 ctx 取消。
// 采集是无状态轮询，重启即恢复；已存数据在 SQLite 天然持久（runtime-safety 崩溃恢复）。
// 间隔为非正值时按默认值兜底，避免 NewTicker(0) panic。
func (c *Collector) Start(ctx context.Context) {
	summaryEvery := c.opts.SummaryEvery
	detailEvery := c.opts.DetailEvery
	if summaryEvery <= 0 {
		summaryEvery = 15
	}
	if detailEvery <= 0 {
		detailEvery = 60
	}
	c.mu.Lock()
	c.status.Running = true
	c.mu.Unlock()
	logx.L().Info("collector started", "summary", summaryEvery, "detail", detailEvery)

	// 首次立即采一次，避免启动后空白等待
	c.collectSummary(ctx)
	c.collectDetail(ctx)

	summaryTick := time.NewTicker(time.Duration(summaryEvery) * time.Second)
	detailTick := time.NewTicker(time.Duration(detailEvery) * time.Second)
	defer func() {
		summaryTick.Stop()
		detailTick.Stop()
		c.mu.Lock()
		c.status.Running = false
		c.mu.Unlock()
		logx.L().Info("collector stopped")
	}()

	for {
		select {
		case <-ctx.Done():
			return
		case <-summaryTick.C:
			c.collectSummary(ctx)
		case <-detailTick.C:
			c.collectDetail(ctx)
		}
	}
}

// recordErr 记录采集失败：错误计数 +1，更新最近错误，写日志。
func (c *Collector) recordErr(stage string, err error) {
	c.mu.Lock()
	c.status.ErrCount++
	c.status.LastError = err.Error()
	c.mu.Unlock()
	logx.L().Warn("collect failed", "stage", stage, "err", err)
}

// recordOK 记录采集成功。
func (c *Collector) recordOK() {
	c.mu.Lock()
	c.status.LastSuccessTs = model.NowMs()
	c.status.LastError = ""
	c.mu.Unlock()
}

// collectSummary 高频：节点硬件。
func (c *Collector) collectSummary(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}
	start := time.Now()
	nodes, err := c.client.FetchNodes()
	if err != nil {
		// 详细记录失败原因：URL/HTTP码/解析错，便于生产环境排查
		logx.L().Warn("summary collect failed", "url", c.client.baseURL, "nodes", len(nodes), "err", err)
		c.recordErr("summary", err)
		return
	}
	// 增量持久化：每批一事务，遵循 runtime-safety
	if err := c.store.WriteNodeMetrics(c.opts.ClusterID, nodes); err != nil {
		logx.L().Warn("summary store failed", "err", err)
		c.recordErr("summary.store", err)
		return
	}
	summaryMs := time.Since(start).Milliseconds()
	logx.L().Info("summary collected", "nodes", len(nodes), "ms", summaryMs)
	c.recordOK()
	c.refreshSnapshotNodes(nodes)
	// 更新性能指标：summary 耗时与节点数
	c.mu.Lock()
	c.perf.SummaryMs = summaryMs
	c.perf.NodeCount = len(nodes)
	c.perf.Risk = assessRisk(c.perf, c.opts.SummaryEvery, c.opts.DetailEvery)
	c.mu.Unlock()

	// 告警检查：节点指标（CPU/MEM/GPU）。workers 用上一轮 detail 的（可能为空）。
	if c.onAlert != nil {
		c.mu.RLock()
		ws := []model.WorkerSnapshot{}
		if c.snap != nil {
			ws = c.snap.Workers
		}
		c.mu.RUnlock()
		c.onAlert(c.opts.ClusterID, nodes, ws)
	}
}

// collectDetail 低频：节点详情 + 集群 + 作业，并生成状态变迁事件。
// 节点详情采用限流并发（信号量上限 = cfg.Concurrency），全部完成后一次性更新快照，
// 保持"攒齐一起提交"语义。cluster/jobs 单独请求。
func (c *Collector) collectDetail(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}
	detailStart := time.Now()
	// 先拿当前节点列表（复用 snapshot 中已有的，避免重复请求 summary）
	c.mu.RLock()
	nodes := c.currentNodeIDs()
	c.mu.RUnlock()
	if len(nodes) == 0 {
		// summary 尚未成功，detail 无节点可查。记录原因，避免误以为 detail 没跑。
		logx.L().Warn("detail skipped: no nodes in snapshot (summary may have failed)")
	}

	// 限流并发拉取各节点详情。结果按节点顺序聚合，避免乱序。
	type nodeResult struct {
		nodeID  string // 即使失败也记录，便于定位慢/失败节点
		workers []model.WorkerSnapshot
		actors  []model.ActorSnapshot
		node    model.NodeMetric
		ok      bool
		ms      int64 // 该节点请求耗时，用于找瓶颈
	}
	results := make([]nodeResult, len(nodes))
	sem := make(chan struct{}, c.concurrency())
	var wg sync.WaitGroup
	nodesStart := time.Now()
	for i, nid := range nodes {
		wg.Add(1)
		sem <- struct{}{} // 占槽，满则等待
		go func(idx int, id string) {
			defer wg.Done()
			defer func() { <-sem }() // 释放槽
			ns := time.Now()
			d, err := c.client.FetchNodeDetail(id)
			ms := time.Since(ns).Milliseconds()
			if err != nil {
				// 单节点失败不中断整体采集
				logx.L().Warn("fetch node detail failed", "node", id, "err", err, "ms", ms)
				results[idx] = nodeResult{nodeID: id, ok: false, ms: ms}
				return
			}
			results[idx] = nodeResult{nodeID: id, workers: d.Workers, actors: d.Actors, node: d.Node, ok: true, ms: ms}
		}(i, nid)
	}
	wg.Wait()
	detailNodesMs := time.Since(nodesStart).Milliseconds()

	// 聚合结果（保持节点顺序），同时定位最慢节点
	var allWorkers []model.WorkerSnapshot
	var allActors []model.ActorSnapshot
	var maxNodeMs int64
	var slowNodeID, slowNodeHost string
	for _, r := range results {
		if r.ms > maxNodeMs {
			maxNodeMs = r.ms
			slowNodeID = r.nodeID
			slowNodeHost = r.node.Hostname
			if slowNodeHost == "" {
				slowNodeHost = r.node.IP
			}
		}
		if !r.ok {
			continue
		}
		allWorkers = append(allWorkers, r.workers...)
		allActors = append(allActors, r.actors...)
		// detail 里的节点资源比 summary 更权威（含 GPU/state），顺便写一份节点指标
		_ = c.store.WriteNodeMetrics(c.opts.ClusterID, []model.NodeMetric{r.node})
		c.refreshSnapshotNode(r.node)
	}

	cm, err := c.client.FetchCluster()
	if err != nil {
		logx.L().Warn("cluster collect failed", "err", err)
		c.recordErr("cluster", err)
	} else {
		// 记录 dashboard 是否返回 gzip 压缩。FetchCluster 是 detail tick 里唯一每轮
		// 都打的请求，用它观测最稳定。首页会基于此字段判断带宽优化是否对该集群生效。
		cm.GzipSupported = c.client.LastGzipUsed()
		_ = c.store.WriteCluster(c.opts.ClusterID, cm)
	}

	jobs, err := c.client.FetchJobs()
	if err != nil {
		logx.L().Warn("jobs collect failed", "err", err)
		c.recordErr("jobs", err)
		jobs = nil
	}

	// 落库 workers/actors/jobs
	_ = c.store.WriteWorkers(c.opts.ClusterID, allWorkers)
	_ = c.store.WriteActors(c.opts.ClusterID, allActors)
	_ = c.store.WriteJobs(c.opts.ClusterID, jobs)

	// 生成状态变迁事件（diff 上一轮）
	actorEvents := c.diffActors(allActors)
	jobEvents := c.diffJobs(jobs)
	if len(actorEvents) > 0 {
		_ = c.store.WriteActorEvents(c.opts.ClusterID, actorEvents)
	}
	if len(jobEvents) > 0 {
		_ = c.store.WriteJobEvents(c.opts.ClusterID, jobEvents)
	}

	c.recordOK()
	c.refreshSnapshotDetail(cm, allWorkers, allActors, jobs)

	// 更新性能指标
	detailMs := time.Since(detailStart).Milliseconds()
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)
	p := model.PerfMetrics{
		SummaryMs:       c.perf.SummaryMs, // 保留最近 summary 耗时
		DetailMs:        detailMs,
		DetailNodesMs:   detailNodesMs,
		DetailMaxNodeMs: maxNodeMs,
		NodeCount:       len(nodes),
		WorkerCount:     len(allWorkers),
		ActorCount:      len(allActors),
		DetailReqs:      len(nodes) + 2, // 节点数 + cluster + jobs
		ProcMemBytes:    memStats.HeapAlloc,
		ProcGoroutine:   runtime.NumGoroutine(),
		Concurrency:     c.concurrency(),
		SlowNodeID:      slowNodeID,
		SlowNodeHost:    slowNodeHost,
		SlowNodeMs:      maxNodeMs,
	}
	p.Risk = assessRisk(p, c.opts.SummaryEvery, c.opts.DetailEvery)
	c.refreshPerf(p)
	logx.L().Info("detail collected", "workers", len(allWorkers), "actors", len(allActors), "jobs", len(jobs),
		"detailMs", detailMs, "nodesMs", detailNodesMs, "maxNodeMs", maxNodeMs, "memMB", memStats.HeapAlloc/1024/1024)

	// 告警检查：用最新节点（snapshot）+ 本轮 workers
	if c.onAlert != nil {
		c.mu.RLock()
		ns := []model.NodeMetric{}
		if c.snap != nil {
			ns = c.snap.Nodes
		}
		c.mu.RUnlock()
		c.onAlert(c.opts.ClusterID, ns, allWorkers)
	}
}

// currentNodeIDs 从当前 snapshot 取节点 id 列表。
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

// diffActors 对比上一轮，生成状态变迁事件。仅状态变化才记录。
func (c *Collector) diffActors(cur []model.ActorSnapshot) []model.ActorEvent {
	var events []model.ActorEvent
	ts := model.NowMs()
	newMap := make(map[string]model.ActorSnapshot, len(cur))
	for _, a := range cur {
		newMap[a.ActorID] = a
		if prev, ok := c.prevActors[a.ActorID]; ok {
			if prev.State != a.State {
				events = append(events, model.ActorEvent{
					Ts: ts, ActorID: a.ActorID, ActorClass: a.ActorClass,
					PrevState: prev.State, NewState: a.State, DeathCause: a.ExitDetail,
				})
			}
		}
	}
	c.prevActors = newMap
	return events
}

// diffJobs 对比上一轮，生成状态变迁事件。
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

// ---- snapshot 更新（细粒度锁内更新，避免高频 summary 与低频 detail 互相覆盖丢失）----

func (c *Collector) refreshSnapshotNodes(nodes []model.NodeMetric) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.snap == nil {
		c.snap = &Snapshot{}
	}
	// 按 NodeID 合并：保留 detail 写入的 isHead/state/gpuTotal（detail 更权威），summary 只更新硬件
	byID := map[string]model.NodeMetric{}
	for _, n := range c.snap.Nodes {
		byID[n.NodeID] = n
	}
	for _, n := range nodes {
		if exist, ok := byID[n.NodeID]; ok {
			// summary 刷新硬件，保留 detail 的权威字段
			exist.CPU, exist.MemTotal, exist.MemUsed = n.CPU, n.MemTotal, n.MemUsed
			exist.IsPartial = n.IsPartial
			if exist.Hostname == "" {
				exist.Hostname = n.Hostname
			}
			byID[n.NodeID] = exist
		} else {
			byID[n.NodeID] = n
		}
	}
	out := make([]model.NodeMetric, 0, len(byID))
	for _, n := range byID {
		out = append(out, n)
	}
	c.snap.Nodes = out
}

func (c *Collector) refreshSnapshotNode(n model.NodeMetric) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.snap == nil {
		c.snap = &Snapshot{}
	}
	for i, ex := range c.snap.Nodes {
		if ex.NodeID == n.NodeID {
			c.snap.Nodes[i] = n // detail 整体覆盖该节点（含 isHead/state/gpuTotal）
			return
		}
	}
	c.snap.Nodes = append(c.snap.Nodes, n)
}

func (c *Collector) refreshSnapshotDetail(cm model.ClusterMetric, workers []model.WorkerSnapshot, actors []model.ActorSnapshot, jobs []model.JobSnapshot) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.snap == nil {
		c.snap = &Snapshot{}
	}
	c.snap.Cluster = cm
	c.snap.Workers = workers
	c.snap.Actors = actors
	c.snap.Jobs = jobs
}
