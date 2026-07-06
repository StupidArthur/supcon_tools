package storage

import (
	"path/filepath"
	"testing"

	"raymonitor/model"
)

// newTestStore 在临时目录建库，测试完自动清理。
func newTestStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	s, err := Open(filepath.Join(dir, "test.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

// ---- 正常路径：写入 + 查询回读一致 ----

func TestWriteAndQueryNodeHistory(t *testing.T) {
	s := newTestStore(t)
	ns := []model.NodeMetric{
		{Ts: 100, NodeID: "n1", Hostname: "h1", CPU: 1.0, MemTotal: 100, MemUsed: 50, GPUTotal: 0},
		{Ts: 200, NodeID: "n1", Hostname: "h1", CPU: 2.0, MemTotal: 100, MemUsed: 60, GPUTotal: 0},
		{Ts: 150, NodeID: "n2", Hostname: "h2", CPU: 0.5, MemTotal: 200, MemUsed: 10},
	}
	if err := s.WriteNodeMetrics("c1", ns); err != nil {
		t.Fatalf("write: %v", err)
	}
	got, err := s.QueryNodeHistory("c1", "n1", 0, 300)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("want 2 rows for n1, got %d", len(got))
	}
	// 应按 ts 升序
	if got[0].Ts != 100 || got[1].Ts != 200 {
		t.Errorf("order wrong: %+v", got)
	}
	if got[1].CPU != 2.0 {
		t.Errorf("cpu wrong: %v", got[1].CPU)
	}
}

// ---- 正常路径：事件写入与查询 ----

func TestWriteAndQueryActorEvents(t *testing.T) {
	s := newTestStore(t)
	es := []model.ActorEvent{
		{Ts: 100, ActorID: "a1", PrevState: "ALIVE", NewState: "DEAD", DeathCause: "oom"},
		{Ts: 200, ActorID: "a2", PrevState: "ALIVE", NewState: "DEAD", DeathCause: "err"},
	}
	if err := s.WriteActorEvents("c1", es); err != nil {
		t.Fatalf("write: %v", err)
	}
	got, err := s.QueryActorEvents("c1", 0, 300)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("want 2 events, got %d", len(got))
	}
	// 应按 ts DESC
	if got[0].Ts != 200 {
		t.Errorf("order wrong: %+v", got)
	}
}

// ---- 空输入 ----

func TestWriteNodeMetrics_Empty(t *testing.T) {
	s := newTestStore(t)
	if err := s.WriteNodeMetrics("c1", nil); err != nil {
		t.Errorf("empty write should ok: %v", err)
	}
	got, err := s.QueryNodeHistory("c1", "n1", 0, 300)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("want empty, got %d", len(got))
	}
}

func TestQueryNodeHistory_NotExist(t *testing.T) {
	s := newTestStore(t)
	_ = s.WriteNodeMetrics("c1", []model.NodeMetric{{Ts: 100, NodeID: "n1"}})
	got, err := s.QueryNodeHistory("c1", "notexist", 0, 300)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("want empty for nonexistent node, got %d", len(got))
	}
}

// ---- 边界：时间范围过滤 ----

func TestQueryNodeHistory_TimeRange(t *testing.T) {
	s := newTestStore(t)
	_ = s.WriteNodeMetrics("c1", []model.NodeMetric{
		{Ts: 100, NodeID: "n1"}, {Ts: 200, NodeID: "n1"}, {Ts: 300, NodeID: "n1"},
	})
	got, _ := s.QueryNodeHistory("c1", "n1", 150, 250)
	if len(got) != 1 || got[0].Ts != 200 {
		t.Errorf("time range filter wrong: %+v", got)
	}
}

// ---- 边界：JobHistory 按 status 过滤 ----

func TestQueryJobHistory_StatusFilter(t *testing.T) {
	s := newTestStore(t)
	_ = s.WriteJobs("c1", []model.JobSnapshot{
		{Ts: 100, JobID: "j1", Status: "RUNNING"},
		{Ts: 100, JobID: "j2", Status: "FAILED", ErrorType: "OOM"},
	})
	all, _ := s.QueryJobHistory("c1", 0, 300, "")
	if len(all) != 2 {
		t.Errorf("want 2, got %d", len(all))
	}
	failed, _ := s.QueryJobHistory("c1", 0, 300, "FAILED")
	if len(failed) != 1 || failed[0].Status != "FAILED" {
		t.Errorf("status filter wrong: %+v", failed)
	}
}

// ---- 边界：重复建表幂等（多次 Open 不报错）----
// Open 内部 createSchema 用 IF NOT EXISTS，重复 Open 同一文件应幂等。

// ---- 边界：GPU 字段存取 ----

func TestWriteNodeMetric_GPU(t *testing.T) {
	s := newTestStore(t)
	_ = s.WriteNodeMetrics("c1", []model.NodeMetric{
		{Ts: 100, NodeID: "n1", GPUTotal: 8.0, GPUUsed: 2.0},
	})
	got, _ := s.QueryNodeHistory("c1", "n1", 0, 300)
	if len(got) != 1 || got[0].GPUTotal != 8.0 || got[0].GPUUsed != 2.0 {
		t.Errorf("gpu roundtrip wrong: %+v", got)
	}
}
