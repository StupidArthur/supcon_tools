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

// newTestClient 构造指向 httptest server 的客户端。
func newTestClient(t *testing.T, handler http.Handler) *Client {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	return NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})
}

// ---- 正常路径 ----

// 测试 FetchNodes 正常解析 summary，含半哑节点（raylet 在但 mem/cpu 缺失）。
func TestFetchNodes_HappyAndPartial(t *testing.T) {
	summary := map[string]interface{}{
		"result": true,
		"data": map[string]interface{}{
			"summary": []map[string]interface{}{
				// 正常节点：raylet 是 dict，含 nodeId/state/isHeadNode/resourcesTotal
				{
					"mem":      []interface{}{16000000000.0, 13085171712.0, 18.2, 2914828288.0},
					"cpu":      1.4,
					"hostname": "head",
					"ip":       "10.166.0.249",
					"raylet": map[string]interface{}{
						"nodeId":          "7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884",
						"state":           "ALIVE",
						"isHeadNode":      true,
						"nodeManagerHostname": "head",
						"resourcesTotal":  map[string]interface{}{"CPU": 8.0, "memory": 16000000000.0},
					},
				},
				// 半哑节点：raylet 在（含 nodeId/state），但无 mem/cpu
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
		if r.URL.Path != "/nodes" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode(summary)
	}))

	nodes, err := c.FetchNodes()
	if err != nil {
		t.Fatalf("FetchNodes err: %v", err)
	}
	if len(nodes) != 2 {
		t.Fatalf("want 2 nodes, got %d", len(nodes))
	}
	// 正常节点
	if nodes[0].Hostname != "head" || nodes[0].NodeID != "7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884" {
		t.Errorf("node0 wrong: %+v", nodes[0])
	}
	if nodes[0].MemTotal != 16000000000 || nodes[0].MemUsed != 13085171712 || nodes[0].CPU != 1.4 {
		t.Errorf("node0 hardware wrong: %+v", nodes[0])
	}
	if nodes[0].IsPartial || !nodes[0].IsHead || nodes[0].State != "ALIVE" {
		t.Errorf("node0 flags wrong: %+v", nodes[0])
	}
	// 半哑节点：有 nodeId/state，但硬件为零
	if !nodes[1].IsPartial {
		t.Errorf("node1 should be partial")
	}
	if nodes[1].MemTotal != 0 || nodes[1].CPU != 0 {
		t.Errorf("partial node hardware should be zero: %+v", nodes[1])
	}
	if nodes[1].NodeID != "fa0496154f1b6dde973f4cbafc17a9be6528396ef6c2843385f9e880" {
		t.Errorf("partial node id wrong: %s", nodes[1].NodeID)
	}
	if nodes[1].State != "ALIVE" {
		t.Errorf("partial node state should come from raylet: %s", nodes[1].State)
	}
}

// 测试 FetchNodeDetail 正常解析 workers/actors，含 GPU 自适应（无卡 resourcesTotal 无 GPU key）。
func TestFetchNodeDetail_Happy(t *testing.T) {
	detail := map[string]interface{}{
		"data": map[string]interface{}{
			"detail": map[string]interface{}{
				"mem": []interface{}{16000000000.0, 13085171712.0},
				"cpu": 1.4,
				"ip":   "10.166.0.249",
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
					"nodeId": "7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884",
					"nodeManagerHostname": "head",
					"resourcesTotal": map[string]interface{}{"CPU": 16.0, "memory": 16000000000.0},
				},
			},
		},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(detail)
	}))

	d, err := c.FetchNodeDetail("7b7f32117bed397e6c0baa66c05a90758defe15a4f636f3ecf6c7884")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	// GPU 自适应：resourcesTotal 无 GPU key → 0
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
	if a.ActorClass != "ServeController" || a.State != "ALIVE" || a.NumRestarts != 0 {
		t.Errorf("actor wrong: %+v", a)
	}
	if a.NumExecTasks != 31696 {
		t.Errorf("actor numExecTasks wrong: %d", a.NumExecTasks)
	}
	if a.ExitDetail != "-" {
		t.Errorf("actor exitDetail wrong: %s", a.ExitDetail)
	}
}

