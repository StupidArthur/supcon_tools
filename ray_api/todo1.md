# `ray_api` 最终审计问题修复任务书

## 一、项目与任务背景

目标仓库：

```text
https://github.com/StupidArthur/supcon_tools.git
```

目标项目：

```text
ray_api
```

工作分支基准：

```text
main
```

已知相关提交：

```text
beb5683a2c0c34b0423bffa7a6519b7f6f180cc6
首次完成采集完整性、节点缓存、健康提示、并发限制、Context、阈值和持久化改造。

9967ea86d713f93e90ef473e1467776ee7b19197
修复旧库迁移顺序、部分数据竞争、幽灵节点、存储错误提示、清理索引等审计问题。
```

开始工作时必须以最新 `main` 为准，不要假设 `9967ea8` 仍是 HEAD。先确认 `9967ea8` 已经位于当前分支历史中，并检查其后的提交是否修改过 `ray_api`。

执行：

```bash
git checkout main
git pull --ff-only
git merge-base --is-ancestor 9967ea86d713f93e90ef473e1467776ee7b19197 HEAD
git log --oneline --decorate -20
git diff 9967ea86d713f93e90ef473e1467776ee7b19197..HEAD -- ray_api
```

若后续提交已经修改了相关文件，应以最新代码为基础实现本任务，不能回退其他人的有效改动。

创建独立分支：

```bash
git checkout -b fix/ray-api-final-audit
```

---

# 二、原始业务问题说明

最初软件存在如下问题：

```text
某个 Ray 节点详情接口临时失败
→ 本轮只聚合成功节点的数据
→ Worker/Actor 快照被不完整结果整体覆盖
→ 进程列表突然减少
→ 下一轮节点恢复后进程又重新出现
```

此前改造已经实现：

* 按节点缓存 Worker 和 Actor。
* 节点请求失败时保留上一轮数据。
* 陈旧数据不写库、不告警、不推进事件 diff。
* 前端提示当前失败以及一分钟内的近期失败。
* Cluster 和 Jobs 失败时保留旧值。
* Actor ID 从 map key 正确获取。
* HTTP Context 取消。
* 全局并发限制。
* 六项报警阈值。
* SQLite retention。
* 配置校验和原子写入。
* 旧数据库迁移顺序调整。

本次任务不是重新设计产品，也不是重写采集器。本次只解决最终复审中仍存在的配置热更新、并发安全、健康统计、提示准确性和测试覆盖问题。

---

# 三、必须遵守的兼容约束

1. 不修改现有产品导航、页面结构和主要操作流程。
2. 不删除已有配置字段。
3. 不修改已有配置字段的用户含义。
4. 不要求用户删除旧配置或旧数据库。
5. 不清空运行中的采集快照来实现热更新。
6. 仅修改阈值时，不允许重建全部 Collector。
7. 仅修改 `RecoverConsecutive` 时，不允许丢失现有报警恢复计数。
8. 保留已有多集群启动、停止和独立控制能力。
9. 保留已有告警历史、Actor 事件、Job 事件和 SQLite 数据。
10. 新增 JSON 字段必须向后兼容。
11. 不在持有 Manager、Collector 或 App 锁时调用可能阻塞的数据库操作。
12. 不在持锁状态下调用外部 callback。
13. 所有并发修改必须通过 `go test -race ./...`。
14. 不通过降低测试要求、删除断言或屏蔽 race 来获得通过。
15. 不增加不必要的运行时依赖。

---

# 四、问题一：阈值修改后仍然使用旧配置

## 4.1 当前根因

当前配置保存流程大致为：

```text
App.SaveConfig
→ 如果采样周期、超时或并发变化，调用 ReloadAll(cfg)
→ 否则调用 SyncClusters(old.Clusters, cfg.Clusters)
→ 阈值变化时调用 SetAlertChecker(newAlertManager)
```

问题在于：

* `ReloadAll(cfg)` 会更新 `CollectorManager.m.cfg`。
* `SyncClusters(...)` 不会更新 `CollectorManager.m.cfg`。
* `SetAlertChecker()` 为每个 Collector 重新绑定 callback 时，又从 `m.cfg` 获取阈值。
* 因此只修改阈值时，callback 仍然捕获旧阈值。

