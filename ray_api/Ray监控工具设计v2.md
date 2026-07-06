# Ray 监控工具 v2 设计方案（多集群 + 告警）

> 流程阶段② 设计文档。承接 v1 单集群实现，扩展为多集群 + 告警。
> 编写日期：2026-07-01
> 本文档待用户审核，审核通过后进入实现。

---

## 0. 设计目标（来自用户确认）

- 同时监控多个互相独立的 Ray 集群（URL），中等规模 5~10 个
- 集群间节点名/worker名可能重复 → 必须用 cluster_id 区分，不靠 hostname
- 请求全从本机发出 → 自带本机负荷评估
- 故障隔离：一个集群挂不影响别的；**一个 API 超时也不影响同集群其他 API**
- 共库单 SQLite，所有表加 cluster_id
- 集群列表热增减（加/删/改 URL 不重启程序，只重建对应集群采集器）
- 配置全部持久化到 exe 同级配置文件（全局配置 + 集群列表 + 每集群配置）
- 阈值两级覆盖：全局阈值 + 集群级覆盖
- 告警：单 node / 单 worker 的 CPU/MEM/GPU 超限报警

---

## 1. 配置结构

单 URL → 集群列表。共享项在外层，每集群独享项在 ClusterConfig。

```go
// 单个集群配置
type ClusterConfig struct {
    ID           string `json:"id"`           // 唯一标识（UUID 或自增）
    Name         string `json:"name"`         // 显示名，如"生产环境A"
    PlatformURL  string `json:"platformUrl"`
    Cookie       string `json:"cookie"`       // 可选
    SummaryEvery int    `json:"summaryEvery"` // 该集群 summary 间隔（秒），0=用全局
    DetailEvery  int    `json:"detailEvery"`  // 该集群 detail 间隔（秒），0=用全局
    // 集群级阈值覆盖（nil=用全局）
    Thresholds   *Thresholds `json:"thresholds,omitempty"`
}

// 全局配置
type Config struct {
    Clusters    []ClusterConfig `json:"clusters"`    // 集群列表
    DBPath      string          `json:"dbPath"`
    LogDir      string          `json:"logDir"`
    TimeoutSec  int             `json:"timeoutSec"`
    SortBy      string          `json:"sortBy"`      // cpu | gpu
    Concurrency int             `json:"concurrency"` // 每集群 detail 并发上限
    GlobalConcurrency int       `json:"globalConcurrency"` // 全局并发上限（所有集群合计）
    Thresholds  Thresholds      `json:"thresholds"`  // 全局阈值
    RecoverConsecutive int      `json:"recoverConsecutive"` // 恢复需连续低于限值的次数，默认3
}

// 阈值（百分比 0~100）
type Thresholds struct {
    NodeCPU   float64 `json:"nodeCpu"`   // 节点 CPU 报警限值
    NodeMEM   float64 `json:"nodeMem"`
    NodeGPU   float64 `json:"nodeGpu"`
    WorkerCPU float64 `json:"workerCpu"` // worker 进程 CPU 报警限值
    WorkerMEM float64 `json:"workerMem"`
    WorkerGPU float64 `json:"workerGpu"`
}
```

**配置文件**:exe 同级 `config.json`，单文件含全局配置 + 集群列表。
**旧配置迁移**:启动时检测到旧格式（有 `platformUrl` 无 `clusters`），自动迁移成 `Clusters[0]`。

---

## 2. 后端架构：CollectorManager

从单采集器 → 管理器管 N 个采集器。

```
CollectorManager
  ├─ collectors map[clusterID]*Collector   每集群独立：goroutine/快照/性能/状态/告警
  ├─ alertMgr   *AlertManager              告警引擎（共享，处理所有集群告警）
  ├─ store      *storage.Store             共享单库
  └─ globalSem  chan struct{}              全局并发信号量（所有集群合计上限）
```

### 2.1 故障隔离（用户强调）

- **集群间隔离**：每个集群独立 goroutine，互不阻塞
- **集群内 API 间隔离**：detail 内"节点详情 / cluster / jobs"彼此独立请求，一个超时不等另一个
  - 改造：当前 collectDetail 是"采完节点详情→cluster→jobs"串行；改为各自独立 goroutine + 全局信号量，全部完成后合并
- **全局并发管控**：所有集群所有请求共享 globalSem，避免 10 集群 ×并发 把本机压垮
  - 每集群也有自己的 concurrency 上限（cfg.Concurrency）
  - 实际并发 = min(集群并发上限, 全局剩余额度)

### 2.2 热增减

App 暴露：
- `AddCluster(cfg)` → 创建新 Collector，热启动，不影响其他
- `RemoveCluster(id)` → 停止并移除该 Collector
- `UpdateCluster(cfg)` → 改 URL/间隔/阈值 → 停旧的、建新的（类似 v1 的 rebuildCollector）
- 配置变更后写回 config.json

### 2.3 本机负荷自评估（全局 perf）

