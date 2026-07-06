# Ray 监控工具 设计方案 v1.0

> 流程阶段② 设计文档。承接《Ray监控标准 v1.0》,产出工具的实现设计。
> 编写日期:2026-06-30
> 本轮范围:桌面 GUI + SQLite + 看板/历史查询(不含 Prometheus、不含主动告警推送)

---

## 1. 技术栈(固定,无选型空间)

按 dev-skill 强制约束,桌面 GUI 工具固定栈:

| 层 | 技术 | 版本 | 作用 |
|----|------|------|------|
| 桌面壳 | **Wails v2** | ≥2.10 | 借用系统 WebView2,打包 ~11MB |
| 后端语言 | **Go** | ≥1.21 | 采集器 + SQLite 存储 + Wails 绑定 |
| 前端 | React 18 + TS + Shadcn UI + Tailwind v3 + Vite | 见共享前端栈 | Notion 风浅色界面 |
| 存储 | **SQLite** | — | 时序 + 事件存储(标准§6 起步选型) |
| SQLite 驱动 | **modernc.org/sqlite** | latest | 纯 Go,免 CGO,跨平台编译稳 |
| 图表 | recharts | — | 趋势折线图(共享前端栈约定) |
| 日志 | log/slog(Go 1.21+) | 标准库 | 采集日志,文件+控制台 |

**为什么 SQLite 驱动选 modernc 而非 mattn/go-sqlite3**:Wails 已需 GCC(WebView2 binding),理论上 go-sqlite3(CGO)也能用;但 modernc 纯 Go 驱动免去 CGO 在 Windows 上的偶发编译问题,交叉编译更稳,体积差异可忽略。这是唯一的技术路线分歧,见 §4。

### 环境要求(实现前须验证 `wails doctor` 全绿)

- Go ≥ 1.21
- Node.js ≥ 18
- GCC(Windows 用 TDM-GCC)
- WebView2 Runtime(Windows 10 多数自带)

---

## 2. 模块拆分

### 2.1 后端(Go)文件结构

```
项目根/
├── main.go                  Wails 入口 + 窗口配置
├── app.go                   App struct + 暴露给前端的方法(Wails 绑定)
├── collector/
│   ├── collector.go         采集调度器(双层频率 goroutine)
│   ├── ray_client.go        Ray REST 客户端(summary/detail/cluster/jobs)
│   └── collector_test.go    采集解析逻辑测试(纯函数)
├── storage/
│   ├── store.go             SQLite 封装(建表/写入/查询)
│   ├── schema.go            表结构定义
│   └── store_test.go        存储测试
├── model/
│   └── model.go             数据结构(节点/worker/actor/job/cluster)
├── config/
│   └── config.go            配置(平台地址/频率/DB路径/token)
├── logx/
│   └── logx.go              slog 日志封装
└── frontend/                前端(见 2.2)
```

### 2.2 后端模块职责

| 模块 | 职责 | 依赖 |
|------|------|------|
| `collector` | 双层定时采集 Ray 接口,解析为结构体,交给 storage 落库 | ray_client + storage,不依赖 Wails |
| `collector.ray_client` | HTTP 请求 5 个 Ray 接口,容错(超时/半哑节点/字段缺失) | 仅标准库 net/http |
| `storage` | SQLite 建表、增量写入(每批一事务)、历史查询 | modernc.org/sqlite |
| `model` | 纯数据结构,带 json tag | 无 |
| `config` | 读配置文件(JSON),默认值(平台地址 `10.30.144.41:32549`,summary 15s,detail 60s) | 无 |
| `logx` | slog 封装,写日志文件 + 控制台 | 标准库 |
| `app.go` | Wails 绑定层:启动/停止采集、查询当前态/历史、配置读写 | collector + storage |

**分层原则**(强制):`collector`、`storage`、`model` **不 import Wails**,保证 `go test ./...` 可独立测试。Wails 只在 `app.go`/`main.go` 出现。

### 2.3 前端视图(React)

左侧 Sidebar 导航,右侧主区,5 个视图:

| 视图 | 内容 | 数据来源(Wails 绑定) |
|------|------|------|
| **概览 Dashboard** | 集群资源总览卡片(总CPU/内存/GPU、已用/可用)、节点状态卡片(3节点在线/掉线)、最近作业状态 | `GetOverview()` |
| **节点视图** | 节点列表 + 选中节点的 CPU/内存趋势图(recharts)、worker 进程表、Actor 表 | `GetNodes()` / `GetNodeHistory(id, range)` |
| **进程视图** | 所有 worker 进程表(按节点/job 分组),CPU/内存/fd | `GetWorkers()` |
| **Actor 视图** | Actor 列表(状态/类/所在节点/重启次数)+ 状态变迁事件流 | `GetActors()` / `GetActorEvents(range)` |
| **Job 视图** | Job 列表(状态/耗时/失败原因)+ 历史查询(按状态/时间) | `GetJobs()` / `GetJobHistory(range)` |