表面现象：

```text
用户把 NodeCPU 从 80 改为 50
→ 配置文件和界面显示 50
→ 当前运行 Collector 仍按照 80 检查
→ 重启软件后才变成 50
```

## 4.2 禁止的修复方式

不得简单地在任何配置变化时调用：

```go
ReloadAll(cfg)
```

因为这会：

* 重建所有 Collector。
* 丢失当前内存快照。
* 丢失节点最后一次成功缓存。
* 页面可能短暂清空。
* 重置采集状态。
* 改变现有产品体验。

## 4.3 推荐设计：稳定 callback + 动态配置分发

推荐将告警 callback 改为稳定 callback。

每个 Collector 创建时只安装一次 callback：

```go
coll.SetOnAlert(m.dispatchAlert)
```

不要让 callback 捕获固定的：

```go
th := m.cfg.ResolveThresholds(clusterID)
```

新增 Manager 内部方法：

```go
func (m *CollectorManager) dispatchAlert(
    clusterID string,
    nodes []model.NodeMetric,
    workers []model.WorkerSnapshot,
    staleNodes map[string]bool,
) {
    m.mu.RLock()
    checker := m.alerts
    thresholds := m.cfg.ResolveThresholds(clusterID)

    clusterName := clusterID
    for _, cl := range m.cfg.Clusters {
        if cl.ID == clusterID {
            clusterName = cl.DisplayName()
            break
        }
    }
    m.mu.RUnlock()

    if checker == nil {
        return
    }

    checker.Check(
        clusterID,
        clusterName,
        thresholds,
        nodes,
        workers,
        staleNodes,
    )
}
```

要求：

1. 只在锁内复制当前 checker、阈值和名称。
2. 释放锁后再调用 `checker.Check()`。
3. 不在锁内进行数据库访问。
4. 不让 Collector callback 捕获旧阈值。
5. 不需要在每次阈值变化时遍历所有 Collector 替换 callback。

`SetAlertChecker()` 应简化为：

```go
func (m *CollectorManager) SetAlertChecker(checker AlertChecker) {
    m.mu.Lock()
    m.alerts = checker
    m.mu.Unlock()
}
```

Collector callback 在 Collector 创建时固定为 Manager 的 dispatch 方法。

## 4.4 Manager 必须保存完整的新配置

新增统一配置更新入口，例如：

```go
func (m *CollectorManager) ApplyConfig(cfg config.Config)
```

该方法至少负责：

* 更新 `m.cfg`。
* 同步集群增加、删除和 URL 修改。
* 在需要时更新全局 limiter。
* 在需要时重建 Collector。
* 在不需要重建时保留现有 Collector 和快照。

可以拆成多个内部方法，但外部必须有明确的统一入口。

配置分类建议：

### 需要重建 Collector

```text
SampleEvery
TimeoutSec
Concurrency
GlobalConcurrency
集群 PlatformURL
```

### 不需要重建 Collector

```text
Thresholds
RecoverConsecutive
RetentionDays
CleanupEveryHours
SortBy
```

阈值变化必须在下一次告警检查中生效。

## 4.5 配置保存推荐顺序

建议将 `App.SaveConfig()` 调整为：

```text
1. 深复制输入配置
2. 标准化
3. Validate
4. 原子写入磁盘
5. Manager ApplyConfig
6. 更新 Alert Manager 的 RecoverConsecutive
7. 必要时重启 retention cleanup
8. 最后更新 App 内存 cfg
```

如果运行时更新方法可能返回错误，则：

* 不能返回保存成功。
* 需要明确错误信息。
* 不得留下磁盘配置、App 配置、Manager 配置三者互相不一致。

若运行时更新方法被设计为不会失败，应通过代码结构保证这一点。

---

# 五、问题二：`RecoverConsecutive` 热更新不得重置报警状态

## 5.1 当前风险

当前实现可能通过以下方式应用新恢复次数：