扩展现有 PerfMetrics 为两层：
- **单集群 perf**（已有）：每集群各自的采集耗时/慢节点/内存
- **全局 perf**（新增）：所有集群合计的请求频率、总 goroutine、本机内存、全局并发使用率
  - 概览页"全局报警"item 旁显示全局负荷，避免 N 集群压垮本机

---

## 3. 告警模块设计

### 3.1 阈值（两级覆盖）

- 全局 Thresholds（Config.Thresholds）
- 集群级覆盖（ClusterConfig.Thresholds，非 nil 则覆盖）
- 解析顺序：集群级 > 全局
- 粒度：集群级（不到单个节点/进程）

### 3.2 触发与恢复（不对称防抖）

- **报警触发**：单次采集超限即触发
- **恢复判定**：连续 N 次采集低于限值才判定恢复（N = Config.RecoverConsecutive，默认 3）
- 理由：报警要快（单次），恢复要稳（连续 N 次）

### 3.3 状态机（恢复与消除分离，确认对整条报警）

两个独立布尔维度：`recovered`（是否恢复） × `acknowledged`（是否确认）

| recovered | acknowledged | 状态 | 在报警列表显示 |
|---|---|---|---|
| 否 | 否 | 报警-未确认 | ✅ |
| 否 | 是 | 报警-已确认 | ✅ |
| 是 | 否 | 已恢复-未确认 | ✅ |
| 是 | 是 | 已消除（生命周期结束） | ❌（进历史，移出列表） |

**关键定义**：
- **恢复**：连续 N 次低于限值，自动判定。状态变化，不结束生命周期。
- **确认**：用户操作，针对整条报警（确认一次全程有效，不是确认某个状态）。
- **消除**：只有 `recovered=true 且 acknowledged=true` 才消除。消除后该报警生命周期结束，之后该对象再超限 → 新的一条报警。

**反复横跳规则**：
- 未消除期间（没同时恢复+确认过），对象反复超限/恢复，都记在**同一条报警**下，作为事件序列
- "已恢复-未确认"状态下又超限 → recovered 变回 false，状态回"报警-未确认"（确认仍对整条有效，若之前确认过则回"报警-已确认"），这条报警不结束，继续记
- 只有真正消除过，下次超限才是新报警

### 3.4 告警数据模型（历史库）

```sql
-- 报警主表：一条报警一行，活到消除
CREATE TABLE alert(
  id INTEGER PRIMARY KEY,           -- 报警 ID
  cluster_id TEXT NOT NULL,         -- 集群
  object_type TEXT NOT NULL,        -- node | worker
  object_id TEXT NOT NULL,          -- nodeId 或 pid（worker 用 nodeId+pid 组合）
  object_name TEXT,                 -- hostname / 进程标识，便于展示
  metric TEXT NOT NULL,             -- cpu | mem | gpu
  threshold REAL NOT NULL,          -- 触发时限值
  recovered INTEGER DEFAULT 0,      -- 是否恢复
  acknowledged INTEGER DEFAULT 0,   -- 是否确认
  first_trigger_ts INTEGER NOT NULL,-- 首次超限时间
  last_trigger_ts INTEGER,          -- 最近一次超限时间
  recover_ts INTEGER,               -- 恢复时间
  ack_ts INTEGER,                   -- 确认时间
  eliminated_ts INTEGER,            -- 消除时间（NULL=未消除）
  last_value REAL                   -- 最近一次实际值
);
CREATE INDEX idx_alert_cluster ON alert(cluster_id, eliminated_ts);
CREATE INDEX idx_alert_object ON alert(object_type, object_id);

-- 报警事件表：记录反复超限/恢复的事件序列
CREATE TABLE alert_event(
  ts INTEGER NOT NULL,
  alert_id INTEGER NOT NULL,
  event TEXT NOT NULL,              -- trigger | recover | acknowledge | eliminate
  value REAL,                       -- trigger 时的实际值
  FOREIGN KEY(alert_id) REFERENCES alert(id)
);
```

### 3.5 告警引擎 AlertManager

每次采集后，对每个 node/worker 的 CPU/MEM/GPU 检查阈值：

```
对每个 (集群, 对象, 指标):
  若超限:
    找该 (集群,对象,指标) 当前活着的报警（eliminated_ts IS NULL）
    若有 → 更新 last_trigger_ts, last_value，记 trigger 事件，recovered=0
    若无 → 新建一条报警，记 trigger 事件
  若低于限值:
    找当前活着的报警
    若有 → 该对象的连续低于计数 +1
      若连续计数 >= N → 标记 recovered=1, recover_ts=now，记 recover 事件，清零计数
      若已 recovered 又低于 → 维持
    若已 recovered 且超限 → recovered=0（复活到未恢复），记 trigger 事件
  若 recovered=1 且 acknowledged=1 → 消除（eliminated_ts=now），记 eliminate 事件
```

连续低于计数在内存维护（AlertManager 状态），不落库（中间态）。

