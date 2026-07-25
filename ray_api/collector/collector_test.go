package collector

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"raymonitor/model"
)

func newTestClient(t *testing.T, handler http.Handler) *Client {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	return NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})
}

func ctx() context.Context { return context.Background() }

func TestFetchNodes_HappyAndPartial(t *testing.T) {
	summary := map[string]interface{}{
		"result": true,
		"data": map[string]interface{}{
			"summary": []map[string]interface{}{
				{
					"mem":      []interface{}{16000000000.0, 13085171712.0, 18.2, 2914828288.0},
					"cpu":      1.4,
					"hostname": "head",
					"ip":       "10.166.0.249",
					"raylet": map[string]interface{}{
						"nodeId":              "7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884",
						"state":               "ALIVE",
						"isHeadNode":          true,
						"nodeManagerHostname": "head",
						"resourcesTotal":      map[string]interface{}{"CPU": 8.0, "memory": 16000000000.0},
					},
				},
				{
					"raylet": map[string]interface{}{
						"nodeId":     "fa0496154f1b6dde973f4cbafc17a9be6528396ef6c2843385f9e880",
						"state":      "ALIVE",
						"isHeadNode": false,
					},
				},
			},
		},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(summary)
	}))

	nodes, err := c.FetchNodes(ctx())
	if err != nil {
		t.Fatalf("FetchNodes err: %v", err)
	}
	if len(nodes) != 2 {
		t.Fatalf("want 2 nodes, got %d", len(nodes))
	}
	if nodes[0].Hostname != "head" || nodes[0].NodeID != "7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884" {
		t.Errorf("node0 wrong: %+v", nodes[0])
	}
	if nodes[0].MemTotal != 16000000000 || nodes[0].MemUsed != 13085171712 || nodes[0].CPU != 1.4 {
		t.Errorf("node0 hardware wrong: %+v", nodes[0])
	}
	if nodes[0].IsPartial || !nodes[0].IsHead || nodes[0].State != "ALIVE" {
		t.Errorf("node0 flags wrong: %+v", nodes[0])
	}
	if !nodes[1].IsPartial {
		t.Errorf("node1 should be partial")
	}
	if nodes[1].MemTotal != 0 || nodes[1].CPU != 0 {
		t.Errorf("partial node hardware should be zero: %+v", nodes[1])
	}
	if nodes[1].NodeID != "fa0496154f1b6dde973f4cbafc17a9be6528396ef6c2843385f9e880" {
		t.Errorf("partial node id wrong: %s", nodes[1].NodeID)
	}
}

func TestFetchNodeDetail_Happy(t *testing.T) {
	detail := map[string]interface{}{
		"result": true,
		"data": map[string]interface{}{
			"detail": map[string]interface{}{
				"mem":      []interface{}{16000000000.0, 13085171712.0},
				"cpu":      1.4,
				"ip":       "10.166.0.249",
				"hostname": "head",
				"workers": []map[string]interface{}{
					{"pid": 329, "jobId": "ffff", "cpuPercent": 0.0, "numFds": 23, "language": "PYTHON",
						"memoryInfo": map[string]interface{}{"rss": 123456}},
				},
				"actors": map[string]interface{}{
					"acc6fefd430254ec3744bc4901000000": map[string]interface{}{
						"className": "ServeController", "name": "SERVE_CONTROLLER_ACTOR",
						"state": "ALIVE", "numRestarts": "0", "jobId": "01000000", "pid": 2290,
						"ipAddress": "10.166.0.249", "numExecutedTasks": 31696, "exitDetail": "-",
						"requiredResources": map[string]interface{}{"node:InternalHead": 0.001},
					},
				},
				"raylet": map[string]interface{}{
					"state": "ALIVE", "isHeadNode": true,
					"nodeId":              "7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884",
					"nodeManagerHostname": "head",
					"resourcesTotal":      map[string]interface{}{"CPU": 16.0, "memory": 16000000000.0},
				},
			},
		},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(detail)
	}))

	d, err := c.FetchNodeDetail(ctx(), "7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if d.Node.GPUTotal != 0 {
		t.Errorf("no-GPU cluster should have gpuTotal=0, got %v", d.Node.GPUTotal)
	}
	if !d.Node.IsHead || d.Node.State != "ALIVE" {
		t.Errorf("node wrong: %+v", d.Node)
	}
	if len(d.Workers) != 1 || d.Workers[0].PID != 329 || d.Workers[0].JobID != "ffff" {
		t.Errorf("workers wrong: %+v", d.Workers)
	}
	if d.Workers[0].MemRSS != 123456 {
		t.Errorf("worker rss wrong: %d", d.Workers[0].MemRSS)
	}
	if len(d.Actors) != 1 {
		t.Fatalf("want 1 actor")
	}
	a := d.Actors[0]
	if a.ActorID != "acc6fefd430254ec3744bc4901000000" {
		t.Errorf("actor id wrong: %s", a.ActorID)
	}
	if a.ActorClass != "ServeController" || a.State != "ALIVE" || a.NumRestarts != 0 {
		t.Errorf("actor wrong: %+v", a)
	}
}

