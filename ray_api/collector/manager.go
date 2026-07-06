// Package collector 多集群采集管理器。
//
// 本文件 manager.go 实现 CollectorManager：管理多个独立 Collector（每集群一个），
// 提供热增减、故障隔离、全局并发管控。
//
// 对外接口（仅以下允许被 collector 包外调用）：
//
//   - NewManager(store, cfg) *CollectorManager
//   - (m *CollectorManager) StartAll()                      // 启动所有集群采集
//   - (m *CollectorManager) StopAll()
//   - (m *CollectorManager) AddCluster(cl)                  // 热加集群
//   - (m *CollectorManager) RemoveCluster(id)               // 热删集群
//   - (m *CollectorManager) UpdateCluster(cl)               // 热改集群（停旧建新）
//   - (m *CollectorManager) Snapshot(clusterID) *Snapshot   // 某集群当前态
//   - (m *CollectorManager) Perf(clusterID) model.PerfMetrics
//   - (m *CollectorManager) Status(clusterID) model.CollectorStatus
//   - (m *CollectorManager) GlobalPerf() model.GlobalPerf   // 全局负荷
//   - (m *CollectorManager) ListClusterIDs() []string
//
// 故障隔离：每个集群独立 goroutine + 独立 ctx，互不阻塞。
// 全局并发：所有集群的 HTTP 请求共享 globalSem，避免 N 集群压垮本机。
package collector

import (
	"context"
	"runtime"
	"sync"

	"raymonitor/config"
	"raymonitor/logx"
	"raymonitor/model"
)

// CollectorManager 管理多个集群采集器。
// AlertChecker 告警检查接口（由 alert.Manager 实现，解耦 collector 与 alert 包）。
type AlertChecker interface {
	Check(clusterID, clusterName string, th config.Thresholds, nodes []model.NodeMetric, workers []model.WorkerSnapshot)
}

type CollectorManager struct {
	mu         sync.RWMutex
	collectors map[string]*collectorEntry // clusterID -> entry
	store      Store
	cfg        config.Config
	globalSem  chan struct{} // 全局并发信号量
	alerts     AlertChecker  // 告警引擎，nil 则不检查
}

// collectorEntry 单个集群的采集器及其生命周期控制。
type collectorEntry struct {
	coll    *Collector
	ctx     context.Context
	cancel  context.CancelFunc
	started bool // 是否已启动采集循环
}

// NewManager 构造管理器，并按配置创建所有集群的采集器（不启动，由 StartAll 启动）。
func NewManager(store Store, cfg config.Config) *CollectorManager {
	gc := cfg.GlobalConcurrency
	if gc <= 0 {
		gc = 30
	}
	m := &CollectorManager{
		collectors: map[string]*collectorEntry{},
		store:      store,
		cfg:        cfg,
		globalSem:  make(chan struct{}, gc),
	}
	for _, cl := range cfg.Clusters {
		if cl.ID == "" || cl.PlatformURL == "" {
			continue
		}
		coll := m.newCollectorFor(cl)
		ctx, cancel := context.WithCancel(context.Background())
		m.collectors[cl.ID] = &collectorEntry{coll: coll, ctx: ctx, cancel: cancel}
	}
	return m
}

// optsForCluster 从全局配置 + 集群配置解析出 CollectorOpts。
func (m *CollectorManager) optsForCluster(cl config.ClusterConfig) CollectorOpts {
	// 统一采样间隔：summary 和 detail 共用全局 SampleEvery
	interval := m.cfg.SampleInterval()
	return CollectorOpts{
		ClusterID:    cl.ID,
		PlatformURL:  cl.PlatformURL,
		SummaryEvery: interval,
		DetailEvery:  interval,
		TimeoutSec:   m.cfg.TimeoutSec,
		Concurrency:  m.cfg.Concurrency,
	}
}

// newCollectorFor 创建一个集群的采集器（不启动）。
func (m *CollectorManager) newCollectorFor(cl config.ClusterConfig) *Collector {
	opts := m.optsForCluster(cl)
	client := NewClient(opts)
	coll := NewCollector(client, m.store, opts)
	// 注入告警检查回调：采集后调 alerts.Check（用该集群有效阈值 + 集群名）
	if m.alerts != nil {
		th := m.cfg.ResolveThresholds(cl.ID)
		clusterName := cl.DisplayName()
		coll.SetOnAlert(func(clusterID string, nodes []model.NodeMetric, workers []model.WorkerSnapshot) {
			m.alerts.Check(clusterID, clusterName, th, nodes, workers)
		})
	}
	return coll
}

