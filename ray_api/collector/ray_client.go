package collector

import (
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"raymonitor/logx"
	"raymonitor/model"
)

const maxResponseBytes = 64 * 1024 * 1024

type Client struct {
	clusterID string
	baseURL   string
	http      *http.Client
	cookie    string

	mu          sync.Mutex
	lastGzip    bool
	schemaByAPI map[string]string
}

func NewClient(opts CollectorOpts) *Client {
	timeout := opts.TimeoutSec
	if timeout <= 0 {
		timeout = 8
	}
	transport := &http.Transport{DisableCompression: true}
	return &Client{
		clusterID: opts.ClusterID,
		baseURL:   strings.TrimRight(opts.PlatformURL, "/"),
		http: &http.Client{
			Timeout:   time.Duration(timeout) * time.Second,
			Transport: transport,
		},
		cookie:      opts.Cookie,
		schemaByAPI: map[string]string{},
	}
}

func (c *Client) LastGzipUsed() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.lastGzip
}

func (c *Client) get(ctx context.Context, path string) ([]byte, error) {
	started := time.Now()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		c.logRequest(path, 0, started, nil, 0, err)
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Accept-Encoding", "gzip")
	if c.cookie != "" {
		req.Header.Set("Cookie", c.cookie)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		c.logRequest(path, 0, started, nil, 0, err)
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		summary := sanitizeBody(string(body))
		err := fmt.Errorf("%s: HTTP %d: %s", path, resp.StatusCode, summary)
		c.logRequest(path, resp.StatusCode, started, resp.Header, len(body), err)
		return nil, err
	}
	var reader io.Reader = resp.Body
	isGzip := resp.Header.Get("Content-Encoding") == "gzip"
	if isGzip {
		gz, gzErr := gzip.NewReader(resp.Body)
		if gzErr != nil {
			err := fmt.Errorf("gzip decode %s: %w", path, gzErr)
			c.logRequest(path, resp.StatusCode, started, resp.Header, 0, err)
			return nil, err
		}
		defer gz.Close()
		reader = gz
	}
	c.mu.Lock()
	c.lastGzip = isGzip
	c.mu.Unlock()
	data, err := io.ReadAll(io.LimitReader(reader, maxResponseBytes+1))
	if err != nil {
		c.logRequest(path, resp.StatusCode, started, resp.Header, len(data), err)
		return nil, err
	}
	if int64(len(data)) > maxResponseBytes {
		err := fmt.Errorf("%s: response exceeds 64 MiB limit", path)
		c.logRequest(path, resp.StatusCode, started, resp.Header, len(data), err)
		return nil, err
	}
	c.logRequest(path, resp.StatusCode, started, resp.Header, len(data), nil)
	c.observeSchema(path, data, resp.Header)
	return data, nil
}

func sanitizeBody(s string) string {
	s = strings.ReplaceAll(s, "\n", " ")
	s = strings.ReplaceAll(s, "\r", " ")
	if len(s) > 512 {
		s = s[:512]
	}
	return s
}

// ---- summary ----

type summaryEnvelope struct {
	Result bool `json:"result"`
	Data   struct {
		Summary []rawNode `json:"summary"`
	} `json:"data"`
}

type rawNode struct {
	Mem      []float64      `json:"mem"`
	CPU      interface{}    `json:"cpu"`
	Gpus     interface{}    `json:"gpus"`
	IP       interface{}    `json:"ip"`
	Hostname interface{}    `json:"hostname"`
	Raylet   *summaryRaylet `json:"raylet"`
}

type summaryRaylet struct {
	NodeID          string             `json:"nodeId"`
	State           string             `json:"state"`
	IsHeadNode      bool               `json:"isHeadNode"`
	NodeManagerHost string             `json:"nodeManagerHostname"`
	ResourcesTotal  map[string]float64 `json:"resourcesTotal"`
}

