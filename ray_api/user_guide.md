# Ray 集群监控（raymonitor）用户手册

> 桌面 GUI 工具，同时监控多个 Ray 集群（KubeRay 部署）：节点/进程/Actor/Job 的当前态与历史时序 + 4 状态告警引擎 + SQLite 历史。
>
> **当前版本**：v0.92（4 集群 × 18 节点生产在用）
>
> designed by yzc

---

## 1. 这是什么

Ray 集群监控（内部代号 `raymonitor`）是一款 Wails v2 桌面应用，作用是：

- **同时监控多个 Ray 集群**：在同一个窗口里看 N 个集群的节点、进程（Worker）、Actor、Job 状态
- **拉 Ray REST 周期采样**：summary 视角（节点硬件）+ detail 视角（节点上的 Worker/Actor）+ cluster_status + jobs
- **4 状态告警引擎**：节点/进程的 CPU / 内存 / GPU 超限告警，触发 → 恢复 → 确认 → 消除，过程中反复横跳都串在同一条告警下
- **SQLite 历史库**：节点硬件时序、Actor 状态变迁、Job 状态变迁、告警主表 + 事件表全留底，可做近 24h 查询
- **故障隔离**：一个集群的某次接口超时不影响同集群其他接口，也不影响别的集群
- **HTTP gzip 透明解压**：dashboard 返回 gzip 时自动解压，省 detail tick 带宽

> 生产现状：4 集群 × 18 节点，detail tick 带宽峰值已被压缩到 20-40MB/3s（原本明文 ~200MB/3s）。

---

## 2. 使用入门

### 2.1 启动

打包后是单文件 exe：

```cmd
ray-monitor.exe
```

> 上面是打包版的启动方式；用源码运行是 `wails dev`（开发模式，带热重载），打包是 `wails build`，产物在 `build/bin/ray-monitor.exe`（约 15.6MB）。

**运行环境**：

- Windows 10 / 11（64 位）；macOS / Linux 可跑但生产未在用
- **WebView2 Runtime**（Win10 1803+ 一般自带，没有的话微软官网下一个）
- exe 同目录可写（用于落 `config.json` / `ray_monitor.db` / `logs/ray_monitor.log`）；不可写时自动回退到 `%USERPROFILE%\ray_monitor\`

### 2.2 首次启动

第一次运行会在 exe 同目录创建：

- `config.json` — 配置（集群 URL、阈值、采样间隔）
- `ray_monitor.db` — SQLite 历史库
- `logs/ray_monitor.log` — 运行日志

**默认配置带一个集群**：`http://10.30.144.41:32549`（示例地址，需要在配置页改成你自己的 Ray dashboard）。

> 首次启动采集默认是**停止**状态，需要在右上角点 **"操作" → "全部开始"** 才会真正开始拉数据。

### 2.3 配置保存位置（要看就看这些文件）

| 文件 | 路径 | 内容 |
| --- | --- | --- |
| 配置 | `exe 同目录\config.json`，无写权限时回退到 `%USERPROFILE%\ray_monitor\config.json` | 集群 URL 列表、阈值、采样间隔 |
| 数据库 | `exe 同目录\ray_monitor.db` | 节点/Worker/Actor/Job 历史 + 告警主表 |
| 日志 | `exe 同目录\logs\ray_monitor.log` | 运行日志（含告警 trigger / recover / ack） |
| 启动诊断 | `exe 同目录\debug.txt` | 启动时写的诊断信息（每次启动覆盖一次） |

> 集群名 = URL 去掉协议前缀后的 host:port（`ClusterConfig.DisplayName()`）。所以同一个 URL 显示出来就是这个 host:port。

### 2.4 关闭

直接关窗口。`shutdown` 会自动 stop 所有采集器 + 关闭 SQLite。

---

## 3. 功能介绍

### 3.1 总述 — 监控的逻辑

工具按如下流程跑：

1. 启动时读 `config.json`，初始化采集管理器（每个集群 1 个 Collector，独立 goroutine）
2. 用户点 **"操作 → 全部开始"**，各集群 Collector 开始双层轮询
3. 每 **采样间隔**（默认 10 秒）：
   - **summary tick**：并发打所有集群的 `/nodes?view=summary` → 节点硬件（CPU/内存/GPU/状态）
   - **detail tick**：并发打各节点的 `/nodes/{id}`（限流并发，默认 10）+ `/api/cluster_status` + `/api/jobs/`，合并为 Worker/Actor/Job/ClusterMetric
