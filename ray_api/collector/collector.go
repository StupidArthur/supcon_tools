package collector

import (
	"context"
	"errors"
	"fmt"
	"runtime"
	"sort"
	"sync"
	"time"

	"raymonitor/logx"
	"raymonitor/model"
)

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
	PlatformURL  string
	Cookie       string
	SummaryEvery int
	DetailEvery  int
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

func (c *Collector) SetLimiter(l RequestLimiter) {
	c.limiter = l
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

func (c *Collector) Perf() model.PerfMetrics {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.perf
}

func (c *Collector) concurrency() int {
	if c.opts.Concurrency <= 0 {
		return 10
	}
	return c.opts.Concurrency
}

func assessRisk(p model.PerfMetrics, summaryEvery, detailEvery int) string {
	period := summaryEvery
	if detailEvery < period {
		period = detailEvery
	}
	periodMs := int64(period) * 1000
	if p.DetailMs > periodMs*80/100 && p.DetailMs > 0 {
		return "danger"
	}
	if p.DetailMaxNodeMs > 3000 || p.ProcMemBytes > 500*1024*1024 {
		return "warn"
	}
	return "ok"
}

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
	logx.L().Info("collector started", "cluster", c.opts.ClusterID, "summary", summaryEvery, "detail", detailEvery)

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
		logx.L().Info("collector stopped", "cluster", c.opts.ClusterID)
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

	c.mu.Lock()
	c.perf.SummaryMs = summaryMs
	c.perf.NodeCount = len(nodes)
	c.perf.Risk = assessRisk(c.perf, c.opts.SummaryEvery, c.opts.DetailEvery)
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
	detailStart := time.Now()
	now := model.NowMs()

	c.mu.RLock()
	nodes := c.currentNodeIDs()
	c.mu.RUnlock()

	if len(nodes) == 0 {
		logx.L().Warn("detail skipped: no nodes in snapshot", "cluster", c.opts.ClusterID)
		return
	}

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
	sem := make(chan struct{}, c.concurrency())
	var wg sync.WaitGroup

	for i, nid := range nodes {
		wg.Add(1)
		go func(idx int, id string) {
			defer wg.Done()

			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				results[idx] = nodeResult{nodeID: id, ok: false, err: ctx.Err()}
				return
			}
			defer func() { <-sem }()

			if err := c.acquireLimiter(ctx); err != nil {
				results[idx] = nodeResult{nodeID: id, ok: false, err: err}
				return
			}
			ns := time.Now()
			d, err := c.client.FetchNodeDetail(ctx, id)
			ms := time.Since(ns).Milliseconds()
			c.releaseLimiter()

			if err != nil {
				results[idx] = nodeResult{nodeID: id, ok: false, err: err, ms: ms}
				return
			}
			results[idx] = nodeResult{nodeID: id, workers: d.Workers, actors: d.Actors, node: d.Node, ok: true, ms: ms}
		}(i, nid)
	}
	wg.Wait()

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

			if err := c.store.WriteNodeMetrics(c.opts.ClusterID, []model.NodeMetric{r.node}); err != nil {
				storeErrs = append(storeErrs, fmt.Errorf("write node metrics node=%s: %w", r.nodeID, err))
			}

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
			if err := c.store.WriteCluster(c.opts.ClusterID, cm); err != nil {
				storeErrs = append(storeErrs, fmt.Errorf("write cluster: %w", err))
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
			if len(jobEvents) > 0 {
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
		Concurrency:     c.concurrency(),
		SlowNodeID:      slowNodeID,
		SlowNodeMs:      maxNodeMs,
	}
	p.Risk = assessRisk(p, c.opts.SummaryEvery, c.opts.DetailEvery)
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