func TestFetchNodeDetailPreservesActorIDs(t *testing.T) {
	detail := map[string]interface{}{
		"result": true,
		"data": map[string]interface{}{
			"detail": map[string]interface{}{
				"mem": []interface{}{16000000000.0, 8000000000.0},
				"cpu": 1.0,
				"actors": map[string]interface{}{
					"actor-id-1": map[string]interface{}{
						"className": "Worker1", "state": "ALIVE", "pid": 100,
					},
					"actor-id-2": map[string]interface{}{
						"className": "Worker2", "state": "ALIVE", "pid": 200,
					},
				},
				"raylet": map[string]interface{}{
					"state": "ALIVE", "nodeId": "n1",
					"resourcesTotal": map[string]interface{}{"CPU": 8.0},
				},
			},
		},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(detail)
	}))

	d, err := c.FetchNodeDetail(ctx(), "n1")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(d.Actors) != 2 {
		t.Fatalf("want 2 actors, got %d", len(d.Actors))
	}
	ids := map[string]bool{}
	for _, a := range d.Actors {
		ids[a.ActorID] = true
	}
	if !ids["actor-id-1"] || !ids["actor-id-2"] {
		t.Errorf("actor IDs not preserved: %+v", ids)
	}
}

func TestFetchCluster_Happy(t *testing.T) {
	status := map[string]interface{}{
		"result": true,
		"data": map[string]interface{}{
			"autoscalingStatus": "Cluster status: 3 nodes\n" +
				" - ResourceUsage: 1.0/16.0 CPU, 0.0 GiB/44.7 GiB memory, 2.0/8.0 GPU\n" +
				" - TimeSinceLastHeartbeat: Min=0 Mean=0 Max=0.04\n",
		},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(status)
	}))

	cm, err := c.FetchCluster(ctx())
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if cm.CPUUsed != 1.0 || cm.CPUTotal != 16.0 {
		t.Errorf("cpu wrong: %+v", cm)
	}
	if cm.MemUsed != 0.0 || cm.MemTotal != 44.7 {
		t.Errorf("mem wrong: %+v", cm)
	}
	if cm.GPUUsed != 2.0 || cm.GPUTotal != 8.0 {
		t.Errorf("gpu wrong: %+v", cm)
	}
	if cm.HeartbeatMax != 0.04 {
		t.Errorf("heartbeat wrong: %+v", cm)
	}
}

func TestFetchJobs_Happy(t *testing.T) {
	longEntry := "python " + strings.Repeat("x", 100)
	jobs := []map[string]interface{}{
		{"job_id": "01000000", "status": "RUNNING", "start_time": 1782458409790,
			"end_time": 0, "error_type": "", "entrypoint": longEntry},
		{"job_id": "02000000", "status": "FAILED", "start_time": 1782458409790,
			"end_time": 1782458500000, "error_type": "RuntimeError", "entrypoint": "short"},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(jobs)
	}))

	out, err := c.FetchJobs(ctx())
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(out) != 2 {
		t.Fatalf("want 2 jobs")
	}
	if len(out[0].Entry) > 80 {
		t.Errorf("entry not truncated: %d", len(out[0].Entry))
	}
	if out[1].Status != "FAILED" || out[1].ErrorType != "RuntimeError" {
		t.Errorf("job1 wrong: %+v", out[1])
	}
}

func TestFetchNodes_Empty(t *testing.T) {
	summary := map[string]interface{}{"result": true, "data": map[string]interface{}{"summary": []interface{}{}}}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(summary)
	}))
	nodes, err := c.FetchNodes(ctx())
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(nodes) != 0 {
		t.Errorf("want empty, got %d", len(nodes))
	}
}