4. 每轮采集后回调告警引擎 `Check`，对每个节点/Worker 按 CPU/MEM/GPU 比阈值，触发 / 累计 / 恢复
5. 前端每 5 秒拉一次选中集群的全量 snapshot + perf + 全局告警计数
6. 所有数据写入 SQLite 供历史查询

### 3.2 支持的操作系统

- **Windows** 10 / 11（64 位，主战场）
- **macOS / Linux**：理论上可跑（`openInFolder` 跨平台、webview 可用），但**未在生产验证**

> Wails v2 在 macOS 上用 WKWebView，在 Linux 上用 WebKitGTK；打包各平台需要各平台的本地工具链。

### 3.3 6 个视图看到什么

侧边栏从上到下是 **"全局报警"**（带未消除告警数角标）+ **集群列表**（每个带状态点：灰=停止、绿=正常、红=运行中但有错误）+ 底部版本号。

选集群后右侧出现 tab：

| tab | 看到什么 |
| --- | --- |
| **概览** | 第一行：分配值（Ray 调度视角，CPU/MEM/GPU from `cluster_status`）；第二行：实际占用（节点硬件视角汇总）；底部：**采集器自评估**（summary/detail 耗时、最慢单节点、节点/Worker/Actor 数、HTTP 压缩是否启用、Risk 评估） |
| **节点** | 全节点列表，列：节点名、类型（Head/Worker）、CPU、内存（已用/总量 + 占比）、GPU（已用/总量）、状态（ALIVE/DEAD）。半哑节点带 **"半哑"** 黄色徽章。表头每列都有筛选框 |
| **进程** | Worker 进程列表，列：进程名（`ray::类名` 或 `ray::IDLE`）、所在节点、PID、CPU%、内存 RSS、GPU。表头每列都有筛选框 |
| **报警** | 未消除告警列表。顶部两个 checkbox：节点报警 / 进程报警（默认都勾）。右键单条报警弹菜单：**确认报警 / 查看对象 / 复制信息** |

> **Actors** 和 **Jobs** 在 v0.92 的主 tab 里**没有独立入口**。通过 ActorsView / JobsView 组件存在但主区未挂载；Actor 事件流（近 24h 状态变迁）和 Job 历史查询（近 24h）的逻辑保留在代码里，后续版本接入。**当前主流程用节点 + 进程 + 报警三个 tab。**

#### 选 "全局报警" 时的视图

不显示集群 tab，主区直接是 **所有集群未消除告警汇总表**，比单集群报警多一列 "集群"。其他操作相同。

### 3.4 告警 4 状态机

每条告警有 **两个独立布尔维度**：`recovered`（是否恢复）× `acknowledged`（是否确认）。组合出 4 种状态：

| recovered | acknowledged | 状态 | UI 显示 |
| --- | --- | --- | --- |
| ❌ | ❌ | 报警-未确认 | 红色 badge |
| ❌ | ✅ | 报警-已确认 | 蓝色 badge |
| ✅ | ❌ | 已恢复-未确认 | 黄色 badge |
| ✅ | ✅ | 已消除 | 列表里消失，进历史 |

**规则**：

- **触发**：单次采集超限即触发。无活告警则新建一条，有活告警则更新最近触发时间，**若之前已恢复则"复活"到未恢复**。
- **恢复**：连续 `RecoverConsecutive` 次（默认 **3 次**）低于限值才标记恢复。**报警要快，恢复要稳**——故意做不对称防抖。
- **确认**：用户对告警右键点 **"确认报警"**。**确认对整条告警全程有效**（不是确认某个状态）。
- **消除**：只有 `recovered=true 且 acknowledged=true` 才消除。消除后该对象再超限 = **新的一条告警**。
- **反复横跳**：未消除期间反复超限/恢复都记在同一条告警下（`alert_event` 表）。"已恢复-未确认" 状态又超限 → recovered 变 false，状态回 "报警-未确认"（如果之前已确认则回 "报警-已确认"），**这条告警不结束**。

**告警指标**（受 Ray 数据限制，UI 上能看到但不会触发）：

| 类型 | CPU | 内存 | GPU |
| --- | --- | --- | --- |
| 节点 | ⚠️ **不报**（缺核数算不出利用率） | ✅ 报 | ✅ 报 |
| Worker（进程） | ✅ 报 | ⚠️ **不报**（worker 没内存总量） | ✅ 报 |

> 阈值 = 0 表示该指标**不告警**（默认配置都 >0）。

### 3.5 告警确认（ack）操作

