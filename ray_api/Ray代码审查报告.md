# Ray 集群监控工具 — 静态代码审查报告

> 评审日期：2026-07-03
> 评审范围：v0.9 全量后端（collector / storage / alert / config / app / logx）+ 前端关键文件
> 评审方式：静态阅读（未跑测试、未运行 exe）
> 当前焦点：告警显示问题收尾，本报告一并梳理相邻模块的隐患

---

## 1. 评审结论摘要

- 共发现 **12 个**静态可确认的 bug 或代码异味，其中 **3 个高严重度**
- `storage.CreateAlert` 修复（16 列 16 占位符 16 值）经静态核对一致，配合 `TestAlertScan` 应能恢复新告警入库
- 当前最影响线上稳定性的 3 个 bug 全部在 `collector/collector.go` 的 `collectDetail` 内：fetch 失败时的零值覆盖、半哑节点 mem 覆盖、启动时双写

---

## 2. 严重度分级

| 等级 | 定义 | 处置 |
|------|------|------|
| 高 | 影响线上数据正确性或生产稳定性 | 优先修复 |
| 中 | 影响数据一致性 / 性能 / 审计完整度 | 当前迭代内修复 |
| 低 | 边界条件 / 代码异味 / 潜在隐患 | 视情况修复 |

---

## 3. 详细发现

### Finding #1 — collectDetail fetch 失败时零值覆盖 snapshot（高）

**位置**：`collector/collector.go:362`

**现象**：
```go
cm, err := c.client.FetchCluster()
if err != nil {
    logx.L().Warn("cluster collect failed", "err", err)
    c.recordErr("cluster", err)
} else {
    _ = c.store.WriteCluster(c.opts.ClusterID, cm)
}

jobs, err := c.client.FetchJobs()
if err != nil {
    logx.L().Warn("jobs collect failed", "err", err)
    c.recordErr("jobs", err)
    jobs = nil
}
...
c.refreshSnapshotDetail(cm, allWorkers, allActors, jobs)  // line 362 无条件
```

`refreshSnapshotDetail` 无条件用本地变量覆盖 snapshot 全部字段。FetchCluster 返回 `(ClusterMetric{}, err)` 时 `cm` 是零值，覆盖 snapshot.cluster；FetchJobs 失败时 `jobs = nil`，覆盖 snapshot.jobs；所有节点详情失败时 `allWorkers / allActors` 为空切片，覆盖 snapshot.workers / snapshot.actors。

**复现**：
1. 启动采集
2. 短暂让 Ray 集群 `/api/cluster_status` 返回 500
3. 观察概览页 cluster 字段瞬间清零（CPUTotal/MemTotal/GPUTotal/HeartbeatMax 全 0）
4. 同样条件下让 `/api/jobs/` 失败 → Jobs 列表变空

**修复建议**：
```go
// 仅在 fetch 成功时覆盖 snapshot
if cm.Ts != 0 {  // 简易成功判断
    c.refreshSnapshotDetail(cm, allWorkers, allActors, jobs)
} else {
    // 或在 FetchCluster 失败时保留旧 cm
}
// 同样的判定给 jobs / workers / actors
```
更彻底的方案：fetch 失败时记 Warn 但不调 `refreshSnapshotDetail`，沿用 snapshot 旧值；DB 侧也跳过写。

---

### Finding #2 — FetchNodeDetail mem 字段缺失时覆盖半哑节点数据（高）

**位置**：`collector/ray_client.go:222-235` + `collector/collector.go:327-328`

**现象**：
```go
// ray_client.go
if len(d.Mem) >= 2 {
    nm.MemTotal = int64(d.Mem[0])
    nm.MemUsed = int64(d.Mem[1])
}
// 否则 MemTotal/MemUsed 保持零值
```
```go
// collector.go
_ = c.store.WriteNodeMetrics(c.opts.ClusterID, []model.NodeMetric{r.node})  // 写零值
c.refreshSnapshotNode(r.node)                                                // 覆盖 snapshot
```