func TestFetchNodes_HTTPError(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	if _, err := c.FetchNodes(ctx()); err == nil {
		t.Errorf("want error on 500")
	}
}

func TestFetchNodes_BadJSON(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("not json"))
	}))
	if _, err := c.FetchNodes(ctx()); err == nil {
		t.Errorf("want error on bad json")
	}
}

func TestFetchNodes_ResultFalse(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{"result": false})
	}))
	if _, err := c.FetchNodes(ctx()); err == nil {
		t.Errorf("want error on result=false")
	}
}

type fakeStore struct {
	actorEvents []model.ActorEvent
	jobEvents   []model.JobEvent
	actors      []model.ActorSnapshot
	workers     []model.WorkerSnapshot
	nodes       []model.NodeMetric
	jobs        []model.JobSnapshot
	clusters    []model.ClusterMetric

	failWriteWorkers bool
	failWriteActors  bool
	failWriteNodes   bool
	failWriteJobs    bool
	failWriteCluster bool
}

func (f *fakeStore) WriteNodeMetrics(_ string, ns []model.NodeMetric) error {
	if f.failWriteNodes {
		return context.DeadlineExceeded
	}
	f.nodes = append(f.nodes, ns...)
	return nil
}
func (f *fakeStore) WriteWorkers(_ string, ws []model.WorkerSnapshot) error {
	if f.failWriteWorkers {
		return context.DeadlineExceeded
	}
	f.workers = append(f.workers, ws...)
	return nil
}
func (f *fakeStore) WriteActors(_ string, a []model.ActorSnapshot) error {
	if f.failWriteActors {
		return context.DeadlineExceeded
	}
	f.actors = append(f.actors, a...)
	return nil
}
func (f *fakeStore) WriteJobs(_ string, js []model.JobSnapshot) error {
	if f.failWriteJobs {
		return context.DeadlineExceeded
	}
	f.jobs = append(f.jobs, js...)
	return nil
}
func (f *fakeStore) WriteCluster(_ string, c model.ClusterMetric) error {
	if f.failWriteCluster {
		return context.DeadlineExceeded
	}
	f.clusters = append(f.clusters, c)
	return nil
}
func (f *fakeStore) WriteActorEvents(_ string, e []model.ActorEvent) error {
	f.actorEvents = append(f.actorEvents, e...)
	return nil
}
func (f *fakeStore) WriteJobEvents(_ string, e []model.JobEvent) error {
	f.jobEvents = append(f.jobEvents, e...)
	return nil
}

func TestDiffActors_StateChange(t *testing.T) {
	col := NewCollector(nil, &fakeStore{}, CollectorOpts{})
	first := []model.ActorSnapshot{
		{ActorID: "A1", State: "ALIVE", ActorClass: "C1"},
		{ActorID: "A2", State: "ALIVE", ActorClass: "C2"},
	}
	if e := col.diffActorsForNode("n1", first); len(e) != 0 {
		t.Errorf("first round should have 0 events, got %d", len(e))
	}
	second := []model.ActorSnapshot{
		{ActorID: "A1", State: "DEAD", ActorClass: "C1", ExitDetail: "oom"},
		{ActorID: "A2", State: "ALIVE", ActorClass: "C2"},
		{ActorID: "A3", State: "ALIVE", ActorClass: "C3"},
	}
	events := col.diffActorsForNode("n1", second)
	if len(events) != 1 {
		t.Fatalf("want 1 event (A1 DEAD), got %d", len(events))
	}
	if events[0].ActorID != "A1" || events[0].PrevState != "ALIVE" || events[0].NewState != "DEAD" {
		t.Errorf("event wrong: %+v", events[0])
	}
	if events[0].DeathCause != "oom" {
		t.Errorf("death cause wrong: %s", events[0].DeathCause)
	}
}

func TestDiffJobs_StatusChange(t *testing.T) {
	col := NewCollector(nil, &fakeStore{}, CollectorOpts{})
	col.diffJobs([]model.JobSnapshot{{JobID: "J1", Status: "RUNNING"}})
	events := col.diffJobs([]model.JobSnapshot{{JobID: "J1", Status: "FAILED", ErrorType: "OOMError"}})
	if len(events) != 1 || events[0].NewStatus != "FAILED" || events[0].ErrorType != "OOMError" {
		t.Errorf("job event wrong: %+v", events)
	}
}