在 **报警 tab** 任意一条上 **右键**：

- **确认报警** — 立即把 `acknowledged=1`。如果该告警已经 `recovered=1`（"已恢复-未确认"），立即消除。如果还没恢复，进入 "报警-已确认"。
- **查看对象** — 跳到节点 tab（v0.92 仅切到节点 tab，不再定位到具体行）
- **复制信息** — 把告警摘要文本复制到剪贴板：`[告警] 进程名 MEM=85.0% (阈值80%) 状态:报警-未确认 集群:xxx 触发:2026-07-05 14:30:12`

> 确认对**整条告警**生效，不是某个状态。所以你确认了一条 "报警-未确认"，之后它恢复到 "已恢复-未确认" 你再点确认，会立即消除（因为已经 ack 过）。

### 3.6 历史查询

- **Actors 状态变迁**：v0.92 主视图未挂载 Actor 入口，组件代码里保留"近 24h ActorEvent"查询逻辑。
- **Job 历史**：同上。JobsView 组件里有"近 24h JobHistory"查询按钮的逻辑。

> 当前用户拿到手的视图：**历史主要靠外部分析 `ray_monitor.db`**。9 张表都在 `storage/schema.go` 定义（见 3.9），可直接用 sqlite3 客户端查。

### 3.7 多集群管理

**新增集群**：右上角 **"配置"** → 集群列表区 → 输入 `http://host:port` → **"添加"** → **"保存"**。**保存后该集群默认是停止状态**（不自动开始采集），需到 **"操作"** 弹窗手动点 **"开始"**。

**删除集群**：配置页集群列表右侧点 **"删除"** → **"保存"**。保存后该集群的采集器会被停掉，数据留在库里但 cluster_id 仍可查。

**运行时启停**：右上角 **"操作"** 弹窗：

- **全部开始** / **全部停止**：一键控制所有集群
- **逐集群开始 / 停止**：每个集群单独一行，状态点颜色：灰=已停止 / 绿=运行中 / 红=运行中且有错误。错误数会显示在文字里（如 `运行中 · 3 错误`）

> 改 **采样间隔** 需要保存配置，工具内部会重建所有采集器。改 **集群 URL** 也需要保存，工具会热重建该集群的采集器（不影响别的集群）。改 **阈值** 不重建采集器，下一轮 Check 生效。

### 3.8 配置项

**采样间隔**（秒）：summary 和 detail 共用（v0.92 统一了），默认 **10**。范围建议 5-30。太短打爆集群，太长告警滞后。

**全局告警阈值**（百分比 0-100，**所有集群共用**，集群级覆盖后端支持但 UI 未暴露）：

| 阈值 | 默认 | 设为 0 |
| --- | --- | --- |
| 节点 CPU | 80 | 不报 |
| 节点内存 | 80 | 不报 |
| 节点 GPU | 90 | 不报 |
| 进程 CPU | 80 | 不报 |
| 进程内存 | 80 | 不报 |
| 进程 GPU | 90 | 不报 |

> v0.92 节点 CPU 默认 80% 但**不生效**（数据源缺核数）；想关掉就设成 0。

**排序**：节点 / 进程 tab 的排序基准，`cpu`（默认）或 `gpu`。

> 后端还有这些字段（用户在配置页看不到）：`TimeoutSec`（API 请求超时，默认 8s）、`Concurrency`（每集群 detail 并发上限，默认 10）、`GlobalConcurrency`（全局并发上限，默认 30）、`RecoverConsecutive`（恢复需连续低于限值的次数，默认 3）。需要改时手动编辑 `config.json`。

### 3.9 SQLite 历史表（9 张）

| 表 | 内容 | 关键列 |
| --- | --- | --- |
| `node_metric` | 节点硬件时序 | `cluster_id, node_id, ts, cpu, mem_total, mem_used, gpu_total, gpu_used, state` |
| `worker_snapshot` | Worker 进程快照 | `cluster_id, node_id, pid, ts, process_name, cpu_percent, mem_rss, gpu_used` |
| `actor_snapshot` | Actor 快照 | `cluster_id, actor_id, ts, actor_class, state, num_restarts, gpu_used, exit_detail` |
| `job_snapshot` | Job 快照 | `cluster_id, job_id, ts, status, start_time, end_time, error_type` |
| `cluster_metric` | 集群调度指标 | `cluster_id, ts, cpu_total/used, mem_total/used (GiB), gpu_total/used, heartbeat_max` |
| `actor_event` | Actor 状态变迁 | `cluster_id, actor_id, ts, prev_state, new_state, death_cause` |
| `job_event` | Job 状态变迁 | `cluster_id, job_id, ts, prev_status, new_status, error_type` |
| `alert` | 告警主表 | `cluster_id, cluster_name, node_name, object_type, object_id, object_name, metric, threshold, recovered, acknowledged, first_trigger_ts, last_trigger_ts, recover_ts, ack_ts, eliminated_ts, last_value` |
| `alert_event` | 告警事件 | `alert_id, ts, event (trigger/recover/acknowledge/eliminate), value` |