func (c *Client) FetchNodes(ctx context.Context) ([]model.NodeMetric, error) {
	b, err := c.get(ctx, "/nodes?view=summary")
	if err != nil {
		return nil, err
	}
	var env summaryEnvelope
	if err := json.Unmarshal(b, &env); err != nil {
		return nil, fmt.Errorf("parse summary: %w", err)
	}
	if !env.Result {
		return nil, fmt.Errorf("/nodes?view=summary: result=false")
	}
	ts := model.NowMs()
	out := make([]model.NodeMetric, 0, len(env.Data.Summary))
	for _, rn := range env.Data.Summary {
		nm := model.NodeMetric{Ts: ts}
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
			nm.State = "ALIVE"
		}
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

// ---- detail ----

type NodeDetail struct {
	Node    model.NodeMetric
	Workers []model.WorkerSnapshot
	Actors  []model.ActorSnapshot
}

type detailEnvelope struct {
	Result bool `json:"result"`
	Data   struct {
		Detail struct {
			Mem     []float64           `json:"mem"`
			CPU     interface{}         `json:"cpu"`
			IP      interface{}         `json:"ip"`
			Host    interface{}         `json:"hostname"`
			Workers []rawWorker         `json:"workers"`
			Actors  map[string]rawActor `json:"actors"`
			Raylet  struct {
				State           string             `json:"state"`
				IsHeadNode      bool               `json:"isHeadNode"`
				NodeID          string             `json:"nodeId"`
				NodeManagerHost string             `json:"nodeManagerHostname"`
				ResourcesTotal  map[string]float64 `json:"resourcesTotal"`
			} `json:"raylet"`
		} `json:"detail"`
	} `json:"data"`
}

type rawWorker struct {
	PID        int         `json:"pid"`
	JobID      interface{} `json:"jobId"`
	CPUPercent interface{} `json:"cpuPercent"`
	NumFds     interface{} `json:"numFds"`
	Language   interface{} `json:"language"`
	MemoryInfo struct {
		RSS int64 `json:"rss"`
	} `json:"memoryInfo"`
	CoreWorkerStats []coreWorkerStat `json:"coreWorkerStats"`
}

type coreWorkerStat struct {
	ActorTitle string `json:"actorTitle"`
}

type rawActor struct {
	ActorClass        string                 `json:"className"`
	Name              interface{}            `json:"name"`
	State             string                 `json:"state"`
	NumRestarts       interface{}            `json:"numRestarts"`
	JobID             string                 `json:"jobId"`
	PID               int                    `json:"pid"`
	IPAddress         string                 `json:"ipAddress"`
	NumExecutedTasks  interface{}            `json:"numExecutedTasks"`
	ExitDetail        interface{}            `json:"exitDetail"`
	RequiredResources map[string]float64     `json:"requiredResources"`
	UsedResources     map[string]interface{} `json:"usedResources"`
}

func (c *Client) FetchNodeDetail(ctx context.Context, nodeID string) (*NodeDetail, error) {
	b, err := c.get(ctx, "/nodes/"+nodeID)
	if err != nil {
		return nil, err
	}
	var env detailEnvelope
	if err := json.Unmarshal(b, &env); err != nil {
		return nil, fmt.Errorf("parse detail %s: %w", nodeID, err)
	}
	if !env.Result {
		return nil, fmt.Errorf("/nodes/%s: result=false", nodeID)
	}
	d := env.Data.Detail
	ts := model.NowMs()

	resolvedNodeID := d.Raylet.NodeID
	if resolvedNodeID == "" {
		resolvedNodeID = nodeID
		logx.L().Warn("detail raylet.nodeId empty, using request nodeID", "nodeID", nodeID)
	}

	gpuTotal := d.Raylet.ResourcesTotal["GPU"]

	nm := model.NodeMetric{
		Ts: ts, NodeID: resolvedNodeID, Hostname: toStr(d.Host), IP: toStr(d.IP),
		IsHead: d.Raylet.IsHeadNode, State: d.Raylet.State,
		CPU: toFloat(d.CPU), GPUTotal: gpuTotal,
	}
	if len(d.Mem) >= 2 {
		nm.MemTotal = int64(d.Mem[0])
		nm.MemUsed = int64(d.Mem[1])
	}

	actors := make([]model.ActorSnapshot, 0, len(d.Actors))
	gpuByPID := map[int]float64{}
	for actorID, a := range d.Actors {
		if actorID == "" {
			logx.L().Warn("actor with empty map key", "nodeID", resolvedNodeID)
		}
		gpuUsed := a.RequiredResources["GPU"]
		actors = append(actors, model.ActorSnapshot{
			Ts: ts, NodeID: resolvedNodeID, ActorID: actorID, ActorClass: a.ActorClass,
			Name: toStr(a.Name), State: a.State, NumRestarts: toInt(a.NumRestarts),
			JobID: a.JobID, PID: a.PID, IPAddress: a.IPAddress,
			NumExecTasks: toInt64(a.NumExecutedTasks), GPUUsed: gpuUsed,
			ExitDetail: toStr(a.ExitDetail),
		})
		if a.PID != 0 {
			gpuByPID[a.PID] += gpuUsed
		}
	}

	var nodeGPUUsed float64
	for _, a := range actors {
		nodeGPUUsed += a.GPUUsed
	}
	nm.GPUUsed = nodeGPUUsed

	workers := make([]model.WorkerSnapshot, 0, len(d.Workers))
	for _, w := range d.Workers {
		workers = append(workers, model.WorkerSnapshot{
			Ts: ts, NodeID: resolvedNodeID, PID: w.PID, JobID: toStr(w.JobID),
			ProcessName: workerProcessName(w.CoreWorkerStats),
			CPUPercent:  toFloat(w.CPUPercent), MemRSS: w.MemoryInfo.RSS,
			NumFds: toInt(w.NumFds), Language: toStr(w.Language),
			GPUUsed: gpuByPID[w.PID],
		})
	}

	return &NodeDetail{Node: nm, Workers: workers, Actors: actors}, nil
}

// ---- cluster_status ----

type clusterEnvelope struct {
	Result bool `json:"result"`
	Data   struct {
		AutoscalingStatus string `json:"autoscalingStatus"`
	} `json:"data"`
}

var (
	cpuRe = regexp.MustCompile(`([\d.]+)/([\d.]+)\s+CPU`)
	memRe = regexp.MustCompile(`([\d.]+)\s+GiB/([\d.]+)\s+GiB\s+memory`)
	gpuRe = regexp.MustCompile(`([\d.]+)/([\d.]+)\s+GPU`)
	hbRe  = regexp.MustCompile(`TimeSinceLastHeartbeat:\s*Min=[\d.]+\s+Mean=[\d.]+\s+Max=([\d.]+)`)
)

func ParseClusterStatus(s string) (model.ClusterMetric, bool) {
	cm := model.ClusterMetric{Ts: model.NowMs()}
	parsed := false
	if m := cpuRe.FindStringSubmatch(s); len(m) == 3 {
		cm.CPUUsed, _ = strconv.ParseFloat(m[1], 64)
		cm.CPUTotal, _ = strconv.ParseFloat(m[2], 64)
		parsed = true
	}
	if m := memRe.FindStringSubmatch(s); len(m) == 3 {
		cm.MemUsed, _ = strconv.ParseFloat(m[1], 64)
		cm.MemTotal, _ = strconv.ParseFloat(m[2], 64)
		parsed = true
	}
	if m := gpuRe.FindStringSubmatch(s); len(m) == 3 {
		cm.GPUUsed, _ = strconv.ParseFloat(m[1], 64)
		cm.GPUTotal, _ = strconv.ParseFloat(m[2], 64)
		parsed = true
	}
	if m := hbRe.FindStringSubmatch(s); len(m) == 2 {
		cm.HeartbeatMax, _ = strconv.ParseFloat(m[1], 64)
		parsed = true
	}
	return cm, parsed
}

func (c *Client) FetchCluster(ctx context.Context) (model.ClusterMetric, error) {
	b, err := c.get(ctx, "/api/cluster_status")
	if err != nil {
		return model.ClusterMetric{}, err
	}
	var env clusterEnvelope
	if err := json.Unmarshal(b, &env); err != nil {
		return model.ClusterMetric{}, fmt.Errorf("parse cluster: %w", err)
	}
	if !env.Result {
		return model.ClusterMetric{}, fmt.Errorf("/api/cluster_status: result=false")
	}
	s := env.Data.AutoscalingStatus
	cm, parsed := ParseClusterStatus(s)
	if !parsed && s != "" {
		logx.L().Warn("cluster status format unrecognized", "len", len(s))
		return model.ClusterMetric{}, fmt.Errorf("/api/cluster_status: unrecognized format")
	}
	return cm, nil
}

// ---- jobs ----

func (c *Client) FetchJobs(ctx context.Context) ([]model.JobSnapshot, error) {
	b, err := c.get(ctx, "/api/jobs/")
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
			entry = entry[:80]
		}
		out = append(out, model.JobSnapshot{
			Ts: ts, JobID: j.JobID, Status: j.Status,
			StartTime: j.StartTime, EndTime: j.EndTime,
			ErrorType: j.ErrorType, Entry: entry,
		})
	}
	return out, nil
}

// ---- helpers ----

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

func workerProcessName(stats []coreWorkerStat) string {
	if len(stats) == 0 {
		return "ray::IDLE"
	}
	title := stats[0].ActorTitle
	if title == "" {
		return "ray::IDLE"
	}
	for i, c := range title {
		if c == '(' {
			return "ray::" + title[:i]
		}
	}
	return "ray::" + title
}
