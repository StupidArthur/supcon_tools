# Ray 集群监控调研文档

> 调研对象：`http://10.30.144.41:32549` 上部署的 Ray 集群管理平台
> 调研日期：2026-06-29
> Ray 版本：2.40.0（session: `session_2026-06-26_15-13-27_781363_1`）

---

## 一、平台基本情况

- 该平台是**公司自建的 Ray 管理平台**，套在 Ray Dashboard 之前，对外通过 K8s **NodePort `32549`** 暴露。
- **内网免登**：所有接口无需 cookie / token，直接请求即可返回数据（已验证）。
  - 平台自带的 `tpt-token`（JWT）存在浏览器 cookie 中，但后端不强制校验，脚本无需处理 token 过期问题。
- 平台**只代理了部分 Ray 原生接口**，并对部分接口做了改写/接管：
  - 保留原生的：`/api/version`、`/api/cluster_status`、`/api/jobs/`
  - 改写/接管的：`/nodes`（自定义 `view=summary` 参数）、`/nodes/{id}`
  - 屏蔽/未暴露的：`/api/overview`、`/api/usage`、`/api/actors`、`/api/log_in`（均 404）

---

## 二、可用接口清单

| 接口 | 方法 | 状态 | 说明 | 数据量 |
|---|---|---|---|---|
| `/nodes?view=summary` | GET | ✅ | 所有节点的硬件监控快照 | ~147KB |
| `/nodes/{node_id}` | GET | ✅ | 单节点完整详情（含 Actor/Worker/raylet） | 较大 |
| `/api/cluster_status` | GET | ✅ | 全局调度资源、心跳、autoscaling 状态 | 小 |
| `/api/jobs/` | GET | ✅ | 作业列表、状态、entrypoint、起止时间 | 中 |
| `/api/version` | GET | ✅ | Ray 版本、commit、session 名 | 小 |
| `/api/overview` | GET | ❌ 404 | 被平台接管 | - |
| `/api/usage` | GET | ❌ 404 | 被平台接管 | - |
| `/api/actors` | GET | ❌ 404 | 被接管，Actor 数据在 `/nodes/{id}` 内 | - |

### 集群拓扑

当前集群 **3 个节点**（1 head + 2 worker）：

| 节点 | hostname | IP | 角色 | 备注 |
|---|---|---|---|---|
| node 0 | `ray-cluster-kuberay-head` | `10.166.0.249` | Head | 数据完整 |
| node 1 | - | - | Worker | **半哑节点**：只有 `raylet` 字段，agent 未上报数据 |
| node 2 | - | - | Worker | 数据完整 |

> `cluster_status` 里显示 "1 nodes" 是 autoscaler 统计口径不同，不代表集群只有 1 台，以 `/nodes` 返回的 3 个为准。

---

## 三、各接口字段说明

### 1. `/nodes?view=summary`（节点硬件快照）

返回结构：`{ result, msg, data: { summary: [ ...节点列表 ] } }`

每个节点字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `hostname` / `ip` | str | 节点主机名 / IP |
| `mem` | list[4] | `[总量, 已用, 空闲百分比, 空闲字节]` |
| `cpu` | float | CPU 负载（核数） |
| `cpus` / `gpus` | list | CPU 核数列表 / GPU 列表 |
| `disk` | dict | 磁盘分区使用情况 |
| `diskIo` / `diskIoSpeed` | list | 磁盘 I/O |
| `network` / `networkSpeed` | list | 网络流量 / 速率 |
| `loadAvg` | list | 负载均值 |
| `shm` | int | 共享内存 |
| `bootTime` / `now` | float | 启动时间 / 当前时间 |
| `raylet` | list[str] | raylet 命令行（含 `--node_id`、`--static_resource_list`） |
| `cmdline` | list | raylet 启动命令行 |
| `agent` | - | agent 信息（半哑节点缺失） |

> 注意：半哑节点（如 node 1）只有 `raylet` 一个字段，采集时需容错。

### 2. `/nodes/{node_id}`（单节点完整详情）

返回结构：`{ result, msg, data: { detail: { ... } } }`