func TestFetchNodeDetail_WithGPU(t *testing.T) {
	detail := map[string]interface{}{
		"result": true,
		"data": map[string]interface{}{
			"detail": map[string]interface{}{
				"mem": []interface{}{32000000000.0, 16000000000.0},
				"cpu": 0.2,
				"actors": map[string]interface{}{
					"a1": map[string]interface{}{
						"className": "Trainer", "state": "ALIVE", "pid": 1,
						"requiredResources": map[string]interface{}{"GPU": 2.0},
					},
				},
				"raylet": map[string]interface{}{
					"state": "ALIVE", "isHeadNode": false, "nodeId": "n1",
					"resourcesTotal": map[string]interface{}{"GPU": 8.0, "CPU": 16.0},
				},
			},
		},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(detail)
	}))
	d, err := c.FetchNodeDetail(ctx(), "n1")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if d.Node.GPUTotal != 8.0 {
		t.Errorf("gpuTotal want 8, got %v", d.Node.GPUTotal)
	}
	if d.Node.GPUUsed != 2.0 {
		t.Errorf("node gpuUsed want 2, got %v", d.Node.GPUUsed)
	}
	if len(d.Actors) != 1 || d.Actors[0].GPUUsed != 2.0 {
		t.Errorf("actor gpuUsed wrong: %+v", d.Actors)
	}
}

func TestCollector_StatusBeforeStart(t *testing.T) {
	col := NewCollector(nil, &fakeStore{}, CollectorOpts{SummaryEvery: 15, DetailEvery: 60})
	st := col.Status()
	if st.Running {
		t.Errorf("should not be running before start")
	}
	if col.Snapshot() != nil {
		t.Errorf("snapshot should be nil before first collect")
	}
	c, cancel := context.WithCancel(context.Background())
	cancel()
	col.Start(c)
}

func gzipEncode(t *testing.T, payload []byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	if _, err := gz.Write(payload); err != nil {
		t.Fatalf("gzip write: %v", err)
	}
	if err := gz.Close(); err != nil {
		t.Fatalf("gzip close: %v", err)
	}
	return buf.Bytes()
}

func TestFetchNodes_GzipSupported(t *testing.T) {
	payload := []byte(`{"result":true,"data":{"summary":[]}}`)
	body := gzipEncode(t, payload)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Encoding", "gzip")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(body)
	}))
	t.Cleanup(srv.Close)
	c := NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})

	nodes, err := c.FetchNodes(ctx())
	if err != nil {
		t.Fatalf("FetchNodes: %v", err)
	}
	if len(nodes) != 0 {
		t.Errorf("want 0 nodes, got %d", len(nodes))
	}
	if !c.LastGzipUsed() {
		t.Errorf("dashboard sent gzip, but LastGzipUsed()=false")
	}
}