顶部统一:**采集状态指示灯**(运行中/已停/上次采集时间)、**配置入口**(平台地址/频率)。

### 2.4 暴露给前端的 Wails 方法(app.go)

| 方法 | 作用 |
|------|------|
| `StartCollector()` / `StopCollector()` | 启停采集 |
| `GetCollectorStatus()` | 采集状态 + 上次成功时间 + 错误计数 |
| `GetOverview()` | 概览数据(集群资源 + 节点状态 + 最近作业) |
| `GetNodes()` | 当前所有节点快照 |
| `GetWorkers()` | 当前所有 worker 进程 |
| `GetActors()` | 当前所有 Actor |
| `GetJobs()` | 当前所有作业 |
| `GetNodeHistory(nodeID, from, to)` | 节点时序历史 |
| `GetActorEvents(from, to)` | Actor 状态变迁事件 |
| `GetJobHistory(from, to, status)` | Job 历史 |
| `GetConfig()` / `SaveConfig(cfg)` | 配置读写 |
| `OpenInFolder(path)` | 打开 DB 文件所在目录 |

实时性:采集器每次成功采集后用 `runtime.EventsEmit(ctx, "snapshot", data)` 推送当前态快照,前端订阅刷新;历史查询走上述 Get 方法按需拉取。

---

## 3. 实现逻辑(伪代码/步骤)

### 3.1 采集调度器(`collector.go`)

```go
// 双层采集:summary 高频,detail/cluster/jobs 低频
func (c *Collector) Run(ctx context.Context) {
    summaryTicker := time.NewTicker(15s)
    detailTicker  := time.NewTicker(60s)
    defer { summaryTicker.Stop(); detailTicker.Stop() }
    // 首次立即采一次
    c.collectSummary(); c.collectDetail()
    for {
        select {
        case <-ctx.Done(): return          // 关窗口 → ctx 取消 → 采集停(A模式)
        case <-summaryTicker.C: c.collectSummary()
        case <-detailTicker.C:  c.collectDetailClusterJobs()
        }
    }
}

func (c *Collector) collectSummary() {
    nodes, err := c.client.NodesSummary()   // 容错:半哑节点只取 raylet 字段
    if err != nil { logx.Warn("summary fail: %v", err); c.errCount++; return }
    c.store.WriteNodeMetrics(now, nodes)    // 增量落库,逐批事务
    runtime.EventsEmit(c.ctx, "snapshot", c.snapshot())  // 推前端
}
```

### 3.2 存储增量写入(`storage.go`,遵循 runtime-safety)

- 每次采集一批 → 立即 `BEGIN; ... COMMIT;` 写入,不攒内存缓冲。
- 写入失败用 slog 记录,不 panic,不影响下一轮采集。
- `defer` 确保 DB 句柄关闭时刷盘。

### 3.3 SQLite Schema(`schema.go`)

```sql
-- 时序:节点硬件(高频15s)
CREATE TABLE node_metric(
  ts INTEGER, node_id TEXT, hostname TEXT, is_head INTEGER,
  cpu REAL, mem_total INTEGER, mem_used INTEGER,
  gpu_total REAL, gpu_used REAL, state TEXT);

-- 时序:worker进程(低频60s)
CREATE TABLE worker_snapshot(
  ts INTEGER, node_id TEXT, pid INTEGER, job_id TEXT,
  cpu_percent REAL, mem_rss INTEGER, num_fds INTEGER);

-- 时序:Actor快照(低频60s)
CREATE TABLE actor_snapshot(
  ts INTEGER, node_id TEXT, actor_id TEXT, actor_class TEXT,
  state TEXT, num_restarts INTEGER);

-- 时序:Job快照(低频60s)
CREATE TABLE job_snapshot(
  ts INTEGER, job_id TEXT, status TEXT,
  start_time INTEGER, end_time INTEGER, error_type TEXT);

-- 时序:集群资源(低频60s)
CREATE TABLE cluster_metric(
  ts INTEGER, cpu_total REAL, cpu_used REAL, mem_total REAL,
  mem_used REAL, gpu_total REAL, gpu_used REAL, heartbeat_max REAL);

-- 事件:Actor状态变迁(全量保留)
CREATE TABLE actor_event(
  ts INTEGER, actor_id TEXT, prev_state TEXT, new_state TEXT, death_cause TEXT);

-- 事件:Job状态变迁(全量保留)
CREATE TABLE job_event(
  ts INTEGER, job_id TEXT, prev_status TEXT, new_status TEXT, error_type TEXT);

-- 索引(查询性能)
CREATE INDEX idx_node_ts ON node_metric(node_id, ts);
CREATE INDEX idx_worker_ts ON worker_snapshot(node_id, ts);
CREATE INDEX idx_actor_ts ON actor_snapshot(actor_id, ts);
CREATE INDEX idx_job_ts ON job_snapshot(job_id, ts);
```