`detail` 主要板块：

| 板块 | 字段 | 监控价值 |
|---|---|---|
| **raylet** | `state`(ALIVE/DEAD)、`isHeadNode`、`numWorkers`、`nodeTypeName`、`nodeManagerAddress` | 进程健康状态 ⭐ |
| **raylet.resourcesTotal** | dict | Ray 调度视角的资源总量（CPU/GPU/内存/对象存储），**比 mem 权威** ⭐ |
| **raylet 对象存储** | `objectStoreUsedMemory`、`objectStoreAvailableMemory`、`storeStats` | 对象存储使用 |
| **workers[]** | pid、jobId、cpuPercent、memoryInfo、numFds、language、createTime | 每个 worker 进程的资源占用与归属 job ⭐ |
| **actors{}** | key=actorId，value=39 字段的 actor 详情 | **Actor 监控全在这里** ⭐⭐ |
| **agent** | pid、cpuPercent、memoryInfo、numFds、cmdline | dashboard agent 进程健康 |
| 硬件 | mem/cpu/disk/network/loadAvg/shm | 与 summary 重复 |
| `gpus` | list | GPU 列表（head 节点为空，说明无 GPU） |

**关键发现：Actor 数据没有独立接口，而是嵌在每个节点的 `/nodes/{id}` 里。要采集全部 Actor，必须遍历每个节点。**

### 3. `/api/cluster_status`（全局调度状态）

返回示例片段：
```
ResourceUsage: 1.0/16.0 CPU, 0.0 GiB/44.7 GiB memory, 0.0 GiB/2.0 GiB object_store_memory
TimeSinceLastHeartbeat: Min=0 Mean=0 Max=0
NodeIdleSeconds: Min=0 Mean=0 Max=0
```

关键字段：

| 字段 | 含义 |
|---|---|
| `autoscalingStatus` | 文本形式的资源使用、心跳、空闲时长汇总 |
| `autoscalingError` | autoscaling 错误 |
| `clusterStatus.gcsRequestTime` | GCS 请求耗时 |

### 4. `/api/jobs/`（作业列表）

返回：作业数组，每个作业字段：

| 字段 | 含义 |
|---|---|
| `job_id` / `submission_id` | 作业 ID |
| `status` | RUNNING / SUCCEEDED / FAILED |
| `entrypoint` | 启动命令 |
| `driver_info` | 驱动节点 IP、pid |
| `start_time` / `end_time` | 起止时间（毫秒） |
| `message` / `error_type` | 错误信息 |

---

## 四、Ray 监控的四个层次

Ray 需要监控的东西分四层，从下往上越贴近业务：

```
4. 作业/应用层   Job、Actor、Serve（"我跑的东西对不对"）
3. 调度资源层    Ray 视角的 CPU/GPU/内存分配（"还剩多少能调度"）
2. 进程/节点层    head/worker/agent/raylet 健康状态（"机器活没活"）
1. 系统硬件层     CPU/内存/磁盘/网络（"机器累不累"）
```

### 第 1 层：系统硬件

每台节点机器本身的资源，`summary` 接口覆盖：
- CPU 负载、核数使用率
- 内存总量/已用/可用
- 磁盘容量、I/O 速度
- 网络带宽、速率
- 负载均值

### 第 2 层：Ray 进程健康（关键）

Ray 靠几个进程协作，任一挂掉集群就出问题：

| 进程 | 作用 | 挂了的影响 |
|---|---|---|
| GCS（在 head） | 全局状态存储：Actor 表、job 表 | 集群失忆，新作业起不来 |
| raylet（每台节点） | 本地调度、资源管理、对象传输 | 该节点掉线 |
| dashboard agent（每台节点） | 上报监控数据、日志代理 | 看不到该节点数据（node 1 半哑即此原因） |
| object store | 跨节点共享内存对象 | 数据传递失败 |

监控点：进程是否存活、重启次数、**心跳延迟**（`TimeSinceLastHeartbeat`，正常应 <几秒）。

### 第 3 层：调度资源（Ray 特色，易踩坑）

