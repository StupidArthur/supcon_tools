package collector

import (
	"context"
	"os"
	"testing"
	"time"

	"raymonitor/model"
)

// noopStore 是仅用于探针的零开销 Store：忽略所有写，避免真的去开 SQLite。
type noopStore struct{}

func (noopStore) WriteNodeMetrics(string, []model.NodeMetric) error        { return nil }
func (noopStore) WriteWorkers(string, []model.WorkerSnapshot) error        { return nil }
func (noopStore) WriteActors(string, []model.ActorSnapshot) error         { return nil }
func (noopStore) WriteJobs(string, []model.JobSnapshot) error             { return nil }
func (noopStore) WriteCluster(string, model.ClusterMetric) error          { return nil }
func (noopStore) WriteActorEvents(string, []model.ActorEvent) error       { return nil }
func (noopStore) WriteJobEvents(string, []model.JobEvent) error           { return nil }

// TestProbeLiveClusterOneRound 用完全放开的并发和超时，去真实集群拉一轮数据。
// 用于回答"集群-NLB 慢链路在不限时长下到底要多久才能拉完"这类诊断问题。
//
// 运行方式：
//   RAY_PROBE_URL=http://host:port go test ./collector -run TestProbeLiveClusterOneRound -v
func TestProbeLiveClusterOneRound(t *testing.T) {
	base := os.Getenv("RAY_PROBE_URL")
	if base == "" {
		t.Skip("set RAY_PROBE_URL=... to enable")
	}

	opts := CollectorOpts{
		ClusterID:   "probe",
		PlatformURL: base,
		TimeoutSec:  60,
		Concurrency: 50,
	}

	client := NewClient(opts)
	coll := NewCollector(client, noopStore{}, opts)

	// 整体给 5 分钟上限，避免卡死测试进程
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	t.Logf("probing %s with Concurrency=%d TimeoutSec=%d", base, opts.Concurrency, opts.TimeoutSec)

	t0 := time.Now()
	coll.collectSummary(ctx)
	summaryMs := time.Since(t0).Milliseconds()
	t.Logf("summary: %d ms", summaryMs)

	t1 := time.Now()
	coll.collectDetail(ctx)
	detailMs := time.Since(t1).Milliseconds()
	totalMs := time.Since(t0).Milliseconds()
	t.Logf("detail: %d ms", detailMs)
	t.Logf("total round: %d ms", totalMs)

	snap := coll.Snapshot()
	if snap != nil {
		t.Logf("snapshot: %d nodes, %d workers, %d actors",
			len(snap.Nodes), len(snap.Workers), len(snap.Actors))
		t.Logf("cluster metric: cpu=%v/%v mem=%v/%v gpu=%v/%v",
			snap.Cluster.CPUUsed, snap.Cluster.CPUTotal,
			snap.Cluster.MemUsed, snap.Cluster.MemTotal,
			snap.Cluster.GPUUsed, snap.Cluster.GPUTotal)
		t.Logf("health: total=%d fresh=%d failed=%d stale=%d missing=%d jobsFresh=%v clusterFresh=%v",
			snap.Health.TotalNodeCount, snap.Health.FreshNodeCount,
			snap.Health.FailedNodeCount, snap.Health.StaleNodeCount, snap.Health.MissingNodeCount,
			snap.Health.JobsDataStale == false, snap.Health.ClusterDataStale == false)
	} else {
		t.Log("snapshot is nil")
	}

	perf := coll.Perf()
	t.Logf("perf: detailMaxNodeMs=%d slowNodeID=%s",
		perf.DetailMaxNodeMs, perf.SlowNodeID)

	st := coll.Status()
	t.Logf("status: lastError=%q lastErrorStage=%q errCount=%d",
		truncateErrShort(st.LastError), st.LastErrorStage, st.ErrCount)
}

func truncateErrShort(s string) string {
	if len(s) > 200 {
		return s[:200] + "..."
	}
	return s
}

// TestProbeDetailSerial20 串行 20 次 collectDetail，观察单链路稳定性和耗时分布。
// 同样用 50 并发 + 60s 超时（完全放开），但只跑 detail，不带 summary。
// 运行方式：
//   RAY_PROBE_URL=http://host:port go test ./collector -run TestProbeDetailSerial20 -v
func TestProbeDetailSerial20(t *testing.T) {
	base := os.Getenv("RAY_PROBE_URL")
	if base == "" {
		t.Skip("set RAY_PROBE_URL=...")
	}

	opts := CollectorOpts{
		ClusterID:   "probe",
		PlatformURL: base,
		TimeoutSec:  60,
		Concurrency: 50,
	}
	client := NewClient(opts)
	coll := NewCollector(client, noopStore{}, opts)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	// 一次性 summary，喂出节点列表给 detail 用
	t0 := time.Now()
	coll.collectSummary(ctx)
	t.Logf("summary: %d ms (to seed snap.Nodes)", time.Since(t0).Milliseconds())

	detailMs := make([]int64, 0, 20)
	maxNodeMsList := make([]int64, 0, 20)
	for i := 1; i <= 20; i++ {
		t1 := time.Now()
		coll.collectDetail(ctx)
		ms := time.Since(t1).Milliseconds()
		perf := coll.Perf()
		snap := coll.Snapshot()
		var h model.CollectionHealth
		if snap != nil {
			h = snap.Health
		}
		detailMs = append(detailMs, ms)
		maxNodeMsList = append(maxNodeMsList, perf.DetailMaxNodeMs)
		t.Logf("iter=%2d  detailMs=%5d  maxNodeMs=%5d  fresh=%d failed=%d stale=%d missing=%d",
			i, ms, perf.DetailMaxNodeMs,
			h.FreshNodeCount, h.FailedNodeCount,
			h.StaleNodeCount, h.MissingNodeCount)
	}

	// 统计
	var sum, mn, mx int64 = 0, detailMs[0], detailMs[0]
	for _, v := range detailMs {
		sum += v
		if v < mn {
			mn = v
		}
		if v > mx {
			mx = v
		}
	}
	avg := sum / int64(len(detailMs))
	t.Logf("detailMs over 20 runs: min=%d avg=%d max=%d", mn, avg, mx)
}
