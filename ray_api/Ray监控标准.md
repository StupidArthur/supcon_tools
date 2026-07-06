# Ray 集群监控标准 v1.0

> 编写日期:2026-06-29
> 适用范围:基于 KubeRay 部署的 Ray 集群(当前参照集群:`10.30.144.41:32549`,Ray 2.40.0)
> 文档定位:规定"应当如何监控 Ray"的标准,作为后续监控工具(界面化、历史存储、查询、告警)的设计与验收依据。

---

## 0. 关于本标准的背书说明

本标准的指标选取与方法论,以下列权威来源为依据。**因编写环境网络受限,未能联网核验官方页面,以下引用基于公开稳定版本,指标名请以你们实际 Ray 版本(2.40.0)官方文档为准复核。**

| 标准来源 | 提出者/出处 | 在本标准中的作用 |
|---|---|---|
| **USE 方法** | Brendan Gregg(N Netflix/Sun 资深性能工程师)| 资源类指标(CPU/内存/GPU/磁盘/对象存储)的监控框架 |
| **四大黄金信号**(Four Golden Signals) | Google SRE Book 第 6 章《Monitoring Distributed Systems》| 服务整体健康度的监控框架 |
| **RED 方法** | Tom Wilkie(Prometheus 作者之一)| 请求驱动型服务(Job/Serve)的监控框架 |
| **Ray 官方观测性体系** | Ray 项目官方文档(Ray Observability)| Ray 特有对象(Actor/raylet/GCS/调度)的监控对象与指标名依据 |

### 三套方法论的关系

```
资源怎么用?        → USE 方法(Utilization / Saturation / Errors)
服务健不健康?      → 四大黄金信号(Latency / Traffic / Errors / Saturation)
请求类服务怎么样?  → RED 方法(Rate / Errors / Duration)
```

三者不互斥,而是**按监控对象选用**:Ray 的"机器资源"用 USE,"作业/服务"用 RED,整体健康用黄金信号兜底。本标准把 Ray 的监控对象逐一映射到这三套方法。

---

## 1. 监控方法论框架(如何套用到 Ray)

### 1.1 USE 方法 —— 用于"资源"

每一个资源按三个维度看:

| 维度 | 含义 | Ray 例子 |
|---|---|---|
| **Utilization**(利用率) | 资源 busy 的时间/容量比例 | CPU 利用率、内存占用比、GPU 分配率 |
| **Saturation**(饱和度) | 资源排队/等待程度 | pending 任务数、对象存储满载度 |
| **Errors**(错误) | 资源自身报错 | OOM、磁盘满、对象 store 驱逐 |

> USE 的核心判断:**Utilization 高不一定有问题,Saturation 高才是真问题**。CPU 100% 但没排队 = 满负荷正常;CPU 50% 但任务大量 pending = 调度出了问题。

### 1.2 四大黄金信号 —— 用于"整体服务健康"

| 信号 | 含义 | Ray 对应 |
|---|---|---|
| **Latency**(延迟) | 请求处理耗时 | 任务调度延迟、Actor 创建延迟、推理延迟 |
| **Traffic**(流量) | 服务承载量 | 提交的 Job 数、Serve QPS |
| **Errors**(错误) | 错误率 | Job FAILED、Actor DEAD、RPC 失败 |
| **Saturation**(饱和度) | 资源有多满 | 调度资源利用率、队列长度 |

### 1.3 RED 方法 —— 用于"请求驱动型服务"(Job / Serve)

| 维度 | 含义 |
|---|---|
| **Rate**(速率) | 单位时间请求/作业量 |
| **Errors**(错误) | 失败比例 |
| **Duration**(耗时) | 处理时长分布 |

---

## 2. Ray 监控对象分层与指标清单

按"必须 / 建议 / 可选"三级标注优先级。**"必须"是监控工具上线即应满足的最低要求。**

### 第 1 层:系统硬件资源(USE 方法)

| 指标 | 维度 | 优先级 | 采集来源(本集群) |
|---|---|---|---|
| CPU 利用率 | Utilization | 必须 | `/nodes?view=summary` → `cpu` |
| 内存利用率(已用/总量) | Utilization | 必须 | `/nodes?view=summary` → `mem[total,used]` |
| 磁盘利用率 | Utilization | 必须 | `/nodes/{id}` → `disk` |
| 磁盘 I/O | Saturation | 建议 | `/nodes?view=summary` → `diskIo` |
| 网络流量/速率 | - | 建议 | `/nodes?view=summary` → `network` |
| 负载均值 | Saturation | 建议 | `/nodes?view=summary` → `loadAvg` |
| GPU 分配率(有GPU时) | Utilization | 必须(有GPU时) | `/nodes/{id}` → `raylet.resourcesTotal["GPU"]` |