> 所有表都有 `cluster_id` 列，多集群数据共库通过 cluster_id 区分。告警主表额外有 `cluster_name` / `node_name` 用于全局报警视图里显示。

### 3.10 完整可用的配置示例（4 集群，复制保存为 `config.json`）

```json
{
  "clusters": [
    { "id": "prod-a", "platformUrl": "http://10.30.144.41:32549" },
    { "id": "prod-b", "platformUrl": "http://10.30.144.42:32549" },
    { "id": "staging", "platformUrl": "http://ray-staging.internal:8265" },
    { "id": "dev",     "platformUrl": "http://ray-dev.internal:8265" }
  ],
  "dbPath": "ray_monitor.db",
  "logDir": "logs",
  "sortBy": "cpu",
  "sampleEvery": 10,
  "thresholds": {
    "nodeCpu": 80,
    "nodeMem": 80,
    "nodeGpu": 90,
    "workerCpu": 80,
    "workerMem": 80,
    "workerGpu": 90
  },
  "timeoutSec": 8,
  "concurrency": 10,
  "globalConcurrency": 30,
  "recoverConsecutive": 3
}
```

字段说明：

- `clusters[].id`：唯一标识，前端**不可改**（自动生成 `cluster-<timestamp>`）
- `clusters[].platformUrl`：Ray dashboard 地址（HTTP 即可，无需鉴权时）；如需 cookie 在源码层加 `cookie` 字段
- `sampleEvery`：所有集群统一采样间隔（秒）
- `thresholds`：全局阈值，CPU/MEM 默认 80%、GPU 默认 90%；**所有 6 个字段都是 0~100 的数字百分比**
- `recoverConsecutive`：连续低于限值多少次才判定恢复，默认 3
- 其他字段（`timeoutSec` / `concurrency` / `globalConcurrency`）一般不动

---

## 4. 已知限制

下面这些是 **v0.92 没做** 的事，用户应知：

- **告警不推送 IM / 邮件**：告警只在工具内显示，没对接钉钉/飞书/邮件/Webhook
- **节点 CPU 不告警**：Ray `/nodes/{id}` 没给节点核数，`cpu` 字段是核数占用不是利用率，**目前算不出 "CPU%" 阈值**。设了 `nodeCpu=80` 也无效
- **Worker 内存不告警**：Worker 进程只有 RSS（已用），没有 cgroup limit 总量，**算不出内存 %**。`workerMem` 阈值无效
- **Worker GPU 阈值不推荐调**：worker 的 GPU 用量是从该 pid 上的 Actor 的 `requiredResources["GPU"]` 汇总的，不是真实测量
- **集群级阈值覆盖**：后端代码 `Config.ResolveThresholds` 留了接口但 UI 不暴露，**所有集群共用同一组全局阈值**
- **Actors / Jobs 视图**：组件代码存在但主 tab 没挂载，**当前只能从数据库查 Actor/Job 历史**
- **告警历史查询 UI**：未实现，只能直接读 `alert` + `alert_event` 表
- **通用历史查询页**：未实现
- **全局负荷（GlobalPerf）详情页**：后端有 `GetGlobalPerf()` 方法和 `cluster_metric` 历史，但概览页只显示单集群 perf，**全局负荷详细展示未接 UI**
- **告警 IM / 邮件 / Webhook 推送**：见上面，不重复

---

## 5. 已知 Bug（用户应避免踩坑）

> v0.92 静态代码审查发现的 3 个 **高严重度** bug，**未在 v0.92 修复**：

### 5.1 fetch 失败时零值覆盖 snapshot（高）

**现象**：详情采集过程中，如果 `/api/cluster_status` 返回错误，工具会用零值（CPUTotal/MemTotal/GPUTotal/HeartbeatMax 全 0）**覆盖**当前快照里 cluster 字段；`/api/jobs/` 失败时 Jobs 列表变空；所有节点详情都失败时 Worker/Actor 列表变空。