// SetAlertChecker 注入告警引擎。已创建的采集器也补上回调。
func (m *CollectorManager) SetAlertChecker(a AlertChecker) {
	m.mu.Lock()
	m.alerts = a
	m.mu.Unlock()
	m.mu.RLock()
	for _, e := range m.collectors {
		cl := m.clusterConfig(e.coll.opts.ClusterID)
		if cl != nil {
			th := m.cfg.ResolveThresholds(cl.ID)
			clusterName := cl.DisplayName()
			e.coll.SetOnAlert(func(clusterID string, nodes []model.NodeMetric, workers []model.WorkerSnapshot) {
				a.Check(clusterID, clusterName, th, nodes, workers)
			})
		}
	}
	m.mu.RUnlock()
}

// clusterConfig 取某集群配置。
func (m *CollectorManager) clusterConfig(id string) *config.ClusterConfig {
	for _, cl := range m.cfg.Clusters {
		if cl.ID == id {
			return &cl
		}
	}
	return nil
}

// StartAll 启动所有集群的采集（已启动的跳过）。
func (m *CollectorManager) StartAll() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, e := range m.collectors {
		if !e.started {
			e.started = true
			go e.coll.Start(e.ctx)
		}
	}
}

// AddCluster 热加集群：创建采集器，started 状态继承旧同 ID 的 collector。
// 新集群（map 里没有）默认 started=false，由用户显式 Start。
// 该行为确保保存配置后不会自动启动——这是 UX 需求（用户已运行的就保持运行，
// 没运行的不自动开始；和旧实现"全部自动启"区分开）。
func (m *CollectorManager) AddCluster(cl config.ClusterConfig) {
	m.mu.Lock()
	wasStarted := false
	if old, ok := m.collectors[cl.ID]; ok {
		wasStarted = old.started
		old.cancel()
	}
	m.mu.Unlock()
	m.addClusterWithState(cl, wasStarted)
}

// addClusterWithState 私有：按指定 started 状态创建/重建 collector。
// started=true 时同步触发 Start goroutine。配置变更（SaveConfig）和 UpdateCluster
// 走这条路径，started 状态由调用方按用户意图决定。
func (m *CollectorManager) addClusterWithState(cl config.ClusterConfig, started bool) {
	coll := m.newCollectorFor(cl)
	ctx, cancel := context.WithCancel(context.Background())
	m.mu.Lock()
	m.collectors[cl.ID] = &collectorEntry{coll: coll, ctx: ctx, cancel: cancel, started: started}
	m.mu.Unlock()
	if started {
		go coll.Start(ctx)
	}
	logx.L().Info("cluster added", "id", cl.ID, "url", cl.PlatformURL, "started", started)
}

// RemoveCluster 热删集群：停止并移除。
func (m *CollectorManager) RemoveCluster(id string) {
	m.mu.Lock()
	e, ok := m.collectors[id]
	if ok {
		e.cancel()
		delete(m.collectors, id)
	}
	m.mu.Unlock()
	if ok {
		logx.L().Info("cluster removed", "id", id)
	}
}

// UpdateCluster 热改集群：停旧的，建新的（URL/间隔/阈值变更都走这个）。
// started 状态继承旧 collector（用户已运行的就保持运行；没运行的不自动开始）。
func (m *CollectorManager) UpdateCluster(cl config.ClusterConfig) {
	m.mu.Lock()
	wasStarted := false
	if old, ok := m.collectors[cl.ID]; ok {
		wasStarted = old.started
	}
	m.mu.Unlock()
	m.RemoveCluster(cl.ID)
	m.addClusterWithState(cl, wasStarted)
}

// StopAll 停止所有集群。
// StopAll 停止所有集群（不删除，可再 StartAll）。
func (m *CollectorManager) StopAll() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, e := range m.collectors {
		e.cancel()
		e.started = false
		ctx, cancel := context.WithCancel(context.Background())
		e.ctx = ctx
		e.cancel = cancel
	}
}

// StartCluster 启动单个集群（若存在且未启动）。
func (m *CollectorManager) StartCluster(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e, ok := m.collectors[id]; ok && !e.started {
		e.started = true
		go e.coll.Start(e.ctx)
	}
}

// StopCluster 停止单个集群。
func (m *CollectorManager) StopCluster(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e, ok := m.collectors[id]; ok {
		e.cancel()
		e.started = false
		ctx, cancel := context.WithCancel(context.Background())
		e.ctx = ctx
		e.cancel = cancel
	}
}