```go
a.alerts = alert.NewManager(a.store, cfg.RecoverConsecutive)
```

这会新建 Alert Manager，并丢失内存中的：

```go
belowCnt map[string]int
```

例如：

```text
报警要求连续 3 次低于阈值后恢复。
某报警当前已连续低于 2 次。
用户只修改其他阈值，或者把恢复次数从 3 改成 4。
代码重建 AlertManager。
原有计数 2 被清零。
```

这会改变报警生命周期。

## 5.2 目标实现

不要为了更新 `RecoverConsecutive` 重建 Alert Manager。

为 `alert.Manager` 增加：

```go
func (m *Manager) UpdateRecoverConsecutive(n int)
```

要求：

1. 对 n 做合理保护，n 小于 1 时使用默认值或拒绝。
2. 在线程安全的锁区间更新。
3. 保留 `belowCnt`。
4. 不替换 Store。
5. 不替换整个 Manager。
6. 下一次恢复判断立即使用新值。

需要检查当前 `checkMetric()` 对 `recoverN` 的读取是否线程安全。

推荐在一次锁操作中同时读取：

```go
cnt := m.belowCnt[key]
recoverN := m.recoverN
```

避免一处有锁、一处无锁。

## 5.3 修改后的预期行为

```text
旧 RecoverConsecutive = 3
当前连续低于次数 = 2
修改 RecoverConsecutive = 4

下一轮低于阈值后：
连续次数 = 3
仍不恢复

再下一轮低于阈值后：
连续次数 = 4
恢复
```

不允许重新从 0 开始。

---

# 六、问题三：告警 callback 存在潜在 data race

## 6.1 当前风险

Collector 当前包含：

```go
onAlert func(...)
```

`SetOnAlert()` 可能在配置保存线程中写入它。

采集线程同时可能执行：

```go
if c.onAlert != nil {
    c.onAlert(...)
}
```

这构成函数指针的并发读写。

普通 `go test -race` 通过不代表没有风险，只说明现有测试没有同时触发：

```text
Collector 正在采集
+
用户同时保存阈值配置
```

## 6.2 必须实现线程安全访问

即使采用稳定 callback 方案，也要使 Collector 的 callback 字段本身线程安全。

可以新增独立锁：

```go
type Collector struct {
    // ...
    alertMu sync.RWMutex
    onAlert AlertCallback
}
```

定义类型：

```go
type AlertCallback func(
    clusterID string,
    nodes []model.NodeMetric,
    workers []model.WorkerSnapshot,
    staleNodes map[string]bool,
)
```

Setter：

```go
func (c *Collector) SetOnAlert(fn AlertCallback) {
    c.alertMu.Lock()
    c.onAlert = fn
    c.alertMu.Unlock()
}
```

Getter：

```go
func (c *Collector) alertCallback() AlertCallback {
    c.alertMu.RLock()
    fn := c.onAlert
    c.alertMu.RUnlock()
    return fn
}
```

调用：

```go
fn := c.alertCallback()
if fn != nil {
    fn(clusterID, nodes, workers, staleNodes)
}
```

禁止：

```go
c.alertMu.RLock()
defer c.alertMu.RUnlock()
c.onAlert(...)
```

不能在 callback 执行期间持锁，否则配置保存可能被数据库操作长时间阻塞。

## 6.3 Callback 参数必须是安全副本

调用 callback 前：

* Nodes 使用复制后的切片。
* Workers 使用复制后的切片。
* `staleNodes` 使用新 map。
* 不暴露 Collector 内部 map。
* 不暴露可能继续被采集线程修改的底层切片。

---

# 七、问题四：App 中 Alert Manager 指针并发访问

## 7.1 当前风险

以下方法读取：

```text
a.alerts
```

* `ListAlerts`
* `CountAlerts`
* `AckAlert`

配置保存可能同时替换：

```go
a.alerts = alert.NewManager(...)
```

这是另一个潜在 data race。

## 7.2 推荐解决方案

优先采用：