func TestFetchNodes_GzipUnsupported(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"result":true,"data":{"summary":[]}}`))
	}))
	t.Cleanup(srv.Close)
	c := NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})

	if _, err := c.FetchNodes(ctx()); err != nil {
		t.Fatalf("FetchNodes: %v", err)
	}
	if c.LastGzipUsed() {
		t.Errorf("dashboard sent plain, but LastGzipUsed()=true")
	}
}

func TestFetchNodes_GzipBroken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Encoding", "gzip")
		_, _ = w.Write([]byte("this is not gzip"))
	}))
	t.Cleanup(srv.Close)
	c := NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})

	_, err := c.FetchNodes(ctx())
	if err == nil {
		t.Errorf("want error on broken gzip body, got nil")
	}
	if !strings.Contains(err.Error(), "gzip") {
		t.Errorf("error should mention gzip, got: %v", err)
	}
}

func TestCollectDetailRetainsLastGoodNodeDataOnPartialFailure(t *testing.T) {
	callCount := map[string]int{}
	mux := http.NewServeMux()
	mux.HandleFunc("/nodes", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true,
			"data": map[string]interface{}{
				"summary": []map[string]interface{}{
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0, "hostname": "a",
						"raylet": map[string]interface{}{"nodeId": "A", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0, "hostname": "b",
						"raylet": map[string]interface{}{"nodeId": "B", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0, "hostname": "c",
						"raylet": map[string]interface{}{"nodeId": "C", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
				},
			},
		})
	})
	mux.HandleFunc("/nodes/A", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(nodeDetailJSON("A", 2))
	})
	mux.HandleFunc("/nodes/B", func(w http.ResponseWriter, r *http.Request) {
		callCount["B"]++
		if callCount["B"] >= 2 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_ = json.NewEncoder(w).Encode(nodeDetailJSON("B", 3))
	})
	mux.HandleFunc("/nodes/C", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(nodeDetailJSON("C", 4))
	})
	mux.HandleFunc("/api/cluster_status", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true, "data": map[string]interface{}{"autoscalingStatus": "1.0/24.0 CPU, 5.0 GiB/30.0 GiB memory"},
		})
	})
	mux.HandleFunc("/api/jobs/", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]interface{}{})
	})

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	store := &fakeStore{}
	opts := CollectorOpts{ClusterID: "test", PlatformURL: srv.URL, TimeoutSec: 2, Concurrency: 5, SummaryEvery: 5, DetailEvery: 5}
	client := NewClient(opts)
	col := NewCollector(client, store, opts)

	c, cancel := context.WithCancel(context.Background())
	defer cancel()

	col.collectSummary(c)
	col.collectDetail(c)

	snap := col.Snapshot()
	if snap == nil {
		t.Fatal("snapshot nil after first detail")
	}
	if len(snap.Workers) != 9 {
		t.Fatalf("round1: want 9 workers, got %d", len(snap.Workers))
	}

	col.collectDetail(c)

	snap = col.Snapshot()
	if snap == nil {
		t.Fatal("snapshot nil after second detail")
	}
	if len(snap.Workers) != 9 {
		t.Errorf("round2: want 9 workers (B retained), got %d", len(snap.Workers))
	}
	if !snap.Health.CurrentIncomplete {
		t.Errorf("round2: CurrentIncomplete should be true")
	}
	if snap.Health.FailedNodeCount != 1 {
		t.Errorf("round2: FailedNodeCount want 1, got %d", snap.Health.FailedNodeCount)
	}

	var bStale bool
	for _, fn := range snap.Health.FailedNodes {
		if fn.NodeID == "B" {
			bStale = fn.CurrentStale
			if !fn.HasCachedData {
				t.Errorf("B should have cached data")
			}
			if fn.ReusedWorkerCount != 3 {
				t.Errorf("B reused workers want 3, got %d", fn.ReusedWorkerCount)
			}
		}
	}
	if !bStale {
		t.Errorf("B should be marked stale")
	}
}

func nodeDetailJSON(nodeID string, workerCount int) map[string]interface{} {
	workers := make([]map[string]interface{}, workerCount)
	for i := 0; i < workerCount; i++ {
		workers[i] = map[string]interface{}{
			"pid": 100 + i, "cpuPercent": 1.0,
			"memoryInfo": map[string]interface{}{"rss": 1024},
		}
	}
	return map[string]interface{}{
		"result": true,
		"data": map[string]interface{}{
			"detail": map[string]interface{}{
				"mem":     []interface{}{1e10, 5e9},
				"cpu":     1.0,
				"workers": workers,
				"actors":  map[string]interface{}{},
				"raylet": map[string]interface{}{
					"state": "ALIVE", "nodeId": nodeID,
					"resourcesTotal": map[string]interface{}{"CPU": 8.0},
				},
			},
		},
	}
}

func TestCollectDetailMarksMissingNodeWithoutFabricatingData(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/nodes", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true,
			"data": map[string]interface{}{
				"summary": []map[string]interface{}{
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0, "hostname": "a",
						"raylet": map[string]interface{}{"nodeId": "A", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0, "hostname": "b",
						"raylet": map[string]interface{}{"nodeId": "B", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
				},
			},
		})
	})
	mux.HandleFunc("/nodes/A", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(nodeDetailJSON("A", 2))
	})
	mux.HandleFunc("/nodes/B", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	})
	mux.HandleFunc("/api/cluster_status", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true, "data": map[string]interface{}{"autoscalingStatus": "1.0/16.0 CPU, 5.0 GiB/20.0 GiB memory"},
		})
	})
	mux.HandleFunc("/api/jobs/", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]interface{}{})
	})

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	store := &fakeStore{}
	opts := CollectorOpts{ClusterID: "test", PlatformURL: srv.URL, TimeoutSec: 2, Concurrency: 5, SummaryEvery: 5, DetailEvery: 5}
	client := NewClient(opts)
	col := NewCollector(client, store, opts)

	c, cancel := context.WithCancel(context.Background())
	defer cancel()

	col.collectSummary(c)
	col.collectDetail(c)

	snap := col.Snapshot()
	if snap == nil {
		t.Fatal("snapshot nil")
	}
	if len(snap.Workers) != 2 {
		t.Errorf("want 2 workers (only A), got %d", len(snap.Workers))
	}
	for _, fn := range snap.Health.FailedNodes {
		if fn.NodeID == "B" {
			if fn.HasCachedData {
				t.Errorf("B never succeeded, should not have cached data")
			}
		}
	}
}

func TestClusterFailureKeepsPreviousClusterMetric(t *testing.T) {
	callCount := 0
	mux := http.NewServeMux()
	mux.HandleFunc("/nodes", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true,
			"data": map[string]interface{}{
				"summary": []map[string]interface{}{
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0,
						"raylet": map[string]interface{}{"nodeId": "A", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
				},
			},
		})
	})
	mux.HandleFunc("/nodes/A", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(nodeDetailJSON("A", 1))
	})
	mux.HandleFunc("/api/cluster_status", func(w http.ResponseWriter, r *http.Request) {
		callCount++
		if callCount >= 2 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true, "data": map[string]interface{}{"autoscalingStatus": "5.0/16.0 CPU, 10.0 GiB/44.0 GiB memory"},
		})
	})
	mux.HandleFunc("/api/jobs/", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]interface{}{})
	})

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	store := &fakeStore{}
	opts := CollectorOpts{ClusterID: "test", PlatformURL: srv.URL, TimeoutSec: 2, Concurrency: 5, SummaryEvery: 5, DetailEvery: 5}
	client := NewClient(opts)
	col := NewCollector(client, store, opts)

	c, cancel := context.WithCancel(context.Background())
	defer cancel()

	col.collectSummary(c)
	col.collectDetail(c)

	snap := col.Snapshot()
	if snap.Cluster.CPUUsed != 5.0 {
		t.Fatalf("round1 cluster cpuUsed want 5, got %v", snap.Cluster.CPUUsed)
	}

	col.collectDetail(c)

	snap = col.Snapshot()
	if snap.Cluster.CPUUsed != 5.0 {
		t.Errorf("round2 cluster should retain old value 5.0, got %v", snap.Cluster.CPUUsed)
	}
	if !snap.Health.ClusterDataStale {
		t.Errorf("round2 ClusterDataStale should be true")
	}
}

func TestJobsFailureKeepsPreviousJobsAndDiffBaseline(t *testing.T) {
	callCount := 0
	mux := http.NewServeMux()
	mux.HandleFunc("/nodes", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true,
			"data": map[string]interface{}{
				"summary": []map[string]interface{}{
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0,
						"raylet": map[string]interface{}{"nodeId": "A", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
				},
			},
		})
	})
	mux.HandleFunc("/nodes/A", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(nodeDetailJSON("A", 1))
	})
	mux.HandleFunc("/api/cluster_status", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true, "data": map[string]interface{}{"autoscalingStatus": "1.0/8.0 CPU, 5.0 GiB/10.0 GiB memory"},
		})
	})
	mux.HandleFunc("/api/jobs/", func(w http.ResponseWriter, r *http.Request) {
		callCount++
		if callCount >= 2 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_ = json.NewEncoder(w).Encode([]map[string]interface{}{
			{"job_id": "J1", "status": "RUNNING", "start_time": 1000, "end_time": 0},
		})
	})

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	store := &fakeStore{}
	opts := CollectorOpts{ClusterID: "test", PlatformURL: srv.URL, TimeoutSec: 2, Concurrency: 5, SummaryEvery: 5, DetailEvery: 5}
	client := NewClient(opts)
	col := NewCollector(client, store, opts)

	c, cancel := context.WithCancel(context.Background())
	defer cancel()

	col.collectSummary(c)
	col.collectDetail(c)

	snap := col.Snapshot()
	if len(snap.Jobs) != 1 {
		t.Fatalf("round1 want 1 job, got %d", len(snap.Jobs))
	}

	col.collectDetail(c)

	snap = col.Snapshot()
	if len(snap.Jobs) != 1 {
		t.Errorf("round2 jobs should retain old list, got %d", len(snap.Jobs))
	}
	if !snap.Health.JobsDataStale {
		t.Errorf("round2 JobsDataStale should be true")
	}
}

func TestSnapshotStillUpdatesWhenStorageFails(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/nodes", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true,
			"data": map[string]interface{}{
				"summary": []map[string]interface{}{
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0,
						"raylet": map[string]interface{}{"nodeId": "A", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
				},
			},
		})
	})
	mux.HandleFunc("/nodes/A", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(nodeDetailJSON("A", 3))
	})
	mux.HandleFunc("/api/cluster_status", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true, "data": map[string]interface{}{"autoscalingStatus": "1.0/8.0 CPU, 5.0 GiB/10.0 GiB memory"},
		})
	})
	mux.HandleFunc("/api/jobs/", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]interface{}{})
	})

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	store := &fakeStore{failWriteWorkers: true}
	opts := CollectorOpts{ClusterID: "test", PlatformURL: srv.URL, TimeoutSec: 2, Concurrency: 5, SummaryEvery: 5, DetailEvery: 5}
	client := NewClient(opts)
	col := NewCollector(client, store, opts)

	c, cancel := context.WithCancel(context.Background())
	defer cancel()

	col.collectSummary(c)
	col.collectDetail(c)

	snap := col.Snapshot()
	if snap == nil {
		t.Fatal("snapshot nil")
	}
	if len(snap.Workers) != 3 {
		t.Errorf("snapshot should still show 3 workers despite storage failure, got %d", len(snap.Workers))
	}
	if snap.Health.LastStorageError == "" {
		t.Errorf("storage error should be recorded in health")
	}
}

func TestRequestWaitingForLimiterCanBeCanceled(t *testing.T) {
	limiter := newSemaphoreLimiter(1)
	limiter.Acquire(context.Background())

	c, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- limiter.Acquire(c)
	}()

	cancel()
	err := <-done
	if err == nil {
		t.Errorf("acquire should fail after cancel")
	}
	limiter.Release()
}

func TestStopDoesNotIncrementFailureForContextCanceled(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/nodes", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true,
			"data": map[string]interface{}{
				"summary": []map[string]interface{}{
					{"mem": []interface{}{1e10, 5e9}, "cpu": 1.0,
						"raylet": map[string]interface{}{"nodeId": "A", "state": "ALIVE", "resourcesTotal": map[string]interface{}{"CPU": 8.0}}},
				},
			},
		})
	})
	mux.HandleFunc("/nodes/A", func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	})
	mux.HandleFunc("/api/cluster_status", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"result": true, "data": map[string]interface{}{"autoscalingStatus": ""},
		})
	})
	mux.HandleFunc("/api/jobs/", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]interface{}{})
	})

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	store := &fakeStore{}
	opts := CollectorOpts{ClusterID: "test", PlatformURL: srv.URL, TimeoutSec: 30, Concurrency: 5, SummaryEvery: 5, DetailEvery: 5}
	client := NewClient(opts)
	col := NewCollector(client, store, opts)

	c, cancel := context.WithCancel(context.Background())
	col.collectSummary(c)

	go col.collectDetail(c)
	cancel()

	st := col.Status()
	if st.ErrCount > 0 {
		t.Errorf("context cancel should not increment error count, got %d", st.ErrCount)
	}
}

func TestParseClusterStatus(t *testing.T) {
	tests := []struct {
		name   string
		input  string
		cpuU   float64
		memT   float64
		parsed bool
	}{
		{"normal", "1.0/16.0 CPU, 0.0 GiB/44.7 GiB memory", 1.0, 44.7, true},
		{"extra spaces", "  2.0/32.0   CPU ,  1.5 GiB/64.0 GiB  memory ", 2.0, 64.0, true},
		{"empty", "", 0, 0, false},
		{"garbage", "hello world no numbers", 0, 0, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cm, parsed := ParseClusterStatus(tt.input)
			if parsed != tt.parsed {
				t.Errorf("parsed=%v want %v", parsed, tt.parsed)
			}
			if parsed && cm.CPUUsed != tt.cpuU {
				t.Errorf("cpuUsed=%v want %v", cm.CPUUsed, tt.cpuU)
			}
			if parsed && cm.MemTotal != tt.memT {
				t.Errorf("memTotal=%v want %v", cm.MemTotal, tt.memT)
			}
		})
	}
}
