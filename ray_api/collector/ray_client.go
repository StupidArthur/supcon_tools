// Package collector 实现 Ray 接口的双层采集与解析。
//
// 本文件 ray_client.go 负责 HTTP 请求 Ray 平台 REST 接口并解析为 model 结构体。
// 对外接口（仅以下函数允许被 collector 包外调用）：
//
//   - NewClient(cfg) *Client
//   - (c *Client) FetchNodes() ([]NodeMetric, error)              // /nodes?view=summary 高频
//   - (c *Client) FetchNodeDetail(nodeID) (*NodeDetail, error)    // /nodes/{id} 低频
//   - (c *Client) FetchCluster() (ClusterMetric, error)           // /api/cluster_status
//   - (c *Client) FetchJobs() ([]JobSnapshot, error)              // /api/jobs/
//   - (c *Client) LastGzipUsed() bool                             // 最近一次响应是否 gzip 压缩
//
// 容错设计（对应标准§7 验收第5条）：
//   - 半哑节点（仅有 raylet 字段）硬件取零值，不报错
//   - 接口超时由 http.Client Timeout 控制，失败返回 error 由调度器记录
//   - GPU 字段自适应：resourcesTotal["GPU"] 无 key 则 0（无卡集群）
//   - Actor 资源/死因字段用候选名容错
package collector

import (
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"raymonitor/model"
)

// Client Ray 平台 REST 客户端。
type Client struct {
	baseURL string
	http    *http.Client
	cookie  string

	// lastGzip 最近一次请求是否观察到 Ray dashboard 返回 gzip 压缩。
	// 由 get() 在读完响应头后更新；供 collector 写入 ClusterMetric.GzipSupported，
	// 让首页能看出每个集群的连接压缩能力。
	mu       sync.Mutex
	lastGzip bool
}

// NewClient 构造客户端。超时取自 CollectorOpts。
// 关闭 Transport 的自动解压（DisableCompression=true）以便我们自己检测
// Content-Encoding 头，否则 Go 会解压后把该头剥掉，状态不可观测。
func NewClient(opts CollectorOpts) *Client {
	timeout := opts.TimeoutSec
	if timeout <= 0 {
		timeout = 8
	}
	transport := &http.Transport{DisableCompression: true}
	return &Client{
		baseURL: strings.TrimRight(opts.PlatformURL, "/"),
		http: &http.Client{
			Timeout:   time.Duration(timeout) * time.Second,
			Transport: transport,
		},
		cookie: opts.Cookie,
	}
}

// LastGzipUsed 最近一次 HTTP 响应是否走了 gzip 压缩。线程安全。
// dashboard 不支持 gzip 时返回 false（请求头带 Accept-Encoding 但响应未压缩）。
func (c *Client) LastGzipUsed() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.lastGzip
}