```text
Alert Manager 不再被替换
→ 只原地更新 RecoverConsecutive
→ a.alerts 指针在 startup 后保持稳定
```

这是首选方案。

即使指针不再被正常替换，也应让 App 字段访问具有明确同步语义。

可以使用现有 `a.mu`，但不要持有 App 锁执行数据库操作。

推荐 helper：

```go
func (a *App) alertManager() *alert.Manager {
    a.mu.Lock()
    am := a.alerts
    a.mu.Unlock()
    return am
}
```

然后：

```go
func (a *App) ListAlerts(clusterID string) []model.Alert {
    am := a.alertManager()
    if am == nil {
        return nil
    }
    // 释放 App 锁后调用
    ...
}
```

也可以增加专用 `sync.RWMutex`。

要求：

* App 锁只保护指针复制。
* 数据库调用期间不持 App 锁。
* 不引入死锁。
* 不让配置保存长时间阻塞 UI 查询。

---

# 八、问题五：健康统计中的 Failed、Stale 和 Missing 必须区分

## 8.1 当前错误语义

当前存在类似：

```go
StaleNodeCount = len(failedNodeSet)
```

但失败节点分为两类：

### Stale

该节点本轮失败，但存在上一轮成功数据。

```text
CurrentStale = true
HasCachedData = true
```

### Missing

该节点本轮失败，而且从未成功采集或没有可复用数据。

```text
CurrentStale = false
HasCachedData = false
```

Missing 节点不能计入 Stale。

## 8.2 正确统计定义

```text
FailedNodeCount
    本轮详情请求失败的全部节点数量。

StaleNodeCount
    本轮失败且正在沿用历史数据的节点数量。

MissingNodeCount
    本轮失败且没有任何可复用历史数据的节点数量。
```

建议在 `CollectionHealth` 增加：

```go
MissingNodeCount int `json:"missingNodeCount"`
```

这是向后兼容的新增字段。

计算方式必须基于最终 `NodeCollectionState`：

```go
failedCount := 0
staleCount := 0
missingCount := 0

for each failed node:
    failedCount++

    if state.CurrentStale {
        staleCount++
    } else if !state.HasCachedData {
        missingCount++
    }
```

必须满足：

```text
FailedNodeCount = StaleNodeCount + MissingNodeCount
```

除非未来增加第三类失败状态；本次实现中应保持上述关系。

## 8.3 Reused 数量

```text
StaleWorkerCount
    只统计正在沿用的 Worker 数量。

StaleActorCount
    只统计正在沿用的 Actor 数量。
```

没有缓存的 Missing 节点不应增加这两个数量。

---

# 九、问题六：节点从 summary 消失后应立即从当前快照移除

## 9.1 当前行为风险

当前成功 summary 已经：

* 从 `snap.Nodes` 移除消失节点。
* 删除 `workersByNode`。
* 删除 `actorsByNode`。
* 删除 `nodeState`。
* 删除 `prevActorsByNode`。

但还需要确认：

```text
snap.Workers
snap.Actors
snap.Health.FailedNodes
```

是否也在同一轮 summary 后立即移除该节点。

如果只删除缓存而不清理当前可见快照，会出现短暂状态：

```text
Nodes 中节点 B 已消失
但 Workers 中仍显示节点 B 的进程
```

该状态可能一直持续到下一轮 detail 完成。

## 9.2 目标行为

成功 summary 返回当前节点集合后，在同一个锁区间：

1. 更新 `snap.Nodes`。
2. 删除消失节点缓存。
3. 从 `snap.Workers` 过滤消失节点。
4. 从 `snap.Actors` 过滤消失节点。
5. 从 `snap.Health.FailedNodes` 过滤消失节点。
6. 重新计算健康统计中与节点有关的数量。
7. 删除 diff 基线。
8. 保持剩余数据排序稳定。

只有 summary 请求成功时才执行删除。

summary 请求失败时：

* 保留旧节点。
* 保留旧 Worker/Actor。
* 不把所有节点解释为已经下线。

## 9.3 并发要求

整个节点集合切换必须对 Snapshot 调用者表现为原子状态。