Ray 视角资源 ≠ 系统硬件资源（例如机器 16 核但 Ray 可能只调度 8 核）。要盯：
- CPU / GPU / 内存 / 对象存储：已用/总量、利用率
- **GPU 是重点**：最贵，"分配 vs 真用"经常对不上
- pending 资源：有作业在等资源分不到 → 该扩容
- 资源碎片：每台都剩一点但都不够开一个 Actor

权威数据来源：`/nodes/{id}` 的 `raylet.resourcesTotal`。

### 第 4 层：业务对象

| 对象 | 监控点 | 数据来源 |
|---|---|---|
| Job | 状态、起止时间、失败原因 | `/api/jobs/` ✅ |
| Actor | 状态(ALIVE/DEAD)、死亡原因、所在节点、重建次数 | `/nodes/{id}` 的 `actors` ✅ |
| Task | 排队数、延迟、失败数 | 需 Prometheus |
| Serve | 副本数、QPS、延迟、错误率 | 需 Serve metrics |

**Actor 死亡原因是最该报警的项**——业务常因 Actor 反复死重启导致抖动，而硬件监控一切正常。

### 第 5 层（进阶）：性能与吞吐

主要靠 Prometheus metrics（raylet 的 `metricsExportPort: 8080`）+ Grafana：
- Task/Actor 调度延迟
- 对象传输延迟、RPC 延迟
- raylet 自身 CPU 占用
- GC 时间、对象 store 驱逐次数

> 当前平台未暴露 metrics 代理，如需此层需直连 head Pod 的 `8080` 端口或接 Prometheus。

---

## 五、监控覆盖现状

| 监控层 | 监控对象 | 当前能否取数 | 数据来源 |
|---|---|---|---|
| 硬件 | CPU/内存/磁盘/网络 | ✅ | `/nodes?view=summary` |
| 进程健康 | raylet/agent/worker 状态 | ✅ | `/nodes/{id}` |
| 调度资源 | CPU/GPU/内存/对象存储 | ✅ | `/api/cluster_status` + `/nodes/{id}` |
| 业务对象-Job | 状态/失败原因 | ✅ | `/api/jobs/` |
| 业务对象-Actor | 状态/死亡原因 | ✅ | `/nodes/{id}` 的 `actors` |
| 性能/延迟 | 调度延迟/RPC/吞吐 | ❌ | 需 Prometheus（未接） |

**结论：除性能/延迟层外，Ray 该监控的对象当前接口已基本齐全。**

---

## 六、自建监控工具建议

### 采集策略（两层频率，避免给 head 加压）

| 频率 | 接口 | 用途 |
|---|---|---|
| 高频（15s） | `/nodes?view=summary` | 存硬件资源趋势 |
| 低频（60s） | 遍历 3 个 `/nodes/{id}` | 存 Actor/Worker/raylet 状态 |
| 低频（60s） | `/api/cluster_status` | 全局调度资源、心跳 |
| 低频（60s） | `/api/jobs/` | 作业状态变迁 |

> `/nodes/{id}` 单次返回较大，不宜高频轮询。

### 存储建议

- 时序数值（CPU/内存/GPU 利用率）→ SQLite / InfluxDB / TimescaleDB，带时间戳
- 业务对象事件（Actor 死亡、Job 失败）→ 单独事件表，记录状态变迁

### 告警优先级

1. 节点掉线 / 心跳延迟过大（第2层）—— 集群别瘫
2. 调度资源利用率，尤其 GPU（第3层）—— 别浪费钱
3. Job 状态变 FAILED（第4层）—— 别跑挂了不知道
4. Actor 状态变 DEAD + 死亡原因（第4层）—— 业务抖动排查

### 注意事项

- 所有接口当前免登，但平台策略可能变更，建议脚本保留可配置 cookie 的能力。
- 半哑节点（如 node 1）只有 `raylet` 字段，采集需容错。
- `cluster_status` 的节点数口径与 `/nodes` 不同，以 `/nodes` 为准。
- 轮询不宜过密，summary 已是几秒级，自建存历史 15~60s 足够。
- 这些接口都是**当前快照**，无任何历史数据，历史值必须自存。