### 3.6 告警 UI

- 左侧集群列表最顶上 item：「全局报警」→ 点开是所有集群未消除报警汇总
- 每集群页 tab：「概览/节点/进程/报警」中的「报警」tab = 该集群未消除报警列表
- 报警列表右键操作：
  - **确认报警**（acknowledged=1）
  - **查看对象**（跳到该节点/进程详情）
  - **复制信息**（复制报警文本）
- 报警列表只显示未消除（eliminated_ts IS NULL）的；消除的进历史查询

### 3.7 App 方法（告警相关）

- `ListAlerts(clusterID)` → 该集群未消除报警（clusterID="" 则全部）
- `AckAlert(alertID)` → 确认报警
- `GetAlertHistory(clusterID, from, to)` → 历史报警（含已消除）
- `GetGlobalPerf()` → 全局负荷评估

---

## 4. UI 重构

### 4.1 布局

```
┌─────────────┬───────────────────────────────────────┐
│ ⚠ 全局报警(3)│  [概览] [节点] [进程] [报警]    ← tab  │
│ ─────────  │───────────────────────────────────────│
│ 🔵 集群A    │                                       │
│ 🟢 集群B    │       当前 tab 内容                   │
│ 🔴 集群C    │                                       │
│ ─────────  │                                       │
│ + 添加集群  │                                       │
└─────────────┴───────────────────────────────────────┘
```

- **左侧 sidebar**：
  - 顶上「全局报警」item（带未消除计数角标）
  - 集群列表（每个带状态点：🟢正常 🟡warn 🔴有报警/挂了）
  - 底部「+ 添加集群」
- **右侧主区**：
  - 顶栏：当前集群名 + 采集状态 + 配置（全局配置/集群配置/阈值）+ 排序
  - tab：概览 / 节点 / 进程 / 报警
  - 「全局报警」item 选中时：主区显示所有集群报警汇总表（无 tab，或单 tab）

### 4.2 tab 内容（每集群）

- **概览**：v1 的两行概览（分配/实际）+ 该集群性能卡 + 在线节点
- **节点**：整行列表（节点名/类型/CPU/内存/GPU/状态）+ 可配排序
- **进程**：整行列表 + 可配排序
- **报警**：该集群未消除报警列表，右键操作

### 4.3 配置弹窗

- **全局配置**：DB/日志/超时/排序/每集群并发/全局并发/恢复连续次数/全局阈值
- **集群配置**（每集群）：名称/URL/cookie/间隔/集群级阈值覆盖
- **添加/编辑/删除集群**

---

## 5. 存储改造

所有表加 `cluster_id` 列：
- node_metric、worker_snapshot、actor_snapshot、job_snapshot、cluster_metric、actor_event、job_event
- 新增 alert、alert_event 表（见 3.4）
- 查询方法加 clusterID 过滤参数

---

## 6. 实现顺序（建议分阶段，每阶段可测）

1. **配置结构 + 迁移**：Config 重构，旧 config.json 自动迁移成 Clusters[0]，确保 v1 用户无感升级
2. **CollectorManager + 多采集器**：管理器管 N 个采集器，热增减，全局并发信号量
3. **集群内 API 隔离**：detail 内 cluster/jobs/节点详情独立请求，一个超时不阻塞其他
4. **存储加 cluster_id**：所有表加列，查询加过滤
5. **UI 重构**：左侧集群列表 + tab 布局 + 集群状态点
6. **告警引擎**：AlertManager + 阈值检查 + 状态机 + 历史库
7. **告警 UI**：报警 tab + 全局报警 + 右键操作 + 阈值配置
8. **全局负荷评估**：全局 perf + 概览展示

每阶段完成后 `wails build` 出包验证，不一次性大改。

---

## 7. 待确认 / 风险

1. **历史查询**：本文档未涉及（用户说下一轮聊）。告警历史库已设计，但通用历史查询页未设计。
2. **告警通知**：本期只在工具内显示（报警列表），不做 IM/邮件推送。未来加推送时，AlertManager 的 eliminate/trigger 事件是推送触发点。
3. **worker GPU**：worker 进程级 GPU 占用字段存在（来自 actor 的 requiredResources["GPU"]，v1 已采）。无卡集群采 0、阈值不触发；有卡集群正常报警。无需特殊处理，worker GPU 报警保留，与 node GPU 同理（GPU 自适应）。
4. **对象标识稳定性**：worker 用 nodeId+pid，pid 重启会变，可能误判为新对象。需评估是否用 workerId（/api/v0/workers 有）替代 pid。

---

## 8. 验收对照（标准 §7）

多集群 + 告警完成后：
- 多集群独立采集、故障隔离 ✅
- 集群热增减 ✅
- 两级阈值告警、4 状态、恢复/消除分离、确认对整条 ✅
- 告警历史库 ✅
- 本机负荷自评估 ✅
- UI 集群列表 + tab + 全局报警 ✅

不含（后续）：通用历史查询页、IM 推送。