不能让调用者看到：

```text
新 Nodes + 旧 Workers
```

建议先在局部变量构造：

```go
nextNodes
nextWorkers
nextActors
nextHealth
```

最后一次性持锁提交。

---

# 十、问题七：前端提示必须准确说明具体失败类型

## 10.1 当前问题

`CurrentIncomplete` 可能由以下任一原因产生：

```text
节点详情失败
Cluster 汇总失败
Jobs 请求失败
```

但当前前端可能统一显示：

```text
部分节点的进程数据暂未更新
```

当只有 Cluster 或 Jobs 请求失败时，这个文案不准确。

## 10.2 不再使用单一互斥 NoticeLevel

当前可能使用：

```ts
type NoticeLevel = 'active' | 'recent' | 'storage' | null
```

一个互斥状态容易隐藏组合问题。例如：

```text
节点详情失败
+
数据库写入失败
```

只显示其中一个。

推荐改为：

```ts
interface CollectionNoticeState {
  nodeDetailStale: boolean
  clusterStale: boolean
  jobsStale: boolean
  storageError: boolean
  recentRecovered: boolean
}
```

或者由纯函数返回数组：

```ts
type NoticeKind =
  | 'node-detail'
  | 'cluster'
  | 'jobs'
  | 'storage'
  | 'recent-recovered'

function getCollectionNotices(
  health: CollectionHealth | null | undefined,
  now: number,
): NoticeKind[]
```

## 10.3 文案要求

### 节点详情失败并有缓存

```text
部分节点的进程数据暂未更新，当前列表中包含最近一次成功采集的数据。
失败节点：2/10；沿用节点：1；沿用进程：37。
```

### 节点详情失败且无缓存

```text
其中 1 个节点暂无可用的历史进程数据，该节点的进程未显示。
```

### Cluster 汇总失败

```text
集群汇总指标暂未更新，当前显示最近一次成功采集的数据。
```

### Jobs 请求失败

```text
作业列表暂未更新，当前显示最近一次成功采集的数据。
```

### 存储失败

```text
当前数据可以显示，但历史数据写入失败。请检查数据库路径、磁盘空间或文件权限。
```

### 当前已恢复但一分钟内发生过失败

```text
过去 1 分钟内曾发生数据采集不完整，当前已恢复。
```

当能够确定具体类型时，可以显示：

```text
过去 1 分钟内曾发生节点详情采集失败，当前已恢复。
```

## 10.4 组合场景

以下组合必须全部显示，不能互相覆盖：

```text
节点详情失败 + Jobs 失败
节点详情失败 + 存储失败
Cluster 失败 + Jobs 失败
节点详情失败 + Cluster 失败 + 存储失败
```

可以使用一个统一 Banner，内部显示多行；也可以显示多个紧凑 Banner。

不得使用阻塞弹窗。

## 10.5 一分钟提示

保持现有规则：

```ts
health.currentIncomplete === false
&& health.lastIncompleteTs > 0
&& now - health.lastIncompleteTs <= 60_000
```

提示需要自动消失，不能等待下一次后端快照。

组件卸载时清理 timer。

---

# 十一、测试任务

所有新增测试必须可重复，不依赖真实 Ray 集群，不使用真实一分钟等待。

## 11.1 真实 v1 SQLite 迁移测试

新增：

```go
func TestOpenMigratesV1SchemaBeforeCreatingIndexes(t *testing.T)
```

测试不能通过当前 `Open()` 创建数据库后再修改。

必须直接使用 `database/sql` 手工创建旧表，模拟真实 v1：

* 表存在。
* 没有 `cluster_id`。
* `worker_snapshot` 没有 `gpu_used`。
* `worker_snapshot` 没有 `process_name`。
* `alert` 没有 `cluster_name`。
* `alert` 没有 `node_name`。
* 有至少一行旧数据。

关闭原始 DB 后调用：

```go
store, err := Open(path)
```

断言：