// get 发起 GET，返回原始 JSON 字节。内网免登，cookie 为空时不带。
// 主动声明 Accept-Encoding: gzip；响应若真的压缩则手动解压。
func (c *Client) get(path string) ([]byte, error) {
	req, err := http.NewRequest("GET", c.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Accept-Encoding", "gzip")
	if c.cookie != "" {
		req.Header.Set("Cookie", c.cookie)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s: HTTP %d", path, resp.StatusCode)
	}
	// 手动处理 gzip：Transport 已关自动解压，响应原样返回。
	// 头标记 gzip 但 body 损坏时返回 error（不让坏数据进入解析层）。
	var reader io.Reader = resp.Body
	isGzip := resp.Header.Get("Content-Encoding") == "gzip"
	if isGzip {
		gz, gzErr := gzip.NewReader(resp.Body)
		if gzErr != nil {
			return nil, fmt.Errorf("gzip decode %s: %w", path, gzErr)
		}
		defer gz.Close()
		reader = gz
	}
	c.mu.Lock()
	c.lastGzip = isGzip
	c.mu.Unlock()
	return io.ReadAll(reader)
}

// ---- summary 接口解析 ----

// summaryEnvelope /nodes?view=summary 的外层结构。
type summaryEnvelope struct {
	Result bool `json:"result"`
	Data   struct {
		Summary []rawNode `json:"summary"`
	} `json:"data"`
}

// rawNode summary 中单个节点的原始结构。
// 实测真实 summary 的 raylet 是 dict 对象（含 nodeId/state/isHeadNode/resourcesTotal），
// 而非命令行数组。半哑节点（agent 未上报）的 mem/cpu 等字段缺失，但 raylet 仍在。
type rawNode struct {
	Mem      []float64    `json:"mem"`      // [total, used, freePct, freeBytes]
	CPU      interface{}  `json:"cpu"`      // 数值
	Gpus     interface{}  `json:"gpus"`     // 数组
	IP       interface{}  `json:"ip"`
	Hostname interface{}  `json:"hostname"`
	Raylet   *summaryRaylet `json:"raylet"` // 节点调度层信息，半哑节点仍含
}

// summaryRaylet summary 接口 raylet 字段。与 detail 的 raylet 字段集子集一致。
type summaryRaylet struct {
	NodeID         string             `json:"nodeId"`
	State          string             `json:"state"`
	IsHeadNode     bool               `json:"isHeadNode"`
	NodeManagerHost string            `json:"nodeManagerHostname"`
	ResourcesTotal map[string]float64 `json:"resourcesTotal"`
}

// FetchNodes 拉取所有节点硬件快照。半哑节点（agent 未上报，mem/cpu 缺失）标记 IsPartial=true。
func (c *Client) FetchNodes() ([]model.NodeMetric, error) {
	b, err := c.get("/nodes?view=summary")
	if err != nil {
		return nil, err
	}
	var env summaryEnvelope
	if err := json.Unmarshal(b, &env); err != nil {
		return nil, fmt.Errorf("parse summary: %w", err)
	}
	ts := model.NowMs()
	out := make([]model.NodeMetric, 0, len(env.Data.Summary))
	for _, rn := range env.Data.Summary {
		nm := model.NodeMetric{Ts: ts}
		// raylet 提供权威的 nodeId/state/isHeadNode/GPU 总量
		if rn.Raylet != nil {
			nm.NodeID = rn.Raylet.NodeID
			nm.State = rn.Raylet.State
			nm.IsHead = rn.Raylet.IsHeadNode
			nm.GPUTotal = rn.Raylet.ResourcesTotal["GPU"]
			if nm.Hostname == "" {
				nm.Hostname = rn.Raylet.NodeManagerHost
			}
		}
		if nm.State == "" {
			nm.State = "ALIVE" // 兜底：出现在列表即视为存活
		}
		// 半哑节点：mem/cpu 字段缺失
		if len(rn.Mem) >= 2 {
			nm.MemTotal = int64(rn.Mem[0])
			nm.MemUsed = int64(rn.Mem[1])
		} else {
			nm.IsPartial = true
		}
		nm.CPU = toFloat(rn.CPU)
		if nm.Hostname == "" {
			nm.Hostname = toStr(rn.Hostname)
		}
		if nm.IP == "" {
			nm.IP = toStr(rn.IP)
		}
		out = append(out, nm)
	}
	return out, nil
}

// ---- detail 接口解析 ----

// NodeDetail 单节点详情解析结果，含 workers/actors/raylet。
type NodeDetail struct {
	Node    model.NodeMetric
	Workers []model.WorkerSnapshot
	Actors  []model.ActorSnapshot
}

// detailEnvelope /nodes/{id} 外层结构。
type detailEnvelope struct {
	Data struct {
		Detail struct {
			Mem     []float64   `json:"mem"`
			CPU     interface{} `json:"cpu"`
			IP      interface{} `json:"ip"`
			Host    interface{} `json:"hostname"`
			Workers []rawWorker  `json:"workers"`
			Actors  map[string]rawActor `json:"actors"`
			Raylet  struct {
				State          string                 `json:"state"`
				IsHeadNode     bool                   `json:"isHeadNode"`
				NodeID         string                 `json:"nodeId"`
				NodeManagerHost string                `json:"nodeManagerHostname"`
				ResourcesTotal map[string]float64     `json:"resourcesTotal"`
			} `json:"raylet"`
		} `json:"detail"`
	} `json:"data"`
}

type rawWorker struct {
	PID             int           `json:"pid"`
	JobID           interface{}   `json:"jobId"`
	CPUPercent      interface{}   `json:"cpuPercent"`
	NumFds          interface{}   `json:"numFds"`
	Language        interface{}   `json:"language"`
	MemoryInfo      struct {
		RSS int64 `json:"rss"`
	} `json:"memoryInfo"`
	CoreWorkerStats []coreWorkerStat `json:"coreWorkerStats"`
}

// coreWorkerStat worker 跑的 actor 信息，actorTitle 含类名（Ray Worker Process Name 来源）。
type coreWorkerStat struct {
	ActorTitle string `json:"actorTitle"`
}

type rawActor struct {
	ActorClass      string                 `json:"className"`
	Name            interface{}            `json:"name"`
	State           string                 `json:"state"`
	NumRestarts     interface{}            `json:"numRestarts"`
	JobID           string                 `json:"jobId"`
	PID             int                    `json:"pid"`
	IPAddress       string                 `json:"ipAddress"`
	NumExecutedTasks interface{}           `json:"numExecutedTasks"`
	ExitDetail      interface{}            `json:"exitDetail"`
	RequiredResources map[string]float64   `json:"requiredResources"`
	UsedResources   map[string]interface{} `json:"usedResources"`
}

// FetchNodeDetail 拉取单节点完整详情，解析 workers/actors。
func (c *Client) FetchNodeDetail(nodeID string) (*NodeDetail, error) {
	b, err := c.get("/nodes/" + nodeID)
	if err != nil {
		return nil, err
	}
	var env detailEnvelope
	if err := json.Unmarshal(b, &env); err != nil {
		return nil, fmt.Errorf("parse detail: %w", err)
	}
	d := env.Data.Detail
	ts := model.NowMs()

	// GPU 总量从调度资源取（无 key 则 0，自适应无卡集群）
	gpuTotal := d.Raylet.ResourcesTotal["GPU"]

	nm := model.NodeMetric{
		Ts: ts, NodeID: d.Raylet.NodeID, Hostname: toStr(d.Host), IP: toStr(d.IP),
		IsHead: d.Raylet.IsHeadNode, State: d.Raylet.State,
		CPU: toFloat(d.CPU), GPUTotal: gpuTotal,
	}
	if len(d.Mem) >= 2 {
		nm.MemTotal = int64(d.Mem[0])
		nm.MemUsed = int64(d.Mem[1])
	}

	// actors（先解析，便于按 pid 汇总 GPU 到 worker）
	actors := make([]model.ActorSnapshot, 0, len(d.Actors))
	// gpuByPID: 每个 pid（worker 进程）上 Actor 占用的 GPU 之和
	gpuByPID := map[int]float64{}
	for _, a := range d.Actors {
		gpuUsed := a.RequiredResources["GPU"] // 分配视角的 GPU 占用
		actors = append(actors, model.ActorSnapshot{
			Ts: ts, NodeID: d.Raylet.NodeID, ActorClass: a.ActorClass,
			Name: toStr(a.Name), State: a.State, NumRestarts: toInt(a.NumRestarts),
			JobID: a.JobID, PID: a.PID, IPAddress: a.IPAddress,
			NumExecTasks: toInt64(a.NumExecutedTasks), GPUUsed: gpuUsed,
			ExitDetail: toStr(a.ExitDetail),
		})
		if a.PID != 0 {
			gpuByPID[a.PID] += gpuUsed
		}
	}

	// workers：GPU 占用 = 该进程上 Actor 的 GPU 之和（按 pid 汇总）
	workers := make([]model.WorkerSnapshot, 0, len(d.Workers))
	for _, w := range d.Workers {
		workers = append(workers, model.WorkerSnapshot{
			Ts: ts, NodeID: d.Raylet.NodeID, PID: w.PID, JobID: toStr(w.JobID),
			ProcessName: workerProcessName(w.CoreWorkerStats),
			CPUPercent: toFloat(w.CPUPercent), MemRSS: w.MemoryInfo.RSS,
			NumFds: toInt(w.NumFds), Language: toStr(w.Language),
			GPUUsed: gpuByPID[w.PID],
		})
	}

	return &NodeDetail{Node: nm, Workers: workers, Actors: actors}, nil
}

// ---- cluster_status 接口解析 ----

// clusterEnvelope /api/cluster_status 外层结构。
type clusterEnvelope struct {
	Result bool `json:"result"`
	Data   struct {
		AutoscalingStatus string `json:"autoscalingStatus"`
	} `json:"data"`
}

// 资源用量行形如：ResourceUsage: 1.0/16.0 CPU, 0.0 GiB/44.7 GiB memory, ...
var (
	cpuRe   = regexp.MustCompile(`([\d.]+)/([\d.]+)\s+CPU`)
	memRe   = regexp.MustCompile(`([\d.]+)\s+GiB/([\d.]+)\s+GiB\s+memory`)
	gpuRe   = regexp.MustCompile(`([\d.]+)/([\d.]+)\s+GPU`)
	hbRe    = regexp.MustCompile(`TimeSinceLastHeartbeat:\s*Min=[\d.]+\s+Mean=[\d.]+\s+Max=([\d.]+)`)
)

// FetchCluster 解析全局调度资源与心跳。autoscalingStatus 是文本，用正则提取数值。
func (c *Client) FetchCluster() (model.ClusterMetric, error) {
	b, err := c.get("/api/cluster_status")
	if err != nil {
		return model.ClusterMetric{}, err
	}
	var env clusterEnvelope
	if err := json.Unmarshal(b, &env); err != nil {
		return model.ClusterMetric{}, fmt.Errorf("parse cluster: %w", err)
	}
	s := env.Data.AutoscalingStatus
	cm := model.ClusterMetric{Ts: model.NowMs()}
	if m := cpuRe.FindStringSubmatch(s); len(m) == 3 {
		cm.CPUUsed, _ = strconv.ParseFloat(m[1], 64)
		cm.CPUTotal, _ = strconv.ParseFloat(m[2], 64)
	}
	if m := memRe.FindStringSubmatch(s); len(m) == 3 {
		cm.MemUsed, _ = strconv.ParseFloat(m[1], 64)
		cm.MemTotal, _ = strconv.ParseFloat(m[2], 64)
	}
	if m := gpuRe.FindStringSubmatch(s); len(m) == 3 {
		cm.GPUUsed, _ = strconv.ParseFloat(m[1], 64)
		cm.GPUTotal, _ = strconv.ParseFloat(m[2], 64)
	}
	if m := hbRe.FindStringSubmatch(s); len(m) == 2 {
		cm.HeartbeatMax, _ = strconv.ParseFloat(m[1], 64)
	}
	return cm, nil
}

// ---- jobs 接口解析 ----

// FetchJobs 拉取作业列表。
func (c *Client) FetchJobs() ([]model.JobSnapshot, error) {
	b, err := c.get("/api/jobs/")
	if err != nil {
		return nil, err
	}
	var raw []struct {
		JobID     string `json:"job_id"`
		Status    string `json:"status"`
		StartTime int64  `json:"start_time"`
		EndTime   int64  `json:"end_time"`
		ErrorType string `json:"error_type"`
		Entry     string `json:"entrypoint"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		return nil, fmt.Errorf("parse jobs: %w", err)
	}
	ts := model.NowMs()
	out := make([]model.JobSnapshot, 0, len(raw))
	for _, j := range raw {
		entry := j.Entry
		if len(entry) > 80 {
			entry = entry[:80] // 截断长命令行，存库与展示更轻
		}
		out = append(out, model.JobSnapshot{
			Ts: ts, JobID: j.JobID, Status: j.Status,
			StartTime: j.StartTime, EndTime: j.EndTime,
			ErrorType: j.ErrorType, Entry: entry,
		})
	}
	return out, nil
}

// ---- 类型转换辅助（容错解析 interface{} 字段）----

func toFloat(v interface{}) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case int64:
		return float64(n)
	case string:
		f, _ := strconv.ParseFloat(n, 64)
		return f
	}
	return 0
}

func toInt(v interface{}) int {
	return int(toFloat(v))
}

func toInt64(v interface{}) int64 {
	return int64(toFloat(v))
}

func toStr(v interface{}) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprintf("%v", v)
}

// workerProcessName 从 coreWorkerStats 推导 Worker Process Name。
// 对应 Ray Dashboard 的 Worker Process Name 列：
//   - 无 actor（IDLE worker）→ ray::IDLE
//   - 有 actor → ray::类名（取 actorTitle 第一个 "(" 前的部分，如 ServeController([],...) → ServeController）
func workerProcessName(stats []coreWorkerStat) string {
	if len(stats) == 0 {
		return "ray::IDLE"
	}
	title := stats[0].ActorTitle
	if title == "" {
		return "ray::IDLE"
	}
	// actorTitle 形如 "ServeController([], {...})"，取第一个 "(" 前
	for i, c := range title {
		if c == '(' {
			return "ray::" + title[:i]
		}
	}
	return "ray::" + title
}