// ReloadAll 用新配置重建所有采集器（采样间隔等全局项变更时调用）。
// 重建时按 cluster ID 继承旧 started 状态：用户已运行的就保持运行，
// 没运行的不自动开始。新集群（不在旧列表里）默认停止。
func (m *CollectorManager) ReloadAll(cfg config.Config) {
	m.mu.Lock()
	// 快照旧 started 状态（按 cluster ID）
	startedMap := map[string]bool{}
	for id, e := range m.collectors {
		startedMap[id] = e.started
	}
	for _, e := range m.collectors {
		e.cancel()
	}
	m.collectors = map[string]*collectorEntry{}
	m.cfg = cfg
	for _, cl := range cfg.Clusters {
		if cl.ID == "" || cl.PlatformURL == "" {
			continue
		}
		coll := m.newCollectorFor(cl)
		ctx, cancel := context.WithCancel(context.Background())
		started := startedMap[cl.ID] // 继承旧状态，新集群=false
		m.collectors[cl.ID] = &collectorEntry{coll: coll, ctx: ctx, cancel: cancel, started: started}
		if started {
			go coll.Start(ctx)
		}
	}
	m.mu.Unlock()
	logx.L().Info("all collectors reloaded", "count", len(cfg.Clusters))
}

// SyncClusters 同步集群列表变更：对比新旧列表，增删改对应集群。
func (m *CollectorManager) SyncClusters(old, newCl []config.ClusterConfig) {
	oldMap := map[string]config.ClusterConfig{}
	for _, c := range old {
		oldMap[c.ID] = c
	}
	newMap := map[string]config.ClusterConfig{}
	for _, c := range newCl {
		newMap[c.ID] = c
	}
	for id := range oldMap {
		if _, ok := newMap[id]; !ok {
			m.RemoveCluster(id)
		}
	}
	for _, c := range newCl {
		if c.ID == "" || c.PlatformURL == "" {
			continue
		}
		if oldC, ok := oldMap[c.ID]; ok {
			// 集群只有 URL，URL 变了才重建
			if oldC.PlatformURL != c.PlatformURL {
				m.UpdateCluster(c)
			}
		} else {
			m.AddCluster(c)
		}
	}
}

// ListClusterIDs 返回所有集群 ID。
func (m *CollectorManager) ListClusterIDs() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	ids := make([]string, 0, len(m.collectors))
	for id := range m.collectors {
		ids = append(ids, id)
	}
	return ids
}

// entry 安全获取某集群 entry。
func (m *CollectorManager) entry(id string) *collectorEntry {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.collectors[id]
}

// Snapshot 某集群当前态快照。
func (m *CollectorManager) Snapshot(clusterID string) *Snapshot {
	e := m.entry(clusterID)
	if e == nil {
		return nil
	}
	return e.coll.Snapshot()
}

// Perf 某集群性能评估。
func (m *CollectorManager) Perf(clusterID string) model.PerfMetrics {
	e := m.entry(clusterID)
	if e == nil {
		return model.PerfMetrics{}
	}
	return e.coll.Perf()
}

// Status 某集群采集状态。
func (m *CollectorManager) Status(clusterID string) model.CollectorStatus {
	e := m.entry(clusterID)
	if e == nil {
		return model.CollectorStatus{}
	}
	return e.coll.Status()
}

// GlobalPerf 全局负荷评估：汇总所有集群。
func (m *CollectorManager) GlobalPerf() model.GlobalPerf {
	m.mu.RLock()
	defer m.mu.RUnlock()
	gp := model.GlobalPerf{
		ClusterCount:     len(m.collectors),
		GlobalConcurrency: cap(m.globalSem),
		UpdatedAt:        model.NowMs(),
	}
	for _, e := range m.collectors {
		p := e.coll.Perf()
		gp.TotalDetailReqs += p.DetailReqs
		gp.TotalNodes += p.NodeCount
		gp.TotalWorkers += p.WorkerCount
		gp.TotalActors += p.ActorCount
		if p.DetailMs > gp.MaxDetailMs {
			gp.MaxDetailMs = p.DetailMs
		}
		st := e.coll.Status()
		if st.Running {
			gp.RunningClusters++
		}
		if st.ErrCount > 0 {
			gp.ClustersWithError++
		}
	}
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	gp.ProcMemBytes = ms.HeapAlloc
	gp.ProcGoroutine = runtime.NumGoroutine()
	return gp
}

// 占位：runtime/time 在 GlobalPerf 用到，确保 import 被引用。