1. `Open()` 成功。
2. 所有需要的 `cluster_id` 已存在。
3. Worker 新字段已存在。
4. Alert 新字段已存在。
5. 所有新索引创建成功。
6. 五个独立清理 ts 索引存在。
7. 旧数据仍然存在。
8. 新数据可以写入。
9. 查询方法可以正常使用。
10. 再次关闭并 `Open()` 仍成功，迁移幂等。

使用：

```sql
PRAGMA table_info(...)
PRAGMA index_list(...)
```

验证，不要只断言没有报错。

## 11.2 阈值单独修改热生效测试

新增：

```go
func TestThresholdOnlyConfigChangeUsesNewThresholds(t *testing.T)
```

推荐场景：

```text
初始 WorkerCPU 阈值 = 80
Worker CPU = 60
首次检查不触发报警

只修改 WorkerCPU 阈值 = 50
不重建 Collector
不重启 Manager

下一次检查触发报警
```

同时断言：

* Collector 实例指针未改变，或 Snapshot 未清空。
* 运行状态保持不变。
* 新阈值在下一次检查中立即生效。
* Manager 内部 cfg 已更新。

## 11.3 `RecoverConsecutive` 保留状态测试

新增：

```go
func TestRecoverConsecutiveHotUpdatePreservesBelowCount(t *testing.T)
```

步骤：

1. 创建一个未恢复报警。
2. `RecoverConsecutive=3`。
3. 连续两次低于阈值。
4. 修改为 `RecoverConsecutive=4`。
5. 再低于一次，不恢复。
6. 再低于一次，恢复。

断言原来的两次计数没有丢失。

另测从 5 修改为 2：

* 若当前累计次数已经达到 2，则下一次检查时按新规则恢复。
* 不要求修改配置瞬间自动恢复，除非产品明确这样设计。

## 11.4 Callback 并发 race 测试

新增：

```go
func TestSetAlertCheckerConcurrentWithCollection(t *testing.T)
```

测试需要真实产生并发：

* 一个 goroutine 循环执行采集或直接调用告警分发路径。
* 一个 goroutine 循环修改阈值或设置 checker。
* 一个 goroutine 循环读取 Snapshot。
* 使用 channel 控制开始和结束。
* 至少执行数百或数千次轻量操作。

必须通过：

```bash
go test -race ./collector -run TestSetAlertCheckerConcurrentWithCollection -count=20
```

测试不能只顺序调用 Setter 和 Getter。

## 11.5 App Alert Manager 并发测试

新增：

```go
func TestAlertManagerAccessConcurrentWithConfigUpdate(t *testing.T)
```

并发执行：

* `ListAlerts`
* `CountAlerts`
* `AckAlert`
* 更新 `RecoverConsecutive`
* 更新阈值配置

断言：

* 无 race。
* 无 panic。
* 无死锁。
* Store 调用仍正常。

## 11.6 节点移除立即清理测试

新增：

```go
func TestSuccessfulSummaryImmediatelyRemovesNodeFromVisibleSnapshot(t *testing.T)
```

步骤：

### 第一轮

```text
summary 返回 A、B
detail A 和 B 都成功
A、B 都有 Worker 和 Actor
B 有 nodeState 和 prevActorsByNode
```

### 第二轮

```text
summary 成功，只返回 A
尚未运行下一轮 detail
```

立即调用 `Snapshot()`。

断言：

* Nodes 不包含 B。
* Workers 不包含 B。
* Actors 不包含 B。
* Health.FailedNodes 不包含 B。
* `workersByNode` 不包含 B。
* `actorsByNode` 不包含 B。
* `nodeState` 不包含 B。
* `prevActorsByNode` 不包含 B。

另测 summary 请求失败：

```go
func TestFailedSummaryDoesNotRemoveExistingNodes(t *testing.T)
```

断言 A、B 全部保留。

## 11.7 Stale 和 Missing 统计测试

新增：

```go
func TestFailedNodeWithoutCacheIsMissingNotStale(t *testing.T)
```

场景：

```text
A 成功
B 首次详情请求失败
```

断言：

```text
FailedNodeCount = 1
StaleNodeCount = 0
MissingNodeCount = 1
StaleWorkerCount = 0
StaleActorCount = 0
```

