// Package model 定义 Ray 监控工具的全部数据结构。
//
// 这些结构体既是采集器从 Ray REST 接口解析出的中间表示，
// 也是 storage 层落库的字段来源，以及 app.go 暴露给前端 Wails 绑定的传输对象。
// 因此所有字段都带 json tag。
//
// 字段命名依据：实际抓取 10.30.144.41:32549 集群的 /nodes?view=summary、
// /nodes/{id}、/api/cluster_status、/api/jobs/ 返回结构定稿（见设计文档 §7）。
package model

import "time"

// NodeMetric 节点级硬件与时序指标（高频 15s 采集，对应标准第1层）。
// 来源 /nodes?view=summary。半哑节点（仅 raylet 字段）的硬件字段为零值。
type NodeMetric struct {
	Ts        int64   `json:"ts"`         // 采集时间戳（毫秒）
	ClusterID  string  `json:"clusterId"`  // 所属集群
	NodeID    string  `json:"nodeId"`     // raylet --node_id
	Hostname  string  `json:"hostname"`   // 节点主机名
	IP        string  `json:"ip"`         // 节点 IP
	IsHead    bool    `json:"isHead"`     // 是否 head 节点
	State     string  `json:"state"`      // ALIVE / DEAD，半哑节点从 raylet 推断
	CPU       float64 `json:"cpu"`        // CPU 负载（核数）
	MemTotal  int64   `json:"memTotal"`   // 内存总量（字节）
	MemUsed   int64   `json:"memUsed"`    // 内存已用（字节）
	GPUTotal  float64 `json:"gpuTotal"`   // GPU 总数（无卡为 0）
	GPUUsed   float64 `json:"gpuUsed"`    // GPU 已分配（无卡为 0）
	IsPartial bool    `json:"isPartial"`  // 是否半哑节点（agent 未上报）
}

// WorkerSnapshot worker 进程快照（低频 60s，对应标准第4层 worker）。
// 来源 /nodes/{id} 的 workers[]。
type WorkerSnapshot struct {
	Ts         int64   `json:"ts"`
	ClusterID  string  `json:"clusterId"`  // 所属集群
	NodeID     string  `json:"nodeId"`
	PID        int     `json:"pid"`
	JobID      string  `json:"jobId"`
	ProcessName string  `json:"processName"` // Worker Process Name：ray::类名 或 ray::IDLE
	CPUPercent float64 `json:"cpuPercent"`
	MemRSS     int64   `json:"memRss"`   // 常驻内存（字节）
	NumFds     int     `json:"numFds"`   // 文件描述符数（连接泄漏排查）
	Language   string  `json:"language"` // PYTHON 等
	GPUUsed    float64 `json:"gpuUsed"`  // 该进程上 Actor 占用的 GPU 之和（按 pid 汇总，无卡为 0）
}

// ActorSnapshot Actor 快照（低频 60s，对应标准第4层 Actor）。
// 来源 /nodes/{id} 的 actors{}。字段名依据实测 39 字段结构定稿：
// state/exitDetail/numRestarts 用于死亡监控，requiredResources/usedResources/gpus 用于资源占用。
type ActorSnapshot struct {
	Ts           int64   `json:"ts"`
	ClusterID  string  `json:"clusterId"`  // 所属集群
	NodeID       string  `json:"nodeId"`
	ActorID      string  `json:"actorId"`
	ActorClass   string  `json:"actorClass"`   // className / actorClass
	Name         string  `json:"name"`         // 如 SERVE_CONTROLLER_ACTOR
	State        string  `json:"state"`        // ALIVE / DEAD / ...
	NumRestarts  int     `json:"numRestarts"`  // 重启次数
	JobID        string  `json:"jobId"`
	PID          int     `json:"pid"`
	IPAddress    string  `json:"ipAddress"`
	NumExecTasks int64   `json:"numExecTasks"` // 已执行任务数
	GPUUsed      float64 `json:"gpuUsed"`      // 占用 GPU 数（无卡为 0）
	ExitDetail   string  `json:"exitDetail"`   // 死亡原因
}