`refreshSnapshotNodes` 的合并逻辑会保留 detail 的权威字段（注释在 line 463），所以 detail 写入零值 mem 后，**summary 已经填好的 mem 数据被覆盖**。半哑节点（agent 未上报 mem，但 raylet 有 nodeId/state）即典型受害者。`TestFetchNodes_HappyAndPartial` 测试了 summary 解析时的半哑节点，但没测 detail 对 mem 的覆盖。

**复现**：
1. 配置一个半哑节点（raylet 在，detail 的 `mem` 字段缺失或长度 < 2）
2. 观察节点历史曲线：每个 detail tick mem 归零，summary tick 才有值
3. 告警 MEM 检查：memPct = 0/MemTotal，可能误报"内存 0%"或干脆被 `n.MemTotal == 0` 跳过

**修复建议**：
```go
// ray_client.go FetchNodeDetail：detail 缺失 mem 时保留旧值或置 IsPartial
if len(d.Mem) < 2 {
    nm.IsPartial = true
    // 不主动写 mem 零值
}

// collector.go collectDetail：detail 节点 IsPartial 时跳过覆盖
if r.ok && !r.node.IsPartial {
    _ = c.store.WriteNodeMetrics(c.opts.ClusterID, []model.NodeMetric{r.node})
    c.refreshSnapshotNode(r.node)
}
```

---

### Finding #3 — 启动时 summary 与 detail 双写 node_metric（中）

**位置**：`collector/collector.go:171-172`

**现象**：
```go
c.collectSummary(ctx)   // line 171：内部 model.NowMs()，写 node_metric
c.collectDetail(ctx)    // line 172：内部 model.NowMs()，每个节点也写 node_metric
```

两者在同一毫秒内顺序执行，都通过 `model.NowMs()` 取 ts。`node_metric` schema 缺少 `(cluster_id, node_id, ts)` 唯一约束（`schema.go:10-25`），所以同一节点同 ts 落两条。`QueryNodeHistory` 用 `ORDER BY ts`，相同 ts 排序不确定，前端图表出现两个相同 x 的点。

**复现**：
1. 启动 exe
2. 等 5 秒让前端的 GetNodeHistory 拉一次
3. 在 OverviewView 的节点历史里，每节点最左端会有两个紧贴的点

**修复建议**（任选其一）：
- 给 `node_metric` 加唯一约束：`CREATE UNIQUE INDEX IF NOT EXISTS idx_node_uniq ON node_metric(cluster_id, node_id, ts)`（INSERT OR REPLACE 兜底）
- collectDetail 跳过 `IsPartial` 节点（与 #2 一并修）
- collectSummary 与 collectDetail 错开一毫秒（脆弱，不推荐）

---

### Finding #4 — alert 表缺少唯一约束，Check 并发可产生重复告警（中）

**位置**：`storage/schema.go:107-127`

**现象**：
```go
// alert.go checkMetric
existing, err := m.store.FindActiveAlert(clusterID, objType, objID, metric)
...
if valuePct >= threshold {
    if existing == nil {
        a, err = m.store.CreateAlert(a)  // 两个 goroutine 都到这里
    }
}
```

两个 Collector 同时进入 checkMetric，对相同 `(cluster, type, id, metric)` 都 `FindActiveAlert` 拿到 nil（都还没插入），都走到 `CreateAlert`。SQLite 无唯一约束，两条都成功。

**复现**（边界场景）：
- 多集群 + 同一 worker 跨集群（实际上 objID 包含 clusterID，不会冲突）
- 同一集群的 summary 与 detail 并发触发 onAlert（理论上不会同时，但 onAlert 是从 collectSummary 和 collectDetail 分别调用的）
- alert.Manager.Check 是 Manager 的方法，多集群 Manager 各自独立，下面 ListActiveAlerts 才汇合