> ⚠️ **GPU 真实利用率(显存占用、GPU 计算百分比)不在 Ray 接口范围**,需 `nvidia-smi`/DCGM exporter,属系统层补充监控,本标准列为"扩展项",见 §5。

### 第 2 层:Ray 进程健康

| 指标 | 优先级 | 采集来源 |
|---|---|---|
| raylet 进程状态(ALIVE/DEAD) | 必须 | `/nodes/{id}` → `raylet.state` |
| 节点心跳延迟 | 必须 | `/api/cluster_status` → `TimeSinceLastHeartbeat` |
| GCS 存活 | 必须 | `/api/cluster_status`(gcsRequestTime 成功即存活) |
| dashboard agent 上报完整性(是否有半哑节点) | 必须 | `/nodes?view=summary`(仅含 `raylet` 字段者为半哑) |
| worker 进程数 | 建议 | `/nodes/{id}` → `workers[]` 数量 |
| agent/raylet 进程 CPU/内存 | 建议 | `/nodes/{id}` → `agent` / `raylet` |

### 第 3 层:调度资源(USE 方法,Ray 调度视角)

| 指标 | 维度 | 优先级 | 采集来源 |
|---|---|---|---|
| 调度资源总量(CPU/GPU/内存/对象存储) | 容量基线 | 必须 | `/nodes/{id}` → `raylet.resourcesTotal` |
| 调度资源已用/可用 | Utilization | 必须 | `/api/cluster_status` → ResourceUsage |
| pending 任务数(排队) | Saturation | 必须 | Prometheus `ray_scheduler_*`(REST 无,**见 §6 差距**) |
| 对象存储使用率 | Utilization | 建议 | `/nodes/{id}` → `objectStoreUsedMemory` / `objectStoreAvailableMemory` |
| 资源碎片(每节点剩余不足以开 Actor) | Saturation | 可选 | 由 `resourcesTotal` 与各 Actor 占用推算 |

### 第 4 层:业务对象

#### 4.1 Job(RED 方法)

| 指标 | RED 维度 | 优先级 | 采集来源 |
|---|---|---|---|
| Job 数量(按状态分布) | Rate | 必须 | `/api/jobs/` |
| Job 状态变迁(→FAILED) | Errors | 必须 | `/api/jobs/` → `status` |
| Job 运行时长 | Duration | 必须 | `/api/jobs/` → `start_time`/`end_time` |
| Job 失败原因 | Errors | 必须 | `/api/jobs/` → `error_type`/`message` |

#### 4.2 Actor(死亡监控是 Ray 特色,必须)

| 指标 | 优先级 | 采集来源 |
|---|---|---|
| Actor 总数(按状态 ALIVE/DEAD/...) | 必须 | `/nodes/{id}` → `actors{}` |
| Actor 状态变迁(→DEAD) | 必须 | `/nodes/{id}` → `actors{}` → `state` |
| Actor 死亡原因 | 必须 | `/nodes/{id}` → `actors{}` → death 相关字段(39字段之一) |
| Actor 所在节点/worker | 建议 | `/nodes/{id}` → `actors{}` |
| Actor 重启次数 | 建议 | `/nodes/{id}` → `actors{}` → `numRestarts` 类字段 |
| Actor 资源占用(含GPU) | 建议 | `/nodes/{id}` → `actors{}` → `requiredResources`/`usedResources` |

#### 4.3 Worker 进程(管算法场景的核心)

| 指标 | 优先级 | 采集来源 |
|---|---|---|
| 每个 worker 进程 CPU/内存占用 | 必须 | `/nodes/{id}` → `workers[]` → `cpuPercent`/`memoryInfo` |
| worker 归属 Job | 必须 | `/nodes/{id}` → `workers[]` → `jobId` |
| worker fd 数(连接泄漏排查) | 建议 | `/nodes/{id}` → `workers[]` → `numFds` |

### 第 5 层:服务性能(RED 方法,需 Prometheus)

| 指标 | 优先级 | 采集来源 |
|---|---|---|
| 任务调度延迟 | 建议(有在线服务时必须) | Prometheus `ray_scheduler_*` |
| RPC/对象传输延迟 | 建议 | Prometheus `ray_rpc_*`/`ray_object_*` |
| Serve QPS / 延迟 / 错误率 | 必须(用 Ray Serve 时) | Prometheus `ray_serve_*` |
| raylet 自身 CPU 占用 | 建议 | Prometheus |