// JobSnapshot 作业快照（低频 60s，对应标准第4层 Job）。
// 来源 /api/jobs/。
type JobSnapshot struct {
	Ts        int64  `json:"ts"`
	ClusterID  string  `json:"clusterId"`  // 所属集群
	JobID     string `json:"jobId"`
	Status    string `json:"status"`    // RUNNING / SUCCEEDED / FAILED
	StartTime int64  `json:"startTime"` // 毫秒
	EndTime   int64  `json:"endTime"`   // 毫秒，0 表示未结束
	ErrorType string `json:"errorType"`
	Entry     string `json:"entry"` // entrypoint 摘要
}

// ClusterMetric 集群级调度资源与时序（低频 60s，对应标准第2/3层）。
// 来源 /api/cluster_status 的 ResourceUsage 文本与心跳。
// 注意：autoscaler 文本统计口径与 /nodes 不同，节点数以 /nodes 为准。
type ClusterMetric struct {
	Ts           int64   `json:"ts"`
	ClusterID  string  `json:"clusterId"`  // 所属集群
	CPUTotal     float64 `json:"cpuTotal"`
	CPUUsed      float64 `json:"cpuUsed"`
	MemTotal     float64 `json:"memTotal"`     // GiB
	MemUsed      float64 `json:"memUsed"`      // GiB
	GPUTotal     float64 `json:"gpuTotal"`
	GPUUsed      float64 `json:"gpuUsed"`
	HeartbeatMax float64 `json:"heartbeatMax"` // 最大心跳延迟（秒），超 30s 告警
	// GzipSupported 最近一轮采集是否观察到 Ray dashboard 返回 gzip 压缩。
	// 用于首页展示"是否启用 HTTP 压缩"，方便判断带宽优化是否对每个集群生效。
	// 由 collector 在 FetchCluster 成功后写入；transport 关闭自动解压以确保
	// 状态可观测（见 collector/ray_client.go 的 Transport 配置）。
	GzipSupported bool `json:"gzipSupported"`
}

// ActorEvent Actor 状态变迁事件（全量保留，对应标准第4层告警依据）。
// 由采集器对比上一轮快照生成：状态变化时插入一条。
type ActorEvent struct {
	Ts          int64  `json:"ts"`
	ClusterID  string  `json:"clusterId"`  // 所属集群
	ActorID     string `json:"actorId"`
	ActorClass  string `json:"actorClass"`
	PrevState   string `json:"prevState"`
	NewState    string `json:"newState"`
	DeathCause  string `json:"deathCause"` // = exitDetail
}

// JobEvent Job 状态变迁事件（全量保留）。
type JobEvent struct {
	Ts         int64  `json:"ts"`
	ClusterID  string  `json:"clusterId"`  // 所属集群
	JobID      string `json:"jobId"`
	PrevStatus string `json:"prevStatus"`
	NewStatus  string `json:"newStatus"`
	ErrorType  string `json:"errorType"`
}

// CollectorStatus 采集器运行状态，前端顶部状态灯用。
type CollectorStatus struct {
	Running       bool   `json:"running"`
	LastSuccessTs int64  `json:"lastSuccessTs"` // 上次成功采集时间
	ErrCount      int    `json:"errCount"`
	LastError     string `json:"lastError"`
}

// GlobalPerf 全局负荷评估：汇总所有集群，避免 N 集群压垮本机。
type GlobalPerf struct {
	ClusterCount      int    `json:"clusterCount"`      // 集群总数
	RunningClusters   int    `json:"runningClusters"`   // 正在采集的集群数
	ClustersWithError int    `json:"clustersWithError"` // 有错误的集群数
	TotalNodes        int    `json:"totalNodes"`        // 所有集群节点合计
	TotalWorkers      int    `json:"totalWorkers"`      // 所有集群 worker 合计
	TotalActors       int    `json:"totalActors"`       // 所有集群 Actor 合计
	TotalDetailReqs   int    `json:"totalDetailReqs"`   // 所有集群最近一轮 detail 请求合计
	MaxDetailMs       int64  `json:"maxDetailMs"`       // 最慢集群的 detail 耗时
	GlobalConcurrency int    `json:"globalConcurrency"` // 全局并发上限
	ProcMemBytes      uint64 `json:"procMemBytes"`      // 本机进程内存
	ProcGoroutine     int    `json:"procGoroutine"`     // 本机 goroutine 数
	UpdatedAt         int64  `json:"updatedAt"`
}