事件表由采集器对比上一轮快照生成(状态变化才插入一条事件),见 §4 路线2。

### 3.4 容错处理

- **半哑节点**:`nodes[]` 中只有 `raylet` 字段者,采 `state` 但硬件字段写 NULL/0,不报错。
- **接口超时**:每个请求 8s 超时,失败计 errCount + slog 警告,下轮重试。
- **字段缺失**:GPU 用 `resourcesTotal["GPU"]`(无 key 则 0);Actor 资源/死因字段用候选名依次尝试。
- **DB 写失败**:slog 记录,数据丢弃但采集不中断(下一轮重试)。

---

## 4. 技术路线分歧(列优缺点 + 推荐)

### 路线1:SQLite 驱动 modernc vs mattn/go-sqlite3

| | modernc(纯Go) | mattn(CGO) |
|---|---|---|
| 编译 | 免 CGO,Windows 省心 | 需 GCC(Wails 已需,可复用) |
| 交叉编译 | 稳 | CGO 交叉编译易踩坑 |
| 性能 | 略低于 mattn,监控量级足够 | 更高 |
| **推荐** | ✅ 选 modernc | — |

### 路线2:Actor/Job 事件生成方式

| | 采集器对比上轮快照生成事件 | 单独轮询对比 |
|---|---|---|
| 实现 | 简单,采集时顺带 diff | 需额外逻辑 |
| 遗漏风险 | 两次采集间状态变两次会漏中间态 | 同样漏 |
| **推荐** | ✅ 采集器内存保留上一轮快照,diff 后写 event 表 | — |

> 说明:60s 采集间隔内若 Actor 死了又重建,会漏中间态——这是采样监控固有局限,标准未要求捕捉,可接受。

### 路线3:前端实时刷新 EventsEmit 推送 vs 轮询

| | EventsEmit(后端推) | 前端 setInterval 轮询 |
|---|---|---|
| 实时性 | 采集完即推,最优 | 受轮询间隔限制 |
| 复杂度 | 需 ctx + 订阅 | 简单 |
| **推荐** | ✅ EventsEmit 推当前态快照,历史查询走按需 Get | — |

---

## 5. 横切规则检查(runtime-safety)

本程序是**长时间运行、持续生成数据**的采集器,适用运行安全规范:

| 要求 | 落地方式 |
|------|---------|
| **增量持久化** | 每批采集立即事务写入 SQLite,不攒内存;DB 句柄 `defer Close()` 刷盘 ✅ |
| **底层日志** | slog 封装(logx),记录采集启动/完成/接口失败/DB写失败,写文件 `ray_monitor.log` + 控制台 ✅ |
| **崩溃恢复** | 采集是无状态轮询,重启即恢复;已存数据在 SQLite 天然持久;配置在 JSON 文件持久 ✅ |

LLM 集成:不涉及,跳过。

---

## 6. 验收对照(标准§7 MVP 级)

| 标准验收项 | 本设计是否满足 |
|---|---|
| 1 覆盖必须指标(硬件/进程/Actor/Job) | ✅ schema 覆盖 |
| 3 历史存储≥7天可查询 | ✅ SQLite 时序表 + 索引 |
| 5 容错(半哑节点/超时/缺字段) | ✅ §3.4 |
| 7 可视化(节点/进程/Actor/Job 四级视图 + 趋势) | ✅ 2.3 五视图 |
| 8 查询(按节点/Job/Actor/时间) | ✅ History 方法 |

本轮**不做**(后续版本):
- 2/4/6 告警 + GPU真实利用率(需 DCGM)
- 第5层 Prometheus 性能指标

---

## 7. 待实现时确认的不确定项

1. **Actor 39 字段中"死亡原因/资源占用"确切字段名**:实测一份 `/nodes/{id}` 的 `actors{}` 定死,代码用候选名容错。
2. **环境**:`wails doctor` 是否全绿(Go/Node/GCC/WebView2)——决定能否直接实现。

---

## 8. 文档同步承诺

实现完成后,按 doc-management 规范同步更新:本设计文档 + 部署运行手册(如何 `wails dev`/`wails build`)。