实际触发概率较低，但 schema 加约束成本极低。

**修复建议**：
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_active_uniq
ON alert(cluster_id, object_type, object_id, metric) WHERE eliminated_ts = 0;
```
（SQLite 支持 partial index）。然后 `CreateAlert` 改为 `INSERT OR IGNORE`，重复时拿到旧 ID；或在 `CreateAlert` 之上加一层 per-key mutex。

---

### Finding #5 — AckAlert 漏写 acknowledge 事件（中）

**位置**：`storage/store.go:341-356`

**现象**：
```go
func (s *Store) AckAlert(id int64) error {
    now := model.NowMs()
    _, err := s.db.Exec(`UPDATE alert SET acknowledged=1, ack_ts=?,
        eliminated_ts=CASE WHEN recovered=1 AND eliminated_ts=0 THEN ? ELSE eliminated_ts END
        WHERE id=? AND eliminated_ts=0`, now, now, id)
    if err != nil { return err }
    var elim int64
    s.db.QueryRow(`SELECT eliminated_ts FROM alert WHERE id=?`, id).Scan(&elim)
    if elim != 0 {
        s.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: id, Event: "eliminate"})
    }
    return nil
}
```

`model.AlertEvent` 注释里写明 `event: trigger | recover | acknowledge | eliminate`（`model/model.go:209-211`），但 `acknowledge` 事件从未写入。后续若前端要做"报警事件时间线"，用户确认操作不可见。

**复现**：
1. 等一个告警进入"已恢复-未确认"状态
2. 右键确认
3. 直接查 DB：`SELECT * FROM alert_event WHERE alert_id=? AND event='acknowledge'` → 0 行

**修复建议**：
```go
// 写 eliminate 之前先无条件写 acknowledge
s.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: id, Event: "acknowledge"})
if elim != 0 {
    s.AddAlertEvent(model.AlertEvent{Ts: now, AlertID: id, Event: "eliminate"})
}
```

---

### Finding #6 — collectDetail 拼 PerfMetrics 时无锁读 c.perf（中）

**位置**：`collector/collector.go:369`

**现象**：
```go
p := model.PerfMetrics{
    SummaryMs:       c.perf.SummaryMs,  // line 369，无锁读
    DetailMs:        detailMs,
    ...
}
```

`collectSummary` 持 `c.mu.Lock()` 写 `c.perf.SummaryMs / NodeCount / Risk`（line 238-242）。`collectDetail` 在另一执行流（同一 Collector 内串行，但 Goroutine 内部 select 会让出）无锁读 `c.perf.SummaryMs`。Go race detector 必报。值都是 int64/string，对齐到 8 字节内一般不会撕裂，但属未定义行为。

**修复建议**：
```go
c.mu.RLock()
summaryMs := c.perf.SummaryMs
c.mu.RUnlock()
p := model.PerfMetrics{
    SummaryMs: summaryMs,
    ...
}
```

---

### Finding #7 — AddCluster 不查重，重复 ID 污染配置（低）

**位置**：`app.go:371-382`

**现象**：
```go
func (a *App) AddCluster(cl config.ClusterConfig) SaveConfigResult {
    a.mu.Lock()
    a.cfg.Clusters = append(a.cfg.Clusters, cl)  // 不查重
    a.mu.Unlock()
    ...
}
```

Manager 内部 map 会去重（`manager.go:154`），但 `a.cfg.Clusters` 切片保留全部。后续 `SaveConfig` 走 `SyncClusters` 时 `oldMap[id]` 多次匹配，`SyncClusters` 走 ID 比较的逻辑会出现预期外分支（虽然功能上无明显错误，但配置脏、UI 侧边栏可能列重）。

**修复建议**：
```go
for _, c := range a.cfg.Clusters {
    if c.ID == cl.ID {
        return SaveConfigResult{Error: "cluster id already exists"}
    }
}
```

---

### Finding #8 — UpdateCluster 不校验 ID 是否存在（低）

**位置**：`app.go:405-421`

**现象**：
```go
for i, c := range a.cfg.Clusters {
    if c.ID == cl.ID {
        a.cfg.Clusters[i] = cl
        break
    }
}
// 没有 return / Error
if err := config.Save(a.cfg); err != nil { ... }
if a.manager != nil {
    a.manager.UpdateCluster(cl)  // 内部 RemoveCluster(no-op) + AddCluster(实际新增)
}
```

陌生 ID 的 UpdateCluster 实际变成"添加"行为。配置和采集器都被修改，行为难料。

**修复建议**：
```go
found := false
for i, c := range a.cfg.Clusters {
    if c.ID == cl.ID {
        a.cfg.Clusters[i] = cl
        found = true
        break
    }
}
if !found {
    return SaveConfigResult{Error: "cluster id not found: " + cl.ID}
}
```

---

### Finding #9 — alert.checkMetric 的 belowCnt 是 TOCTOU 模式（低，边界）

**位置**：`alert/alert.go:104-178`

**现象**：
```go
key := fmt.Sprintf("%s|%s|%s|%s", clusterID, objType, objID, metric)
m.mu.Lock()
cnt := m.belowCnt[key]    // 读
m.mu.Unlock()             // 释放