// 测试 FetchCluster 正则解析 ResourceUsage 文本（CPU/内存/GPU/心跳）。
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

	cm, err := c.FetchCluster()
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

// 测试 FetchJobs 正常解析 + entrypoint 截断。
func TestFetchJobs_Happy(t *testing.T) {
	longEntry := "python " + string(make([]byte, 100)) // >80 字符
	jobs := []map[string]interface{}{
		{"job_id": "01000000", "status": "RUNNING", "start_time": 1782458409790,
			"end_time": 0, "error_type": "", "entrypoint": longEntry},
		{"job_id": "02000000", "status": "FAILED", "start_time": 1782458409790,
			"end_time": 1782458500000, "error_type": "RuntimeError", "entrypoint": "short"},
	}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(jobs)
	}))

	out, err := c.FetchJobs()
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

// ---- 空输入 ----

func TestFetchNodes_Empty(t *testing.T) {
	summary := map[string]interface{}{"result": true, "data": map[string]interface{}{"summary": []interface{}{}}}
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(summary)
	}))
	nodes, err := c.FetchNodes()
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(nodes) != 0 {
		t.Errorf("want empty, got %d", len(nodes))
	}
}

// ---- 错误输入 ----

// 非 200 返回 error。
func TestFetchNodes_HTTPError(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	if _, err := c.FetchNodes(); err == nil {
		t.Errorf("want error on 500")
	}
}

// JSON 格式非法返回 error。
func TestFetchNodes_BadJSON(t *testing.T) {
	c := newTestClient(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("not json"))
	}))
	if _, err := c.FetchNodes(); err == nil {
		t.Errorf("want error on bad json")
	}
}

// ---- 边界：事件 diff ----

// fakeStore 内存实现，记录写入的事件，用于断言 diff 逻辑。
type fakeStore struct {
	actorEvents []model.ActorEvent
	jobEvents   []model.JobEvent
	actors      []model.ActorSnapshot
}

func (f *fakeStore) WriteNodeMetrics(_ string, _ []model.NodeMetric) error       { return nil }
func (f *fakeStore) WriteWorkers(_ string, _ []model.WorkerSnapshot) error       { return nil }
func (f *fakeStore) WriteActors(_ string, a []model.ActorSnapshot) error       { f.actors = a; return nil }
func (f *fakeStore) WriteJobs(_ string, _ []model.JobSnapshot) error             { return nil }
func (f *fakeStore) WriteCluster(_ string, _ model.ClusterMetric) error          { return nil }
func (f *fakeStore) WriteActorEvents(_ string, e []model.ActorEvent) error     { f.actorEvents = append(f.actorEvents, e...); return nil }
func (f *fakeStore) WriteJobEvents(_ string, e []model.JobEvent) error         { f.jobEvents = append(f.jobEvents, e...); return nil }