**复现**：让 Ray dashboard `/api/cluster_status` 短暂返回 500 → 概览页 `cluster.cpuTotal` 等瞬间归零。

**对用户的影响**：监控数据会"瞬时假清零"，需要等下一轮恢复。**不会丢数据库历史**（失败时 DB 也没写），但 UI 那一刻会看起来像集群挂掉。

### 5.2 半哑节点内存被覆盖（高）

**现象**：半哑节点（agent 未上报 mem，但 raylet 有 nodeId/state）原本在 summary tick 有内存数据；detail tick 解析时 mem 字段缺失，**用零值覆盖**了 summary 写好的内存数据。

**对用户的影响**：节点内存历史曲线在 detail tick 归零 → 下一轮 summary 又有值，曲线呈"锯齿"。如果设了内存告警阈值，半哑节点会一直误报"0%"。

**临时绕过**：在节点 tab 看 `memUsed=0` 的节点基本都是半哑的，别当内存真为零。

### 5.3 告警确认不写 acknowledge 事件（高）

**现象**：`acknowledge` 是事件类型之一（`alert_event.event` 取值：`trigger` / `recover` / `acknowledge` / `eliminate`），但实际写入时**确认事件从未落库**。`alert_event` 表只有 trigger / recover / eliminate 三种事件。

**对用户的影响**：后续如果做"告警事件时间线"，用户点确认的时间不可见。**当前 UI 不展示事件时间线，用户暂时无感**。

### 5.4 其他中低严重度 bug（参考）

静态审查报告里还有 9 个中/低严重度问题（告警并发去重、AddCluster 不查重、节点 hostname summary/detail 不一致等），详见 `Ray代码审查报告.md`。当前未影响主流程。

---

## 6. 故障排查 / 常见问题

**Q：配了集群但看不到数据？**
A：右上角 **"操作"** 弹窗，确认该集群状态点是 **绿色**（运行中）。灰色 = 停止，红色 = 运行但有错误（看错误数）。常见错误：URL 不可达、超时、Ray dashboard 没起来。

**Q：采集跑起来了但侧边栏集群列表是空的？**
A：检查 `config.json` 里 `clusters` 字段。配置页改完后**必须点保存**，仅关弹窗不生效。

**Q：告警角标显示 13 但列表是空的？**
A：v0.91 之前存在 `CreateAlert` INSERT 占位符不匹配 bug（16 列只给 13 值），新告警插不进库。**v0.92 已修复**（`storage.CreateAlert`），跑新版后正常。如旧脏数据碍眼，删 `ray_monitor.db` 重来。

**Q：报警 tab 标题的 `(clusterID=xxx, 共N条)` 这个诊断显示是什么？**
A：这是开发调试用的临时显示：N>0 但列表空 = 前端问题；N=0 = 后端没查到。**稳定下来后会删除**。

**Q：日志在哪里？**
A：默认 `exe 同目录\logs\ray_monitor.log`。配置页底部会显示当前日志路径。包含告警 trigger / recover / ack / eliminate 日志行。

**Q：怎么重启？**
A：直接关窗口重开。所有配置、阈值、URL 都在 `config.json` 里持久化，**重启不丢**。SQLite 历史也会持久化。

**Q：怎么改端口？**
A：采集器不打端口。配置里的 URL 必须是 Ray dashboard 的完整 `http://host:port`（不带 path），默认 Ray dashboard 端口是 `8265`，KubeRay 经常换（如示例的 `32549`）。

---

## 7. 给运维的构建说明

> 这部分用户不需要看，运维/开发者用。

### 7.1 源码构建

```bash
export PATH="/d/TDM-GCC-64/bin:$PATH"   # Windows + GCC（CGO 编译 WebView2 binding）
cd F:/github/supcon_tools/ray_api
wails build                              # 产物：build/bin/ray-monitor.exe（~15.6MB）
```

### 7.2 仅后端编译/测试

```bash
go build ./...
go test -count=1 ./...
```

### 7.3 开发模式

```bash
wails dev    # 热重载，会起窗口
```

### 7.4 改 Wails 绑定

改了 `app.go` 的方法签名/新增方法后必须：

```bash
wails generate module
```

否则前端调不到新方法（前端用的是 `frontend/wailsjs/go/models.ts` 自动生成的绑定）。

### 7.5 环境要求

- Go ≥ 1.21（实际 1.25）
- Node.js ≥ 18（实际 24）
- GCC：`D:\TDM-GCC-64`（CGO 必须）
- WebView2 Runtime（Win10 多数自带）

---

designed by yzc