existing, err := m.store.FindActiveAlert(...)  // DB 调用，无锁

if valuePct >= threshold {
    m.mu.Lock()
    m.belowCnt[key] = 0   // 写
    m.mu.Unlock()
} else {
    m.mu.Lock()
    m.belowCnt[key] = cnt + 1   // 用旧 cnt 加 1
    ...
}
```

两个并发 Check 对同一 key：A 读 cnt=2 后释放；B 进入超限把 key 复位为 0；A 进 else 分支把 key 设为 2+1=3，触发 recover。状态机边界条件漂移。

**复现**：依赖多集群 Manager 各自 Check 同时触发同一对象。实际概率极低，但理论存在。

**修复建议**：
- 把"读 cnt → DB 查询 → 写 cnt"用一把 mutex 包住（牺牲 DB 调用期间的并发）
- 或重构成"先 FindActiveAlert 看 DB 的 Recovered 字段，单一权威源"，把 belowCnt 改成纯本地 cache，定期 reconcile

---

### Finding #10 — Manager.belowCnt 永不清理，键单调累积（低）

**位置**：`alert/alert.go:43-61`

**现象**：每次 worker 进程重启换 pid 都会产生新的 objID（`nodeId:pid`），belowCnt 多一个键。集群热删时其键也不清。长时间运行（worker 高频故障 + 集群增删）下 map 单调增长。

**修复建议**：
- 定期（如 1 小时）扫描 DB 活跃 alert，清除不在活跃集合里的 belowCnt 条目
- 或在 worker/job 状态消失时主动删 key（需 collector 配合通知）

---

### Finding #11 — FetchNodes 解析 hostname 顺序与 detail 不一致（低）

**位置**：`collector/ray_client.go:117-145`

**现象**：
```go
// summary
if nm.Hostname == "" {
    nm.Hostname = rn.Raylet.NodeManagerHost   // 总是覆盖（首次 hostname 必为空）
}
...
if nm.Hostname == "" {
    nm.Hostname = toStr(rn.Hostname)          // 兜底
}

