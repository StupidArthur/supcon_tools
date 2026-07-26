package collector

import (
	"context"
	"runtime"
	"sync"

	"raymonitor/config"
	"raymonitor/logx"
	"raymonitor/model"
)

// DefaultConcurrency 是单集群节点详情 fan-out 的并发上限。未对用户暴露，需要调整时改这里。
const DefaultConcurrency = 50

// DefaultGlobalConcurrency 是所有集群 HTTP 请求共享的并发上限。未对用户暴露，需要调整时改这里。
const DefaultGlobalConcurrency = 100

type AlertChecker interface {
	Check(clusterID, clusterName string, th config.Thresholds, nodes []model.NodeMetric, workers []model.WorkerSnapshot, staleNodes map[string]bool)
}

type semaphoreLimiter struct {
	ch chan struct{}
}

func newSemaphoreLimiter(capacity int) *semaphoreLimiter {
	if capacity <= 0 {
		capacity = 30
	}
	return &semaphoreLimiter{ch: make(chan struct{}, capacity)}
}

func (s *semaphoreLimiter) Acquire(ctx context.Context) error {
	select {
	case s.ch <- struct{}{}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (s *semaphoreLimiter) Release() {
	<-s.ch
}

func (s *semaphoreLimiter) Capacity() int {
	return cap(s.ch)
}

type CollectorManager struct {
	mu         sync.RWMutex
	collectors map[string]*collectorEntry
	store      Store
	cfg        config.Config
	limiter    *semaphoreLimiter
	alerts     AlertChecker
}

type collectorEntry struct {
	coll    *Collector
	ctx     context.Context
	cancel  context.CancelFunc
	started bool
}

func NewManager(store Store, cfg config.Config) *CollectorManager {
	m := &CollectorManager{
		collectors: map[string]*collectorEntry{},
		store:      store,
		cfg:        cfg,
		limiter:    newSemaphoreLimiter(DefaultGlobalConcurrency),
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

func (m *CollectorManager) optsForCluster(cl config.ClusterConfig) CollectorOpts {
	interval := m.cfg.SampleInterval()
	return CollectorOpts{
		ClusterID:    cl.ID,
		PlatformURL:  cl.PlatformURL,
		SummaryEvery: interval,
		DetailEvery:  interval,
		TimeoutSec:   DefaultTimeoutSec,
		Concurrency:  DefaultConcurrency,
	}
}

func (m *CollectorManager) newCollectorFor(cl config.ClusterConfig) *Collector {
	opts := m.optsForCluster(cl)
	client := NewClient(opts)
	coll := NewCollector(client, m.store, opts)
	coll.SetLimiter(m.limiter)
	coll.SetOnAlert(m.dispatchAlert)
	return coll
}

func (m *CollectorManager) dispatchAlert(clusterID string, nodes []model.NodeMetric, workers []model.WorkerSnapshot, staleNodes map[string]bool) {
	m.mu.RLock()
	checker := m.alerts
	thresholds := m.cfg.ResolveThresholds(clusterID)
	clusterName := clusterID
	for _, cl := range m.cfg.Clusters {
		if cl.ID == clusterID {
			clusterName = cl.DisplayName()
			break
		}
	}
	m.mu.RUnlock()

	if checker != nil {
		checker.Check(clusterID, clusterName, thresholds, nodes, workers, staleNodes)
	}
}

func (m *CollectorManager) SetAlertChecker(a AlertChecker) {
	m.mu.Lock()
	m.alerts = a
	m.mu.Unlock()
}

func (m *CollectorManager) clusterConfig(id string) *config.ClusterConfig {
	for _, cl := range m.cfg.Clusters {
		if cl.ID == id {
			return &cl
		}
	}
	return nil
}

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

func (m *CollectorManager) StartCluster(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e, ok := m.collectors[id]; ok && !e.started {
		e.started = true
		go e.coll.Start(e.ctx)
	}
}

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

func (m *CollectorManager) ReloadAll(cfg config.Config) {
	m.mu.Lock()
	startedMap := map[string]bool{}
	for id, e := range m.collectors {
		startedMap[id] = e.started
	}
	for _, e := range m.collectors {
		e.cancel()
	}

	m.limiter = newSemaphoreLimiter(DefaultGlobalConcurrency)

	m.collectors = map[string]*collectorEntry{}
	m.cfg = cfg
	for _, cl := range cfg.Clusters {
		if cl.ID == "" || cl.PlatformURL == "" {
			continue
		}
		coll := m.newCollectorFor(cl)
		ctx, cancel := context.WithCancel(context.Background())
		started := startedMap[cl.ID]
		m.collectors[cl.ID] = &collectorEntry{coll: coll, ctx: ctx, cancel: cancel, started: started}
		if started {
			go coll.Start(ctx)
		}
	}
	m.mu.Unlock()
	logx.L().Info("all collectors reloaded", "count", len(cfg.Clusters))
}

// ApplyConfig updates the manager's complete configuration. Only changes to
// user-facing config fields (clusters, sample interval, thresholds) are acted
// on here; concurrency / timeout / etc. are compile-time constants so they
// never trigger a rebuild.
func (m *CollectorManager) ApplyConfig(cfg config.Config) {
	m.mu.Lock()
	old := m.cfg
	rebuildAll := old.SampleEvery != cfg.SampleEvery

	if rebuildAll {
		started := make(map[string]bool, len(m.collectors))
		for id, entry := range m.collectors {
			started[id] = entry.started
			entry.cancel()
		}
		m.cfg = cfg
		m.limiter = newSemaphoreLimiter(DefaultGlobalConcurrency)
		m.collectors = make(map[string]*collectorEntry, len(cfg.Clusters))
		for _, cl := range cfg.Clusters {
			if cl.ID == "" || cl.PlatformURL == "" {
				continue
			}
			coll := m.newCollectorFor(cl)
			ctx, cancel := context.WithCancel(context.Background())
			entry := &collectorEntry{coll: coll, ctx: ctx, cancel: cancel, started: started[cl.ID]}
			m.collectors[cl.ID] = entry
			if entry.started {
				go coll.Start(ctx)
			}
		}
		m.mu.Unlock()
		logx.L().Info("all collectors reloaded", "count", len(cfg.Clusters))
		return
	}

	oldClusters := make(map[string]config.ClusterConfig, len(old.Clusters))
	for _, cl := range old.Clusters {
		oldClusters[cl.ID] = cl
	}
	newClusters := make(map[string]config.ClusterConfig, len(cfg.Clusters))
	for _, cl := range cfg.Clusters {
		newClusters[cl.ID] = cl
	}

	m.cfg = cfg
	for id, entry := range m.collectors {
		next, exists := newClusters[id]
		previous := oldClusters[id]
		if !exists || next.ID == "" || next.PlatformURL == "" {
			entry.cancel()
			delete(m.collectors, id)
			continue
		}
		if previous.PlatformURL != next.PlatformURL {
			wasStarted := entry.started
			entry.cancel()
			coll := m.newCollectorFor(next)
			ctx, cancel := context.WithCancel(context.Background())
			m.collectors[id] = &collectorEntry{coll: coll, ctx: ctx, cancel: cancel, started: wasStarted}
			if wasStarted {
				go coll.Start(ctx)
			}
		}
	}
	for _, cl := range cfg.Clusters {
		if cl.ID == "" || cl.PlatformURL == "" {
			continue
		}
		if _, exists := m.collectors[cl.ID]; exists {
			continue
		}
		coll := m.newCollectorFor(cl)
		ctx, cancel := context.WithCancel(context.Background())
		m.collectors[cl.ID] = &collectorEntry{coll: coll, ctx: ctx, cancel: cancel}
	}
	m.mu.Unlock()
}

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
			if oldC.PlatformURL != c.PlatformURL {
				m.UpdateCluster(c)
			}
		} else {
			m.AddCluster(c)
		}
	}
}

func (m *CollectorManager) ListClusterIDs() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	ids := make([]string, 0, len(m.collectors))
	for id := range m.collectors {
		ids = append(ids, id)
	}
	return ids
}

func (m *CollectorManager) entry(id string) *collectorEntry {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.collectors[id]
}

func (m *CollectorManager) Snapshot(clusterID string) *Snapshot {
	e := m.entry(clusterID)
	if e == nil {
		return nil
	}
	return e.coll.Snapshot()
}

func (m *CollectorManager) Perf(clusterID string) model.PerfMetrics {
	e := m.entry(clusterID)
	if e == nil {
		return model.PerfMetrics{}
	}
	return e.coll.Perf()
}

func (m *CollectorManager) Status(clusterID string) model.CollectorStatus {
	e := m.entry(clusterID)
	if e == nil {
		return model.CollectorStatus{}
	}
	return e.coll.Status()
}

func (m *CollectorManager) GlobalPerf() model.GlobalPerf {
	m.mu.RLock()
	defer m.mu.RUnlock()
	gp := model.GlobalPerf{
		ClusterCount:      len(m.collectors),
		GlobalConcurrency: m.limiter.Capacity(),
		UpdatedAt:         model.NowMs(),
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