再新增：

```go
func TestFailedNodeWithCacheIsStale(t *testing.T)
```

断言：

```text
FailedNodeCount = 1
StaleNodeCount = 1
MissingNodeCount = 0
```

## 11.8 前端提示纯函数测试

至少覆盖：

```text
仅节点详情失败，有缓存
仅节点详情失败，无缓存
仅 Cluster 失败
仅 Jobs 失败
仅存储失败
节点详情 + Cluster
节点详情 + Jobs
节点详情 + 存储
Cluster + Jobs + 存储
恢复后 30 秒
恢复后 60 秒边界
恢复后超过 60 秒
无任何异常
```

断言文案不能出现错误类型。

例如只有 Jobs 失败时，不能出现：

```text
部分节点的进程数据暂未更新
```

## 11.9 UI timer 清理测试

测试组件卸载后：

```text
setInterval 已清理
无后续 state update
无测试警告
```

---

# 十二、人工验收场景

## 场景一：阈值热修改

1. 启动一个集群。
2. 等待有稳定 Worker 数据。
3. 将 WorkerCPU 阈值设置为高于当前值，确认不报警。
4. 只修改 WorkerCPU 阈值为低于当前值。
5. 不停止采集，不重启程序。

预期：

* 下一轮采集后触发报警。
* 页面 Snapshot 不清空。
* Worker 列表不闪烁。
* Collector 运行状态不改变。
* 日志显示使用新阈值。

## 场景二：恢复次数热修改

1. 制造一个报警。
2. 使指标连续两轮低于阈值。
3. 把恢复次数从 3 改为 4。
4. 再进行一轮低值。
5. 再进行一轮低值。

预期：

* 第三次低值时不恢复。
* 第四次低值时恢复。
* 原有两轮计数没有丢失。

## 场景三：节点真正下线

1. 初始 summary 返回 A、B。
2. A、B 均采集成功。
3. 下一次 summary 成功，但只返回 A。
4. 在下一次 detail 前读取界面。

预期：

* B 节点立即消失。
* B Worker 和 Actor 立即消失。
* 不出现无节点归属的 Worker。
* 不显示 B 的失败提示。
* 不生成伪造的 Actor DEAD 事件。

## 场景四：节点首次失败

1. A 成功。
2. B 从第一次详情请求就失败。

预期：

* Failed=1。
* Missing=1。
* Stale=0。
* 文案说明 B 无历史数据。
* 不显示“沿用 B 的历史进程”。

## 场景五：不同接口独立失败

分别制造：

```text
只有 Cluster 失败
只有 Jobs 失败
只有节点详情失败
只有存储失败
```

预期：

* 每种情况显示对应文案。
* 不把 Cluster 或 Jobs 失败说成进程采集失败。
* 多个问题同时出现时全部可见。

## 场景六：配置保存与采集并发

在采集循环运行期间快速反复修改：

```text
NodeCPU
WorkerCPU
RecoverConsecutive
```

预期：

* 无崩溃。
* 无死锁。
* 无 Worker 列表清空。
* 无 race。
* 最后一次保存的配置生效。

---

# 十三、质量门槛

在 `ray_api` 目录执行：

```bash
gofmt -w .

go test ./...
go test -race ./...
go test ./... -count=20
go vet ./...

cd frontend
npm ci
npx vitest run
npm run build
cd ..

wails build
```

额外执行重点测试：

```bash
go test -race ./collector -run 'TestSetAlertCheckerConcurrentWithCollection|TestThresholdOnlyConfigChangeUsesNewThresholds' -count=20

go test -race ./alert -run 'TestRecoverConsecutiveHotUpdatePreservesBelowCount' -count=20

go test ./storage -run 'TestOpenMigratesV1SchemaBeforeCreatingIndexes' -count=20
```

最后执行：

```bash
git diff --check
git status --short
```

要求：