> **本集群现状**:平台 NodePort(32549)未代理 `/metrics`,第 5 层数据当前不可得,见 §6。

---

## 3. 每个指标"怎么监控"——采集方式映射

按数据来源分三类,工具实现时对应三种采集器:

### 3.1 REST API 采集(当前可用,工具主数据源)

| 接口 | 频率 | 采集内容 | 覆盖指标层 |
|---|---|---|---|
| `/nodes?view=summary` | 高频 15s | 节点硬件快照 | 第1层 |
| `/nodes/{id}`(遍历每节点) | 低频 60s | raylet状态、调度资源、对象存储、workers、actors | 第2/3/4层 |
| `/api/cluster_status` | 低频 60s | 全局调度资源、心跳、autoscaling | 第2/3层 |
| `/api/jobs/` | 低频 60s | 作业列表与状态 | 第4层 Job |
| `/api/version` | 启动时1次 | 版本/会话校验 | 元信息 |

**双层频率原因**:`summary` 轻量适合高频拉硬件趋势;`/nodes/{id}` 返回大(单次 100KB+),低频拉业务对象即可,避免给 head 节点施压。

### 3.2 Prometheus metrics 采集(当前不可用,扩展项)

- 数据源:head Pod 内 raylet `metricsExportPort: 8080` → `/metrics`
- 当前障碍:平台未代理该端口,需 `kubectl port-forward` 或直连 Pod
- 覆盖:第 5 层性能指标 + 第 3 层 pending 任务数
- 指标名(2.x,需按 2.40.0 复核):`ray_node_cpu_utilization_percentage`、`ray_node_actors{state=...}`、`ray_scheduler_running_tasks`、`ray_object_store_memory`、`ray_serve_num_http_requests` 等

### 3.3 日志采集(扩展项)

- 失败作业/Actor 的详细堆栈,REST 只给 `error_type`/`message` 概要
- 数据源:Ray Dashboard 日志接口或直接读 Pod 日志
- 当前列为扩展项,工具 v1 不强制

---

## 4. 告警标准与阈值

告警优先级沿用前文场景映射,阈值给初值,需按实际负载调优:

| 告警 | 触发条件(初值) | 级别 | 数据来源 |
|---|---|---|---|
| 节点掉线 | `raylet.state != ALIVE` | P0 | `/nodes/{id}` |
| 心跳超时 | `TimeSinceLastHeartbeat > 30s` | P0 | `/api/cluster_status` |
| GCS 不可达 | `cluster_status` 请求失败或 gcsRequestTime 异常 | P0 | `/api/cluster_status` |
| Job 失败 | 任一 Job `status → FAILED` | P1 | `/api/jobs/` |
| Actor 死亡 | 任一 Actor `state → DEAD` | P1 | `/nodes/{id}` |
| Actor 频繁重启 | 单 Actor `numRestarts` 单位时间 > N | P1 | `/nodes/{id}` |
| 资源饱和 | 调度资源可用 < 总量 10%,持续 2min | P2 | `/api/cluster_status` |
| 内存压力 | 节点内存可用率 < 15% | P2 | `/nodes?view=summary` |
| 磁盘压力 | 磁盘利用率 > 90% | P2 | `/nodes/{id}` |
| 半哑节点 | 节点仅有 `raylet` 字段,持续 > 5min | P2 | `/nodes?view=summary` |
| GPU 分配率异常(有GPU时) | 已分配率 > 95% 或 < 20%(可能配置问题) | P2 | `resourcesTotal` |

> P0=集群不可用;P1=业务受损;P2=容量风险。工具应支持阈值可配置。

---

## 5. GPU 监控专项说明

由于当前集群无 GPU,但未来集群可能有,标准做如下约定:

| 维度 | 含义 | 数据来源 | 本工具是否覆盖 |
|---|---|---|---|
| **GPU 分配**(调度视角) | 卡分给了谁、剩几张 | Ray 接口 `resourcesTotal["GPU"]` + Actor 资源 | ✅ 覆盖(自适应,无卡时采0) |
| **GPU 真实利用率** | 显存占用、GPU 计算率 | `nvidia-smi` / DCGM exporter | ❌ 扩展项,不在 Ray 接口范围 |

**GPU 采集自适应约定**:代码不得写死 GPU 字段,用 `resources.get("GPU", 0)` 容错;Actor 内 GPU 字段候选名 `requiredResources`/`usedResources`/`resources` 依次尝试。无卡集群采到空/0,有卡集群自动生效,无需改码。