// detail（FetchNodeDetail）
nm := model.NodeMetric{
    ...
    Hostname: toStr(d.Host),  // 直接用顶层 hostname
    ...
}
```

summary 优先用 `raylet.nodeManagerHostname`，detail 优先用顶层 `hostname`。同一节点在两次解析中可能得到不同 hostname，前端切换 summary tick 与 detail tick 时节点名会跳变。

**修复建议**：统一两边的优先级。建议 summary 也优先顶层 `hostname`，缺省再回退到 `raylet.nodeManagerHostname`。

---

### Finding #12 — collectDetail 每节点一次独立事务，DB 写放大（低，性能）

**位置**：`collector/collector.go:327`

**现象**：
```go
for _, r := range results {
    ...
    _ = c.store.WriteNodeMetrics(c.opts.ClusterID, []model.NodeMetric{r.node})
    c.refreshSnapshotNode(r.node)
}
```

`WriteNodeMetrics` 每次 `Begin/Commit` 一次事务。100 节点集群在 SampleEvery=10s 时每 10s 触发 100 次事务，WAL 模式下 fsync 累加。

**修复建议**：在 collectDetail 末尾收集所有 `r.node` 切片（成功且非 IsPartial 的）调一次 `WriteNodeMetrics`。或加个 `WriteNodeMetricsBatch`。

---

## 4. 已确认无 bug 的部分

| 模块 | 验证点 |
|------|--------|
| `storage.CreateAlert` 修复 | 16 列 ↔ 16 占位符 ↔ 16 值 一致（`store.go:300-313`） |
| `FindActiveAlert / ListActiveAlerts` | 16 列 SELECT ↔ 16 个 Scan target 一致（`store.go:316-331, 367-392`） |
| `UpdateAlert / AckAlert` | SET/WHERE 列数与值数匹配（`store.go:334-357`） |
| 告警状态机一致性 | recover 路径走 `Manager.tryEliminate`，ack 路径走 `store.AckAlert` 原子消除 eliminated_ts，两条路径都覆盖（`alert.go:164-187, store.go:341-357`） |
| 告警事件类型注释 | `model.AlertEvent` 注释与实际写入的事件类型一致（trigger/recover/eliminate 三个写入点都正确） |
| 告警对象 ID 设计 | node 用 nodeId，worker 用 `nodeId:pid`，避开了"同名进程串扰"（`alert.go:226-237`） |
| 配置两级阈值 | `config.ResolveThresholds` 统一返回全局（`config.go:92-94`），与 doc 一致 |
| 前端拉数据策略 | `App.tsx:47-81` 只拉选中集群的全量快照，其他集群只拉 status——N 集群场景下的正确性能取舍 |
| `TestAlertScan` 覆盖 | 写 1 条 → Count=1 → List=1，Scan 不报错（`storage/alert_test.go:12-61`） |

---

## 5. 修复优先级建议

**本迭代必修**（影响线上稳定性）：
1. #1 — fetch 失败零值覆盖
2. #2 — 半哑节点 mem 覆盖

**本迭代可修**（影响数据完整度 / 一致性）：
3. #5 — acknowledge 事件
4. #4 — alert 表唯一约束（成本极低，顺手做）
5. #6 — race detector 报的无锁读

**下一迭代可修**（性能 / 边界）：
6. #3 — 启动双写（与 #2 一起考虑）
7. #12 — DB 写放大
8. #7 / #8 — AddCluster / UpdateCluster 校验

**待观察**：
9. #9 — TOCTOU（实际触发概率极低）
10. #10 — belowCnt 累积（长时间运行才显现）
11. #11 — hostname 不一致（依赖实际 Ray 接口数据）

---

## 6. 给下一次评审的检查清单

- [ ] alert_event 表中 "acknowledge" 事件出现率
- [ ] 半哑节点历史曲线在 detail tick 时是否仍能保留 summary 的 mem
- [ ] collectDetail 失败时概览页 cluster 字段是否回退到上一有效值
- [ ] collectSummary / collectDetail 同 ts 落库的去重情况
- [ ] 多集群 Manager 跨集群并发 Check 是否产生重复告警
- [ ] alert 的 ListActiveAlerts 在 1000+ 条目时的查询性能（缺索引，仅有 `(cluster_id, eliminated_ts)` 和 `(cluster_id, object_type, object_id)` 复合索引）