// PerfMetrics 采集器自身性能评估，供概览页展示，用于决策是否需要改架构。
// 所有耗时单位毫秒，内存单位字节。
type PerfMetrics struct {
	// 耗时（最近一轮）
	SummaryMs      int64 `json:"summaryMs"`      // 上一轮 summary 采集耗时
	DetailMs       int64 `json:"detailMs"`       // 上一轮 detail 采集耗时
	DetailNodesMs  int64 `json:"detailNodesMs"`  // detail 中"拉所有节点详情"阶段耗时（并发）
	DetailMaxNodeMs int64 `json:"detailMaxNodeMs"` // detail 中最慢单节点请求耗时（反映瓶颈）

	// 负载
	NodeCount    int   `json:"nodeCount"`    // 本轮采集的节点数
	WorkerCount  int   `json:"workerCount"`  // 本轮 worker 进程数
	ActorCount   int   `json:"actorCount"`   // 本轮 Actor 数
	DetailReqs   int   `json:"detailReqs"`   // 本轮 detail 发起的 HTTP 请求数

	// 慢节点定位（解决"4秒慢"问题的直接线索）
	SlowNodeID   string `json:"slowNodeId"`   // 最慢节点 ID
	SlowNodeHost string `json:"slowNodeHost"` // 最慢节点 hostname
	SlowNodeMs   int64  `json:"slowNodeMs"`   // 最慢节点请求耗时

	// 采集器进程自身（Go runtime）
	ProcMemBytes uint64 `json:"procMemBytes"` // 进程当前内存（HeapAlloc）
	ProcGoroutine int   `json:"procGoroutine"`// goroutine 数
	Concurrency  int    `json:"concurrency"`  // 当前并发上限配置

	// 风险评估（采集器自评，给前端提示用）
	Risk string `json:"risk"` // ok | warn | danger
}

// Overview 概览页聚合数据。
type Overview struct {
	Cluster   ClusterMetric   `json:"cluster"`
	Nodes     []NodeMetric    `json:"nodes"`
	NodeCount int             `json:"nodeCount"` // 在线节点数
	RecentJobs []JobSnapshot  `json:"recentJobs"`
	UpdatedAt int64           `json:"updatedAt"`
}

// NowMs 当前时间毫秒戳。封装一处，避免散落的 time.Now().UnixMilli()。
func NowMs() int64 { return time.Now().UnixMilli() }

// Alert 一条报警。活着到消除（recovered && acknowledged）。
// 状态由 recovered × acknowledged 两维决定：
//   (false,false)=报警-未确认  (false,true)=报警-已确认
//   (true,false)=已恢复-未确认 (true,true)=已消除
type Alert struct {
	ID            int64   `json:"id"`
	ClusterID     string  `json:"clusterId"`
	ClusterName   string  `json:"clusterName"`   // 集群名（URL host:port），全局报警定位用
	NodeName      string  `json:"nodeName"`      // 对象所在节点名，定位用
	ObjectType    string  `json:"objectType"`    // node | worker
	ObjectID      string  `json:"objectId"`      // node: nodeId；worker: nodeId+":"+pid
	ObjectName    string  `json:"objectName"`    // 展示用：进程名(hostname 在 nodeName)
	Metric        string  `json:"metric"`        // cpu | mem | gpu
	Threshold     float64 `json:"threshold"`     // 触发时限值（%）
	Recovered     bool    `json:"recovered"`
	Acknowledged  bool    `json:"acknowledged"`
	FirstTriggerTs int64  `json:"firstTriggerTs"`
	LastTriggerTs  int64  `json:"lastTriggerTs"`
	RecoverTs      int64  `json:"recoverTs"`
	AckTs          int64  `json:"ackTs"`
	EliminatedTs   int64  `json:"eliminatedTs"` // 0=未消除
	LastValue      float64 `json:"lastValue"`   // 最近一次实际值（%）
}

// AlertEvent 报警事件序列（反复超限/恢复/确认/消除）。
type AlertEvent struct {
	Ts      int64   `json:"ts"`
	AlertID int64   `json:"alertId"`
	Event   string  `json:"event"` // trigger | recover | acknowledge | eliminate
	Value   float64 `json:"value"`
}

// AlertStateStr 报警状态文案，供前端展示。
func (a Alert) StateStr() string {
	switch {
	case a.EliminatedTs != 0:
		return "已消除"
	case a.Recovered && a.Acknowledged:
		return "已消除"
	case a.Recovered:
		return "已恢复-未确认"
	case a.Acknowledged:
		return "报警-已确认"
	default:
		return "报警-未确认"
	}
}