---

## 6. 历史数据存储标准

| 项 | 标准 |
|---|---|
| 时序数据采样粒度 | 硬件 15s,业务对象 60s |
| 时序数据保留 | 原始 7 天;1分钟聚合保留 30 天;1小时聚合保留 1 年(可配置) |
| 事件数据(Job/Actor 状态变迁) | 全量保留 90 天,记录变迁前后状态与原因 |
| 存储引擎 | SQLite(轻量起步)/ TimescaleDB / InfluxDB(生产) |
| 数据完整性 | 采集失败需记录缺口(不静默丢),补采集容错半哑节点 |

---

## 7. 验收标准(监控工具达到以下即合格)

工具上线需满足全部"必须"项:

1. **覆盖度**:§2 所有标注"必须"的指标均有采集与展示。
2. **双层频率**:硬件高频(≤30s)、业务对象低频(≤120s),不混用。
3. **历史存储**:时序数据可回溯至少 7 天,支持时间范围查询与聚合。
4. **告警**:§4 的 P0/P1 告警全部生效,支持阈值配置与通知。
5. **容错**:半哑节点、接口超时、字段缺失不导致采集中断。
6. **GPU 自适应**:无卡集群正常运行,有卡集群自动采集分配数据。
7. **可视化**:节点/进程/Actor/Job 四级视图,趋势图 + 当前态 + 事件流。
8. **查询**:支持按节点、Job、Actor、时间范围检索历史。

### 验收分级

- **MVP(第一版)**:满足 1/3/5/7 的硬件+Job+Actor+节点视图,即前 4 层 REST 可得指标 + 历史 + 看板。
- **完整版**:补齐告警(2/4/8)、GPU 自适应(6)、第 5 层性能(需 Prometheus 接入)。

---

## 8. 与当前集群现状的差距分析

| 标准要求 | 当前状态 | 差距与对策 |
|---|---|---|
| 第1层 硬件 | ✅ `/nodes?view=summary` 可得 | 无 |
| 第2层 进程健康 | ✅ `/nodes/{id}` + `cluster_status` 可得 | 半哑节点需容错 |
| 第3层 调度资源(总量/已用) | ✅ 可得 | 无 |
| 第3层 pending 任务数 | ❌ REST 无 | 需 Prometheus,列为扩展 |
| 第4层 Job | ✅ `/api/jobs/` 可得 | 无 |
| 第4层 Actor | ✅ `/nodes/{id}` 内 `actors{}` 可得 | 需确认39字段中死亡原因/资源字段确切名 |
| 第4层 Worker 进程 | ✅ `/nodes/{id}` 内 `workers[]` 可得 | 无 |
| 第5层 服务性能 | ❌ 平台未代理 `/metrics` | 需 `kubectl port-forward` 8080 或接 Prometheus;在线运行时场景必须补 |
| GPU 监控 | ⚠️ 当前集群无卡 | 接口预留自适应,有卡集群自动生效;真实利用率需 DCGM |
| 告警 | ❌ 无 | 工具需新建 |
| 历史存储 | ❌ 现有接口仅当前快照 | 工具需自建存储 |

**结论**:除"第3层 pending 任务数"和"第5层服务性能"需 Prometheus 外,**标准中其余"必须"项当前 REST 接口均可覆盖**。MVP 版本可完全基于现有接口实现。

---

## 附:方法论到 Ray 的速查表

```
要回答的问题                    用什么方法    监控哪些
─────────────────────────────────────────────────────────────────
机器资源用得怎么样?            USE           CPU/内存/GPU/磁盘利用率+饱和
Ray 进程活不活?                (健康检查)    raylet.state / 心跳 / GCS
资源够不够再塞任务?            USE(饱和)    调度资源可用量 / pending 任务
作业跑得对不对?                RED           Job 状态/失败/耗时
Actor 有没有反复死?            (Ray特色)    Actor DEAD + 死因 + 重启次数
服务快不快?                    RED(性能)    调度延迟/RPC/Serve QPS — 需Prometheus
```

---

## 参考来源

- Google SRE Book, Chapter 6《Monitoring Distributed Systems》—— Four Golden Signals
- Brendan Gregg, The USE Method
- Tom Wilkie, The RED Method
- Ray Official Documentation — Ray Observability / Ray Metrics(docs.ray.io)

> ⚠️ 因编写环境网络受限,未能联网核验上述页面,引用基于公开稳定版本。指标名请对照 Ray 2.40.0 官方文档复核。