* 所有命令退出码为 0。
* 无 race。
* 无 flaky。
* 无 TypeScript 错误。
* 无未清理 timer。
* 无未使用变量或 import。
* 无格式问题。
* 不提交 `node_modules`。
* 不提交 SQLite 文件。
* 不提交日志。
* 不提交构建中间目录。
* 仓库若原本跟踪 Wails bindings，则更新后的 bindings 需要提交。
* 构建生成的 exe 是否提交按仓库现有规则处理，不得擅自加入版本库。

---

# 十四、提交建议

建议拆为以下提交：

```text
fix(ray-api): make alert config hot reload use current manager config
fix(ray-api): make alert callbacks and manager access race-free
fix(ray-api): distinguish stale and missing collection nodes
fix(ray-api): show reason-specific collection health notices
test(ray-api): add migration hot-reload and concurrency regressions
```

每个提交应保持可构建。

不要将其他项目的无关格式化或重构混入提交。

---

# 十五、最终交付报告

完成后提交一份报告，必须包含：

## 15.1 基准信息

```text
开始时 main HEAD
最终分支
最终 HEAD SHA
9967ea8 是否为祖先
是否存在未提交文件
```

## 15.2 修改文件

逐个说明：

* 文件路径。
* 修改目的。
* 是否涉及并发。
* 是否涉及 JSON/API 变化。
* 是否涉及数据库迁移。

## 15.3 阈值热更新说明

明确回答：

* Manager 的 cfg 在何时更新。
* Collector callback 是否捕获阈值。
* 阈值修改后第几轮生效。
* 是否重建 Collector。
* Snapshot 是否保留。

## 15.4 `RecoverConsecutive` 说明

明确回答：

* Alert Manager 是否被替换。
* `belowCnt` 是否保留。
* 新恢复次数何时生效。
* 并发访问如何保护。

## 15.5 锁设计

列出：

```text
App 哪个锁保护哪些字段
Collector 哪个锁保护 callback
Collector 哪个锁保护 Snapshot
Manager 哪个锁保护 cfg 和 alerts
Alert Manager 哪个锁保护 recoverN 和 belowCnt
```

说明任何 callback 和数据库操作是否在释放锁后调用。

## 15.6 健康状态语义

明确给出：

```text
FailedNodeCount
StaleNodeCount
MissingNodeCount
StaleWorkerCount
StaleActorCount
```

的定义和关系。

## 15.7 UI 截图

至少提供：

* 节点详情失败截图。
* Cluster 失败截图。
* Jobs 失败截图。
* 存储失败截图。
* 多问题组合截图。
* 恢复后一分钟内截图。

## 15.8 测试结果

完整列出：

```text
go test ./...
go test -race ./...
go test ./... -count=20
go vet ./...
npx vitest run
npm run build
wails build
```

包括退出状态和测试数量。

## 15.9 已知限制

不得隐瞒：

* Ray Dashboard 私有接口可能随 Ray 版本变化。
* GPU 指标表示资源分配率，不是显卡硬件利用率。
* 应用未运行时不会采集。
* 两次采样之间的瞬时变化可能无法记录。
* 首次详情失败的节点没有可复用历史数据。

---

# 十六、完成定义

只有以下条件全部满足，任务才算完成：

1. 只修改阈值时，下一次告警检查使用新阈值。
2. 阈值修改不重建 Collector。
3. 阈值修改不清空 Snapshot。
4. `RecoverConsecutive` 修改不丢失已有恢复计数。
5. Collector callback 无并发读写。
6. App Alert Manager 指针无并发读写。
7. Manager cfg 和 alert checker 的访问线程安全。
8. 成功 summary 移除节点后，节点及其 Worker/Actor 立即从当前快照消失。
9. summary 请求失败不会删除现有节点。
10. Failed、Stale 和 Missing 统计准确。
11. Cluster、Jobs、节点详情和存储失败显示准确文案。
12. 多种失败同时发生时不会互相遮盖。
13. 一分钟恢复提示按时自动消失。
14. 真实 v1 数据库迁移测试通过。
15. 并发配置更新回归测试通过 race detector。
16. 全部后端、前端和 Wails 构建质量门槛通过。
17. 没有无关产品功能变化。