// 测试 Actor 状态变迁 diff：同 ID 状态变化生成事件，不变不生成，新出现的算新增（首轮无事件）。
func TestDiffActors_StateChange(t *testing.T) {
	col := &Collector{prevActors: map[string]model.ActorSnapshot{}, store: &fakeStore{}}
	// 第一轮：两个 actor 都是 ALIVE
	first := []model.ActorSnapshot{
		{ActorID: "A1", State: "ALIVE", ActorClass: "C1"},
		{ActorID: "A2", State: "ALIVE", ActorClass: "C2"},
	}
	if e := col.diffActors(first); len(e) != 0 {
		t.Errorf("first round should have 0 events, got %d", len(e))
	}
	// 第二轮：A1 变 DEAD，A2 不变，A3 新增
	second := []model.ActorSnapshot{
		{ActorID: "A1", State: "DEAD", ActorClass: "C1", ExitDetail: "oom"},
		{ActorID: "A2", State: "ALIVE", ActorClass: "C2"},
		{ActorID: "A3", State: "ALIVE", ActorClass: "C3"},
	}
	events := col.diffActors(second)
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

// 测试 Job 状态变迁 diff。
func TestDiffJobs_StatusChange(t *testing.T) {
	col := &Collector{prevJobs: map[string]model.JobSnapshot{}, store: &fakeStore{}}
	col.diffJobs([]model.JobSnapshot{{JobID: "J1", Status: "RUNNING"}})
	events := col.diffJobs([]model.JobSnapshot{{JobID: "J1", Status: "FAILED", ErrorType: "OOMError"}})
	if len(events) != 1 || events[0].NewStatus != "FAILED" || events[0].ErrorType != "OOMError" {
		t.Errorf("job event wrong: %+v", events)
	}
}

// ---- 边界：GPU 有卡场景 ----

// resourcesTotal 含 GPU 时，节点 gpuTotal 与 actor gpuUsed 正确解析。
func TestFetchNodeDetail_WithGPU(t *testing.T) {
	detail := map[string]interface{}{
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
	d, err := c.FetchNodeDetail("n1")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if d.Node.GPUTotal != 8.0 {
		t.Errorf("gpuTotal want 8, got %v", d.Node.GPUTotal)
	}
	if len(d.Actors) != 1 || d.Actors[0].GPUUsed != 2.0 {
		t.Errorf("actor gpuUsed wrong: %+v", d.Actors)
	}
}

// 确保 Collector.Status/Snapshot 在未启动时不 panic。
func TestCollector_StatusBeforeStart(t *testing.T) {
	col := NewCollector(nil, &fakeStore{}, CollectorOpts{SummaryEvery: 15, DetailEvery: 60})
	st := col.Status()
	if st.Running {
		t.Errorf("should not be running before start")
	}
	if col.Snapshot() != nil {
		t.Errorf("snapshot should be nil before first collect")
	}
	// ctx 立即取消，Start 应立即返回（client 为 nil，但 ctx 已取消不会触发采集）
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	col.Start(ctx) // 不应阻塞/panic
}

// ---- gzip 透明解压：dashboard 支持 / 不支持 / 损坏 三场景 ----

// gzipEncode 用 gzip 压缩 + 写 Content-Encoding 头，模拟支持压缩的 dashboard。
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

// 支持 gzip 的 dashboard：响应带 Content-Encoding: gzip + gzip 流。
// 客户端应：透明解压、LastGzipUsed()=true、解析出原 JSON。
func TestFetchNodes_GzipSupported(t *testing.T) {
	payload := []byte(`{"result":true,"data":{"summary":[]}}`)
	body := gzipEncode(t, payload)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Accept-Encoding") != "gzip" {
			t.Errorf("request missing Accept-Encoding: gzip, got %q", r.Header.Get("Accept-Encoding"))
		}
		w.Header().Set("Content-Encoding", "gzip")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(body)
	}))
	t.Cleanup(srv.Close)
	c := NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})

	nodes, err := c.FetchNodes()
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

// 不支持 gzip 的 dashboard：返回明文 JSON（无 Content-Encoding 头）。
// 客户端应：直接读明文、LastGzipUsed()=false、解析正常。
func TestFetchNodes_GzipUnsupported(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// 不设 Content-Encoding
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"result":true,"data":{"summary":[]}}`))
	}))
	t.Cleanup(srv.Close)
	c := NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})

	if _, err := c.FetchNodes(); err != nil {
		t.Fatalf("FetchNodes: %v", err)
	}
	if c.LastGzipUsed() {
		t.Errorf("dashboard sent plain, but LastGzipUsed()=true")
	}
}

// 头部撒谎：响应头标 gzip 但 body 损坏。
// 客户端应：返回 error（不让坏数据进入解析层），不 panic。
func TestFetchNodes_GzipBroken(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Encoding", "gzip")
		// 写非 gzip 的字节
		_, _ = w.Write([]byte("this is not gzip"))
	}))
	t.Cleanup(srv.Close)
	c := NewClient(CollectorOpts{PlatformURL: srv.URL, TimeoutSec: 2})

	_, err := c.FetchNodes()
	if err == nil {
		t.Errorf("want error on broken gzip body, got nil")
	}
	// 错误信息应提到 gzip（便于排查）
	if !strings.Contains(err.Error(), "gzip") {
		t.Errorf("error should mention gzip, got: %v", err)
	}
}
