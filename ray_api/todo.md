# `ray_api` 稳定性与数据完整性改造任务书

你需要修改并完整测试以下仓库中的 `ray_api` 项目：

```text
仓库：https://github.com/StupidArthur/supcon_tools.git
项目目录：ray_api
基准分支：main
```

## 一、任务总目标

在不删除、不隐藏、不重新定义现有产品功能的前提下，对 `ray_api` 做一轮完整的稳定性改造。

必须解决以下问题：

1. 某些节点详情接口暂时失败时，进程列表突然减少，恢复后又增多。
2. 出现部分节点数据未获取到时，界面没有明确提示。
3. Actor ID 在解析过程中丢失。
4. 多处数据库写入错误被忽略，采集状态却仍被记录为成功。
5. `GlobalConcurrency` 配置没有真正限制所有集群的总 HTTP 并发。
6. HTTP 请求没有绑定采集器的 `context.Context`，停止采集不能及时取消请求。
7. 六项阈值配置中只有部分实际生效。
8. Worker 内存和 GPU 阈值缺乏一致、明确的百分比计算方式。
9. SQLite 原始快照数据无限增长。
10. 相对数据库路径的实际打开位置和界面显示位置不一致。
11. 保存配置失败时，内存配置可能已经被修改。
12. 集群配置缺少后端重复 ID、空 URL、非法 URL 等校验。
13. Ray Dashboard 接口返回格式异常或字段缺失时，可能被错误解释为合法的零值数据。
14. Actor/Job 状态事件可能受到不完整采集结果污染。
15. 采集状态无法区分“全部成功”“部分成功”“沿用旧数据”“存储失败”等情况。
16. 修复与当前实现不一致的注释、指标语义和测试缺口。

本次改造属于可靠性修复，不要改产品导航结构、主要页面结构、已有配置项含义和已有操作流程。

---

# 二、开始修改前必须完成的工作

## 2.1 创建独立分支

创建分支：

```bash
git checkout main
git pull --ff-only
git checkout -b fix/ray-api-collection-integrity
```

不要直接向 `main` 提交。

## 2.2 核对代码版本

开始修改前检查以下文件。如果文件内容或 blob SHA 已变化，先阅读最新实现，再按本任务的行为要求适配，不要机械套用旧代码。

当前审查时的文件版本：

```text
ray_api/collector/collector.go
blob: dcb78ceb056582ebb38c29606f973f1ed99440f5

ray_api/collector/ray_client.go
blob: ca63d440501ff1fc24135f9507b0c4d2aaea0f3b

ray_api/collector/manager.go
blob: 94d4ca0d3b9b2055349b168fa4fdf80155727a69

ray_api/model/model.go
blob: 765272eefd9ba8b202069c114cbafb8b98f80f41

ray_api/app.go
blob: a9416f87a9d5dccd41e9d587fa2e109fae11625c

ray_api/config/config.go
blob: 94d2857a53a4828c06e3bbc564cdb5b1d53985fd

ray_api/alert/alert.go
blob: 76290dd18909ce45a1ae3e0d1eb312cbe933a2d4

ray_api/storage/store.go
blob: 51ff312edaf9dd3bb01d98a8a8161553615336e7

ray_api/frontend/src/App.tsx
blob: 2e395d9eb070f9bb79a9f32c8d4b90a86edf6406

ray_api/frontend/src/lib/api.ts
blob: 7ecf3907ee26243330dfeba543154b4550f04b49
```

## 2.3 建立修改前基线

在 `ray_api` 目录执行并记录结果：

```bash
go test ./...
go vet ./...

cd frontend
npm ci
npm run build
cd ..

wails build
```

若基线本身失败，不要直接忽略。记录：

* 失败命令
* 错误输出
* 是否属于环境问题
* 是否属于仓库原有问题
* 本次修改是否会处理该问题

不得通过删除测试、关闭 TypeScript 严格检查、跳过构建步骤来制造通过结果。

---

# 三、强制兼容约束

必须遵守以下约束：

1. 保留现有 Wails 桌面应用形态。
2. 保留现有多集群能力。
3. 保留现有“启动全部、停止全部、启动单集群、停止单集群”行为。
4. 保留现有节点、进程、报警、概览页面。
5. 不擅自新增 Actor 或 Job 导航标签。
6. 不修改现有配置字段的含义。
7. 新增 JSON 字段必须向后兼容；旧配置文件必须能直接启动。
8. 不因为单个节点失败而清空整个集群的数据。
9. 不把沿用的旧数据伪装成本轮新采集数据写入数据库。
10. 不使用陈旧数据触发新报警或推进报警恢复计数。
11. 不因为数据库写入失败而停止向界面展示已经成功获取的数据。
12. 不在日志或界面中显示 Cookie、认证信息或完整敏感响应内容。
13. 不通过简单增加超时时间掩盖根本问题。
14. 除非确有必要，不增加新的运行时依赖。
15. 所有并发状态必须能通过 `go test -race`。

---

# 四、核心改造一：节点详情失败时保留上一轮数据

## 4.1 当前错误行为

当前 `collectDetail` 会并发请求所有节点详情，然后把成功节点的 Worker 和 Actor 聚合为新切片。

失败节点被直接跳过，随后执行类似：

```go
c.snap.Workers = workers
c.snap.Actors = actors
```

这会使失败节点上一轮的数据消失。

## 4.2 目标行为

采集器必须按节点维护最后一次成功的详情数据：

```go
workersByNode map[string][]model.WorkerSnapshot
actorsByNode  map[string][]model.ActorSnapshot
```

建议同时维护：

```go
nodeDetailState map[string]NodeCollectionState
```

每轮详情采集时执行以下规则。

### 节点成功

对该节点：

1. 用本轮 Worker 完整替换该节点旧 Worker。
2. 用本轮 Actor 完整替换该节点旧 Actor。
3. 更新该节点最近成功时间。
4. 将连续失败次数清零。
5. 清除当前陈旧状态。
6. 本轮成功结果可以写入数据库。
7. 本轮成功结果可以参与报警检查。
8. 本轮成功结果可以参与 Actor 状态 diff。

### 节点失败，但存在历史成功数据

对该节点：

1. 保留上一轮 Worker。
2. 保留上一轮 Actor。
3. 不修改这些对象原有的 `Ts`。
4. 标记该节点当前使用陈旧数据。
5. 更新最近失败时间和失败原因。
6. 连续失败次数加一。
7. 不把保留的数据再次写入数据库。
8. 不让这些数据参与报警触发或报警恢复。
9. 不使用失败结果更新 Actor diff 基线。
10. 不因为失败生成 Actor 消失、死亡或状态变化事件。

### 节点失败，且从未成功采集过

对该节点：

1. 不伪造 Worker 或 Actor。
2. 节点详情状态中明确记录“没有可复用数据”。
3. 界面提示该节点本轮缺失。
4. 其他成功节点的数据正常显示。

### 节点从成功的 summary 结果中消失

若 `/nodes?view=summary` 本轮请求整体成功，并且某个旧节点不再出现在本轮节点列表：

1. 认为该节点已经不属于当前活动节点集合。
2. 删除该节点的 Worker/Actor 内存缓存。
3. 删除该节点的详情健康状态。
4. 不再把该节点数据拼入当前快照。

注意：当前 `refreshSnapshotNodes` 是旧数据与新数据的并集合并，可能永久保留已经消失的节点。必须改为：

* 以本轮成功 summary 返回的节点集合为主体。
* 只为仍然存在的相同 NodeID 合并 detail 中的权威字段。
* 不保留本轮 summary 中不存在的旧节点。

若 summary 请求本身失败，则保留旧节点快照，不执行节点删除。

## 4.3 合并顺序

最终 Worker 和 Actor 列表必须按稳定顺序输出，避免每轮因 map 遍历导致界面抖动。

建议排序：

```text
Worker：NodeID -> PID -> ProcessName
Actor：NodeID -> ActorID -> PID
Node：Hostname -> IP -> NodeID
```

必须使用稳定排序。

## 4.4 快照线程安全

当前 `Snapshot()` 只浅复制结构体，切片可能仍共享底层数组。

必须返回真正的快照副本：

* 复制 `Nodes`
* 复制 `Workers`
* 复制 `Actors`
* 复制 `Jobs`
* 复制健康状态中的切片
* 不向调用方暴露采集器内部 map 或可变切片

`go test -race` 不得报告快照与采集更新之间的数据竞争。

---

# 五、核心改造二：采集完整性状态模型

## 5.1 新增模型

在 `model` 或 `collector` 包中新增清晰的数据结构。字段名可以按项目风格微调，但语义必须完整。

推荐：

```go
type NodeCollectionState struct {
    NodeID              string `json:"nodeId"`
    NodeName            string `json:"nodeName"`
    LastAttemptTs       int64  `json:"lastAttemptTs"`
    LastSuccessTs       int64  `json:"lastSuccessTs"`
    LastFailureTs       int64  `json:"lastFailureTs"`
    ConsecutiveFailures int    `json:"consecutiveFailures"`
    LastError           string `json:"lastError"`

    CurrentStale        bool `json:"currentStale"`
    HasCachedData       bool `json:"hasCachedData"`
    ReusedWorkerCount   int  `json:"reusedWorkerCount"`
    ReusedActorCount    int  `json:"reusedActorCount"`
}
```

推荐增加：

```go
type CollectionHealth struct {
    LastDetailAttemptTs         int64 `json:"lastDetailAttemptTs"`
    LastCompleteDetailSuccessTs int64 `json:"lastCompleteDetailSuccessTs"`
    LastIncompleteTs            int64 `json:"lastIncompleteTs"`

    CurrentIncomplete bool `json:"currentIncomplete"`

    TotalNodeCount       int `json:"totalNodeCount"`
    FreshNodeCount       int `json:"freshNodeCount"`
    FailedNodeCount      int `json:"failedNodeCount"`
    StaleNodeCount       int `json:"staleNodeCount"`
    StaleWorkerCount     int `json:"staleWorkerCount"`
    StaleActorCount      int `json:"staleActorCount"`

    ClusterDataStale bool `json:"clusterDataStale"`
    JobsDataStale    bool `json:"jobsDataStale"`

    LastStorageErrorTs int64  `json:"lastStorageErrorTs"`
    LastStorageError   string `json:"lastStorageError"`

    FailedNodes []NodeCollectionState `json:"failedNodes"`
}
```

在 `collector.Snapshot` 中增加：

```go
Health model.CollectionHealth `json:"health"`
```

新增字段必须兼容旧前端和旧数据，不修改已有字段名称。

## 5.2 时间语义

必须严格区分：

```text
LastDetailAttemptTs
    最近一次发起 detail 采集的时间。

LastCompleteDetailSuccessTs
    最近一次所有计划节点、cluster、jobs 和必要存储步骤均成功的时间。

LastIncompleteTs
    最近一次发生任一数据获取不完整的时间。

CurrentIncomplete
    当前快照中是否仍含陈旧或缺失数据。
```

不要只存一个 `RecentIncomplete bool`，因为布尔值会随时间失真。后端传时间戳，前端按当前时间判断“最近一分钟”。

## 5.3 错误信息清理

`LastError` 和 `LastStorageError` 必须：

* 截断到合理长度，例如 300 或 500 字符。
* 不包含 Cookie。
* 不包含响应完整 body。
* 可以包含接口阶段、HTTP 状态码、超时和节点 ID。
* 节点 ID、主机名、接口路径可显示。

---

# 六、核心改造三：界面显示一分钟内的数据缺失提示

## 6.1 显示位置

增加一个独立组件，例如：

```text
frontend/src/components/CollectionHealthNotice.tsx
```

显示在当前选中集群页面中：

* `TopBar` 下方或标签栏下方
* 页面内容上方
* 不使用阻塞式弹窗
* 不覆盖现有操作按钮
* 不修改导航结构

## 6.2 提示状态

### 状态 A：当前仍存在缺失或陈旧数据

条件：

```ts
health.currentIncomplete === true
```

显示黄色或橙色提示：

```text
部分节点的进程数据暂未更新，当前列表中包含最近一次成功采集的数据。
失败节点：2/10；沿用进程：37；最近失败：12:34:56。
```

若某节点从未成功采集：

```text
其中 1 个节点暂无可用的历史进程数据。
```

可折叠显示：

* 失败节点名称
* NodeID 的缩略形式
* 最近失败时间
* 连续失败次数
* 简化后的错误原因
* 是否沿用了历史数据
* 沿用的 Worker/Actor 数量

### 状态 B：当前已经恢复，但一分钟内发生过失败

条件：

```ts
health.currentIncomplete === false &&
health.lastIncompleteTs > 0 &&
Date.now() - health.lastIncompleteTs <= 60_000
```

显示较弱的黄色提示：

```text
过去 1 分钟内曾发生节点详情采集失败，当前已恢复，列表已更新为最新数据。
```

该提示必须在最后一次不完整采集发生满一分钟后自动消失。

不能只依赖下一次后端数据变化。前端需要有本地时间刷新机制：

* 提示存在时每秒更新一次当前时间；或
* 使用等效的定时器确保 60 秒后自动隐藏。

组件卸载时必须清理定时器。

### 状态 C：数据库写入失败

若数据已成功获取，但数据库写入失败：

```text
当前数据可以显示，但历史数据写入失败。请检查数据库路径、磁盘空间或文件权限。
```

该提示应与“节点数据未获取”文案区分。

## 6.3 进程列表中的陈旧数据标记

`WorkersView` 应接收 `Snapshot.Health`。

对于来自 `CurrentStale=true` 节点的进程：

* 不删除
* 不改变排序
* 增加轻量“旧数据”或“未刷新”标记
* Tooltip 显示“该节点本轮采集失败，当前显示最近一次成功数据”
* 不把整行变成不可读状态
* 不将其误标为进程已停止

不要求把 `stale` 字段加入数据库模型。前端可通过 `health.failedNodes` 中的 NodeID 判断。

## 6.4 Sidebar 状态

可以把最近不完整采集表示为橙色状态，但不要替换现有运行/停止含义。

建议优先级：

```text
停止：灰色
运行且当前不完整：橙色
运行且正常：绿色
```

“过去一分钟发生过但当前已恢复”不必改变侧边栏颜色，页面提示即可。

---

# 七、核心改造四：Cluster 和 Jobs 请求失败时保留旧值

当前 `FetchJobs` 失败后可能把 `jobs` 设为 `nil`，随后覆盖当前快照。

必须改为：

### Cluster 请求成功

* 更新快照 Cluster。
* 写入数据库。
* 标记 `ClusterDataStale=false`。

### Cluster 请求失败

* 保留上一轮 Cluster。
* 标记 `ClusterDataStale=true`。
* 更新 `LastIncompleteTs`。
* 不写入伪造的零值 ClusterMetric。

### Jobs 请求成功

* 更新 Jobs 快照。
* 参与 Job diff。
* 写入数据库。
* 标记 `JobsDataStale=false`。

### Jobs 请求失败

* 保留上一轮 Jobs。
* 标记 `JobsDataStale=true`。
* 更新 `LastIncompleteTs`。
* 不执行 Job diff。
* 不写入空列表。
* 不把所有作业临时从界面移除。

首次请求失败且无历史数据时，可以显示空列表，但必须有健康提示。

---

# 八、修复 Actor ID 丢失

`detailEnvelope` 中 Actor 是：

```go
Actors map[string]rawActor `json:"actors"`
```

map 的 key 才是 Actor ID。

必须将：

```go
for _, a := range d.Actors
```

改成等效的：

```go
for actorID, a := range d.Actors {
    actors = append(actors, model.ActorSnapshot{
        ActorID: actorID,
        // 其他字段
    })
}
```

同时满足：

1. Actor ID 不得为空，除非上游 map key 本身为空。
2. 空 key 要记录解析警告，但不能 panic。
3. 测试至少包含两个 Actor，确认两个 ID 均保留。
4. `diffActors` 不得因为空 ID 把多个 Actor 合并为一项。
5. 按 ActorID 稳定排序。
6. Actor 事件数据库中的 `actor_id` 必须正确。

---

# 九、修复 Actor/Job diff 的不完整数据污染

## 9.1 Actor diff

不要用一个不完整的 `allActors` 替换全局 `prevActors`。

推荐按节点维护：

```go
prevActorsByNode map[string]map[string]model.ActorSnapshot
```

仅对本轮成功的节点执行：

1. 取该节点上一轮 Actor。
2. 与该节点本轮 Actor 对比。
3. 生成状态变化事件。
4. 替换该节点的 diff 基线。

失败节点：

* 保留原 diff 基线。
* 不生成任何状态变化事件。
* 恢复采集后，使用上次成功基线和当前成功结果做比较。

节点从成功 summary 中确认移除时，可以移除该节点 diff 基线。

## 9.2 Job diff

仅在 Jobs 请求成功时执行 Job diff。

Jobs 请求失败时：

* 保留上一轮 `prevJobs`。
* 不生成状态事件。
* 不把基线设置为空。

---

# 十、修复数据库错误被忽略的问题

禁止继续使用：

```go
_ = c.store.Write...
```

所有存储调用必须检查错误，包括：

* `WriteNodeMetrics`
* `WriteWorkers`
* `WriteActors`
* `WriteJobs`
* `WriteCluster`
* `WriteActorEvents`
* `WriteJobEvents`
* 告警相关的 `UpdateAlert`
* `AddAlertEvent`
* 其他现有无检查的写操作

## 10.1 数据获取成功但写库失败时

必须执行：

1. 更新内存快照，让界面仍能显示成功获取的数据。
2. 记录明确的存储错误。
3. 增加错误计数。
4. 更新 `LastStorageErrorTs`。
5. 不更新 `LastCompleteDetailSuccessTs`。
6. 不把整个采集轮次标记为完全成功。
7. 界面显示存储失败提示。
8. 日志包含具体失败阶段。

## 10.2 多项写入错误

不要遇到第一项错误后完全跳过后续独立写入。

可以收集错误：

```go
var storeErrs []error
```

最终用：

```go
errors.Join(storeErrs...)
```

或等效方式统一记录。

每项错误必须带阶段，例如：

```text
write node metrics node=<id>
write workers
write actors
write jobs
write cluster
write actor events
write job events
```

## 10.3 不写入陈旧缓存

当节点详情失败而沿用旧 Worker/Actor 时：

* 内存快照可以包含旧数据。
* 数据库只能写本轮成功节点产生的新数据。
* 不得重复插入旧对象。
* 不得给旧对象改成本轮时间戳。
* 不得以旧数据伪造一轮成功的历史快照。

---

# 十一、重新定义采集状态，但保持向后兼容

现有：

```go
type CollectorStatus struct {
    Running       bool
    LastSuccessTs int64
    ErrCount      int
    LastError     string
}
```

可以保留原字段并新增：

```go
LastErrorTs          int64
LastErrorStage       string
LastCompleteDetailTs int64
CurrentIncomplete    bool
```

语义要求：

```text
LastSuccessTs
    保持兼容，可表示最近一次成功完成某个采集阶段。

LastCompleteDetailTs
    最近一次完整详情轮次成功。

LastError
    最近尚未被完整成功轮次覆盖的错误。

ErrCount
    累计错误数，不因成功清零。

CurrentIncomplete
    当前详情快照是否仍含缺失或陈旧内容。
```

不要让 summary 成功立即清除同一时期仍存在的 detail 节点失败错误。

一个完整 detail 轮次成功后，才可以清除“当前不完整”状态。

---

# 十二、让全局并发限制真正生效

当前 Manager 创建了 `globalSem`，但请求没有真正 acquire/release。

## 12.1 实现要求

所有集群的所有 HTTP 请求必须共享同一个全局 limiter，包括：

* `/nodes?view=summary`
* `/nodes/{id}`
* `/api/cluster_status`
* `/api/jobs/`

推荐定义内部接口：

```go
type RequestLimiter interface {
    Acquire(ctx context.Context) error
    Release()
    Capacity() int
}
```

或使用线程安全的等效实现。

Manager 创建一个共享 limiter，并注入所有 Client。

## 12.2 获取令牌必须支持取消

禁止无条件阻塞：

```go
sem <- struct{}{}
```

必须使用：

```go
select {
case sem <- struct{}{}:
    // acquired
case <-ctx.Done():
    return ctx.Err()
}
```

释放必须用 `defer`，且只在成功 acquire 后释放。

## 12.3 局部与全局并发

节点详情请求同时受两个限制：

```text
单集群节点详情并发 <= Config.Concurrency
全部集群全部 HTTP 请求并发 <= Config.GlobalConcurrency
```

summary、cluster、jobs 至少受全局并发限制。

## 12.4 性能统计

`GlobalPerf.GlobalConcurrency` 必须报告真实 limiter 容量。

建议增加：

```text
当前正在执行请求数
全局并发峰值
等待 limiter 的请求数或累计等待时间
```

这些字段可以新增，但不要求改变现有页面。

---

# 十三、让 HTTP 请求受 Context 控制

将 Client API 改为接受 context，例如：

```go
FetchNodes(ctx context.Context)
FetchNodeDetail(ctx context.Context, nodeID string)
FetchCluster(ctx context.Context)
FetchJobs(ctx context.Context)
```

底层请求必须使用：

```go
http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
```

或：

```go
req = req.WithContext(ctx)
```

停止采集时必须能够：

1. 取消正在等待全局 limiter 的请求。
2. 取消正在等待局部 semaphore 的任务。
3. 取消正在进行的 HTTP 请求。
4. 避免在取消后继续写入快照或数据库。
5. 不把正常的用户停止操作记录成异常故障。

日志中应区分：

```text
context canceled
deadline exceeded
HTTP status error
JSON parse error
```

对主动 Stop 导致的 `context.Canceled`，使用 debug/info，而不是污染错误计数。

---

# 十四、完整实现六项阈值

当前配置包含：

```text
NodeCPU
NodeMEM
NodeGPU
WorkerCPU
WorkerMEM
WorkerGPU
```

六项都必须有明确实现。

## 14.1 Node CPU

若 Ray `/nodes` 的 CPU 字段按当前支持版本表示百分比，则：

```text
node CPU percentage = NodeMetric.CPU
```

修正错误注释“CPU 负载（核数）”。

必须用 fixture 测试确认当前支持的 Ray 返回样本中，该字段确实按百分比解析。

若不同 Ray 版本语义不一致，必须：

* 在解析层明确检测。
* 不要悄悄猜测。
* 在健康状态或日志中提示指标不可用。
* 不对不可确认的指标触发报警。

## 14.2 Node MEM

```text
NodeMEM% = MemUsed / MemTotal × 100
```

`MemTotal <= 0` 或 `IsPartial=true` 时跳过。

## 14.3 Node GPU

当前 NodeMetric 的 `GPUUsed` 没有可靠填充。

在节点详情解析中，把该节点 Actor 的：

```go
RequiredResources["GPU"]
```

按节点合计，写入：

```go
NodeMetric.GPUUsed
```

计算：

```text
NodeGPU% = GPUUsed / GPUTotal × 100
```

`GPUTotal <= 0` 时跳过。

该指标是“GPU 分配率”，不是显卡硬件利用率。代码注释、界面 Tooltip 和报警描述必须准确，不要写成物理 GPU utilization。

## 14.4 Worker CPU

```text
WorkerCPU% = WorkerSnapshot.CPUPercent
```

## 14.5 Worker MEM

以所在节点总内存为分母：

```text
WorkerMEM% = Worker.MemRSS / Node.MemTotal × 100
```

找不到节点或节点总内存为零时跳过，不得按 0% 参与报警恢复。

## 14.6 Worker GPU

Worker 的 `GPUUsed` 是该 PID 上 Actor 分配 GPU 数量之和。

计算：

```text
WorkerGPU% = Worker.GPUUsed / 所在节点 GPUTotal × 100
```

找不到节点或节点无 GPU 时跳过。

同样明确该指标是“分配率”，不是硬件繁忙率。

## 14.7 陈旧数据不得推进报警状态机

对本轮失败节点沿用的 Worker/Node 数据：

* 不触发新报警。
* 不更新报警最近值。
* 不增加恢复连续次数。
* 不消除报警。
* 不生成重复 trigger 事件。

只有本轮新鲜数据参与阈值检查。

## 14.8 告警存储错误

`UpdateAlert`、`AddAlertEvent` 等错误不能被忽略。

事件写入失败时至少：

* 记录日志。
* 返回或聚合错误。
* 不声称整个告警处理成功。

---

# 十五、统一数据库路径解析

当前启动时直接：

```go
storage.Open(cfg.DBPath)
```

而 `GetDBPath()` 会把相对路径解释为可执行文件目录下的路径，两者可能不一致。

新增统一 helper，例如：

```go
func ResolveRuntimePath(path string, baseDir string) string
```

规则：

1. 绝对路径原样清理后使用。
2. 相对路径统一基于可执行文件目录解析。
3. startup 打开数据库和 `GetDBPath()` 必须调用同一函数。
4. 打开数据库前创建父目录。
5. 日志记录最终解析后的绝对路径。
6. 测试不要依赖真实 `os.Executable()`，将 baseDir 作为可注入参数测试。
7. Windows 与 Unix 路径都不得通过字符串拼接实现。

必须保证：

```text
界面显示路径 == 实际 SQLite 文件路径
```

---

# 十六、配置保存原子性与一致性

## 16.1 App 内存状态

当前 `SaveConfig` 在磁盘保存前就修改 `a.cfg`。

必须调整为：

1. 深复制输入配置。
2. 标准化并校验。
3. 原子保存到磁盘。
4. 保存成功后更新 Manager。
5. Manager 更新成功后再更新 `a.cfg`。
6. 任一步失败，原内存配置和运行中 Collector 保持不变。

`AddCluster`、`RemoveCluster`、`UpdateCluster` 同样采用 copy-on-write，不能先修改 `a.cfg` 再保存。

不要在释放锁后直接读取可能被其他 goroutine 修改的 `a.cfg` 切片。

## 16.2 原子写配置文件

`config.Save` 不应直接覆盖正式文件。

实现：

1. 在相同目录创建临时文件。
2. 写完整 JSON。
3. `Sync` 临时文件。
4. 关闭文件。
5. 原子 rename 替换正式文件。
6. 必要时同步目录。
7. 失败时清理临时文件。
8. 主路径不可写时继续使用现有 fallback 逻辑。
9. 不留下半截 JSON。

## 16.3 配置校验

后端必须校验：

### 集群

* ID 去除首尾空格后非空。
* ID 唯一。
* URL 去除首尾空格后非空。
* URL scheme 只能是 `http` 或 `https`。
* URL 必须有 host。
* 同一个标准化 URL 不应重复。
* Update 的 ID 必须存在。
* Remove 的 ID 必须存在；若产品当前允许幂等删除，可返回成功但必须明确记录。

### 数值

建议范围：

```text
SampleEvery: 1～3600 秒
TimeoutSec: 1～300 秒
Concurrency: 1～1000
GlobalConcurrency: 1～5000
RecoverConsecutive: 1～100
所有阈值: 0～100
RetentionDays: 1～3650
```

阈值 `0` 继续表示禁用该项报警。

错误返回要能让前端显示具体原因，例如：

```text
duplicate cluster id: prod
invalid platform URL: missing host
globalConcurrency must be >= concurrency
```

不要 panic。

## 16.4 Manager 配置同步

确保保存以下字段后运行中采集器真正应用新值：

* SampleEvery
* TimeoutSec
* Concurrency
* GlobalConcurrency
* Thresholds
* RecoverConsecutive
* Clusters

当前只依据 SampleEvery 和 URL 判断是否重建是不够的。

实现统一的：

```go
ApplyConfig(oldCfg, newCfg)
```

或等效机制。

要求：

* Manager 内部 `m.cfg` 必须更新。
* 阈值变化必须更新告警回调。
* Timeout/Concurrency/SampleEvery 变化必须应用到 Client/Collector。
* GlobalConcurrency 变化必须应用到共享 limiter。
* 已启动集群保持启动。
* 已停止集群保持停止。
* 不因纯阈值变化短暂清空界面快照。
* 重建 Collector 时尽可能继承现有快照和每节点缓存，避免配置保存后页面突然空白。

---

# 十七、SQLite 数据保留策略

## 17.1 新配置

增加：

```go
RetentionDays      int `json:"retentionDays,omitempty"`
CleanupEveryHours int `json:"cleanupEveryHours,omitempty"`
```

默认：

```text
RetentionDays = 90
CleanupEveryHours = 6
```

旧配置缺少字段时自动补默认值。

这是为了限制高频原始快照增长，不改变现有页面和查询入口。

## 17.2 清理范围

按时间清理以下原始快照表：

```text
node_metric
worker_snapshot
actor_snapshot
job_snapshot
cluster_metric
```

默认永久保留：

```text
actor_event
job_event
alert
alert_event
```

不要删除尚未消除的报警。

## 17.3 执行方式

1. 启动后异步执行一次清理。
2. 此后按 `CleanupEveryHours` 执行。
3. 不阻塞 Wails 启动。
4. 受 App context 控制，退出时停止。
5. 使用批量删除，避免一次事务锁库过久。
6. 每批例如 5000 或 10000 行。
7. 清理操作写结构化日志，包括表、删除行数、cutoff 和耗时。
8. 执行 `PRAGMA optimize`。
9. 可执行被动 WAL checkpoint。
10. 不要每次自动 `VACUUM`，避免长时间独占数据库。
11. 删除后的页面查询必须继续正常。
12. 清理失败不能导致采集器退出，但必须有日志和健康状态。

建议增加：

```go
CleanupBefore(cutoff int64) (CleanupResult, error)
```

便于单元测试。

## 17.4 索引

检查清理涉及的表是否有以 `ts` 或 `(cluster_id, ts)` 开头的索引。

缺少时通过兼容迁移增加，避免全表扫描。

---

# 十八、增强 Ray HTTP 与解析容错

## 18.1 Envelope 校验

对于包含：

```json
{"result": false}
```

的响应，不得当作合法空数据。

必须返回包含接口路径的错误。

## 18.2 非 200 响应

错误中包含：

* 路径
* HTTP 状态码
* 最多前 512 字节的响应摘要

摘要必须清理换行和敏感信息。

## 18.3 响应大小限制

使用合理的读取上限，例如 64 MiB。

超过限制时返回明确错误，避免异常响应导致内存无限增长。

不要把正常大集群合法响应限制得过小。

## 18.4 cluster status 正则解析

`autoscalingStatus` 是文本，可能随 Ray 版本变化。

要求：

1. 保留当前已支持格式。
2. 为至少两种 spacing/换行变化增加 fixture。
3. 如果原文本非空但 CPU、MEM、GPU、heartbeat 全部无法解析，返回“格式不支持”或解析不完整状态。
4. 不要用全零 ClusterMetric 覆盖上一轮有效值。
5. 日志记录 Ray 版本或响应格式线索时，不记录完整大文本。
6. 把正则解析封装为纯函数并单独测试。

## 18.5 节点详情的 NodeID

若 detail 返回的 `raylet.nodeId` 为空，但请求路径中的 NodeID 非空：

* 使用请求 NodeID 作为回退。
* 记录解析警告。
* 不让 Worker/Actor 落到空 NodeID。

## 18.6 字段兼容

为 Ray 返回中的以下变化添加 fixture 测试：

* 数字或字符串形式的 CPU
* 缺失 memory
* 无 GPU key
* 空 workers
* 空 actors
* 多 Actor map
* Actor 字段缺失
* gzip 正常
* gzip body 损坏
* HTTP 非 200
* `result=false`
* 无法识别的 cluster status 文本

---

# 十九、日志要求

统一使用结构化日志。

每一轮 detail 至少记录：

```text
clusterID
totalNodes
freshNodes
failedNodes
staleNodes
freshWorkers
totalDisplayedWorkers
reusedWorkers
freshActors
totalDisplayedActors
reusedActors
jobsFresh
clusterFresh
detailMs
maxNodeMs
slowNodeID
complete
storageOK
```

单节点失败日志包含：

```text
clusterID
nodeID
nodeName
stage
durationMs
consecutiveFailures
hasCachedData
reusedWorkerCount
reusedActorCount
errorKind
error
```

恢复日志：

```text
node detail recovered
clusterID
nodeID
failedDurationMs
previousConsecutiveFailures
```

禁止：

* 打印 Cookie。
* 打印完整响应 body。
* 每 5 秒重复打印完全相同的大段错误。
* 用 info 记录所有 Worker/Actor 对象。

可对连续失败做有限日志降噪，但首次失败和恢复必须记录。

---

# 二十、测试要求

所有测试必须可重复，不依赖真实 Ray 环境。

优先使用：

* `httptest.Server`
* Fake Store
* Fake Clock
* 可控 limiter
* 临时 SQLite
* 固定 JSON fixture

不要在时间相关测试中真实等待一分钟。

## 20.1 Actor ID 测试

新增：

```text
TestFetchNodeDetailPreservesActorIDs
```

输入包含两个 Actor：

```json
"actors": {
  "actor-id-1": {...},
  "actor-id-2": {...}
}
```

断言：

* 返回两个 Actor。
* ID 分别正确。
* diff map 不发生覆盖。
* 写入事件时 ID 正确。

## 20.2 部分节点失败并保留缓存

新增类似：

```text
TestCollectDetailRetainsLastGoodNodeDataOnPartialFailure
```

步骤：

### 第一轮

* 节点 A、B、C 全部成功。
* A 有 2 个 Worker。
* B 有 3 个 Worker。
* C 有 4 个 Worker。
* 快照总数为 9。

### 第二轮

* A、C 成功。
* B 超时。
* A、C 返回更新数据。
* B 保留上一轮 3 个 Worker。

断言：

* 界面快照仍包含 B 的 3 个 Worker。
* 列表不会从 9 项骤降为 6 项。
* B 对应状态 `CurrentStale=true`。
* `FailedNodeCount=1`。
* `CurrentIncomplete=true`。
* `LastIncompleteTs` 已更新。
* B Worker 的原始 `Ts` 未被改成本轮时间。
* B Worker 没有再次写入数据库。
* B Worker 没有参与报警检查。
* B Actor 没有参与 diff。
* A、C 的本轮数据正常写入。
* 总体列表顺序稳定。

## 20.3 从未成功的失败节点

新增：

```text
TestCollectDetailMarksMissingNodeWithoutFabricatingData
```

断言：

* 不生成假 Worker。
* `HasCachedData=false`。
* 提示统计正确。

## 20.4 恢复行为

新增：

```text
TestCollectionHealthKeepsRecentFailureForOneMinuteAfterRecovery
```

使用 fake clock：

1. 节点失败。
2. 下一轮恢复。
3. `CurrentIncomplete=false`。
4. `LastIncompleteTs` 保留。
5. 59 秒时前端 helper 判断应显示“最近失败”。
6. 60 秒或 61 秒后不显示。

明确统一边界：

```ts
now - lastIncompleteTs <= 60_000
```

或：

```ts
< 60_000
```

选择一种并在测试中固定。

## 20.5 summary 节点移除

新增：

```text
TestSuccessfulSummaryRemovesMissingNodesAndTheirCachedDetails
```

第一轮 A、B，第二轮成功 summary 只有 A。

断言：

* B 从节点快照移除。
* B Worker/Actor 缓存移除。
* B 健康状态移除。
* A 保留 detail 权威字段。

另测 summary 请求失败时，A、B 都保留。

## 20.6 Cluster/Jobs 保留

新增：

```text
TestClusterFailureKeepsPreviousClusterMetric
TestJobsFailureKeepsPreviousJobsAndDiffBaseline
```

断言：

* 失败不覆盖旧值。
* 失败不生成事件。
* 恢复后再正常 diff。

## 20.7 存储错误

Fake Store 对每个写方法分别返回错误。

至少测试：

```text
TestDetailStoreErrorDoesNotReportCompleteSuccess
TestSnapshotStillUpdatesWhenStorageFails
TestStaleRowsAreNotPersisted
```

断言：

* 错误计数增加。
* 错误阶段正确。
* `LastCompleteDetailSuccessTs` 不更新。
* Snapshot 可显示新数据。
* Storage 健康提示存在。
* 不再存在未检查的 `_ = store.Write...`。

## 20.8 全局并发

建立两个或三个 Collector，共享 limiter。

服务器 handler：

* 记录当前并发数。
* 延迟返回。
* 记录峰值。

测试：

```text
TestGlobalConcurrencyIsSharedAcrossCollectors
```

断言：

```text
峰值 HTTP 并发 <= GlobalConcurrency
单集群节点详情峰值 <= Concurrency
```

使用 `-count=20` 运行，避免偶然通过。

## 20.9 Context 取消

测试：

```text
TestRequestWaitingForLimiterCanBeCanceled
TestInflightHTTPRequestCanBeCanceled
TestStopDoesNotIncrementFailureForContextCanceled
```

handler 阻塞直到 request context done。

断言停止后请求快速返回，不等待完整 `TimeoutSec`。

不要用极短时间窗口制造 flaky 测试，可用 channel 同步。

## 20.10 六项阈值

为六项阈值分别写触发、低于阈值、不具备分母三个方向的测试。

至少覆盖：

```text
NodeCPU
NodeMEM
NodeGPU
WorkerCPU
WorkerMEM
WorkerGPU
```

断言：

* 所有阈值都真正被调用。
* WorkerMEM 使用所在节点总内存。
* WorkerGPU 使用所在节点 GPU 总数。
* 无分母时跳过，而不是按 0 推进恢复。
* 陈旧节点数据不参与。
* 连续恢复次数只由新鲜数据推进。

## 20.11 配置原子性

测试：

```text
TestSaveConfigFailureLeavesRuntimeConfigUnchanged
TestAddDuplicateClusterRejected
TestInvalidClusterURLRejected
TestAtomicSaveNeverLeavesPartialJSON
TestOldConfigLoadsWithNewDefaults
```

模拟保存失败时：

* `a.cfg` 不变。
* Manager 不变。
* Collector 启停状态不变。

## 20.12 数据库路径

测试 helper：

```text
relative path + base dir
absolute path
带 .. 的路径
父目录不存在
```

断言实际创建文件路径和显示路径完全一致。

## 20.13 Retention

临时 SQLite 中写入：

* cutoff 之前的快照。
* cutoff 之后的快照。
* Actor events。
* Job events。
* Alerts。

执行 cleanup 后断言：

* 旧快照删除。
* 新快照保留。
* 事件保留。
* 报警保留。
* 清理可重复执行。
* 清理中途 context cancel 能停止。
* 数据库仍可正常采集和查询。

## 20.14 前端提示逻辑

把提示判断提取为纯函数，例如：

```ts
getCollectionNotice(health, now)
```

增加前端单元测试。允许增加 Vitest 作为开发依赖，但不要增加运行时依赖。

至少测试：

```text
当前失败
恢复后 30 秒
恢复后超过 60 秒
无失败历史
只有存储错误
失败节点有缓存
失败节点无缓存
```

组件测试或人工测试还需验证：

* 展开失败节点详情。
* 组件卸载后 timer 清理。
* 切换集群时显示对应集群状态。
* 停止采集后不会误报“停止导致失败”。

---

# 二十一、验收场景

以下场景全部通过，才可认为完成。

## 场景 1：正常采集

给定：

* 三个节点全部成功。
* 共 100 个 Worker。

预期：

* 显示 100 个。
* 无完整性提示。
* `CurrentIncomplete=false`。
* `LastCompleteDetailSuccessTs` 更新。
* 数据正常写库。
* 告警正常检查。

## 场景 2：一个节点短暂超时

给定：

* 第一轮 100 个 Worker。
* 第二轮节点 B 超时，B 上一轮有 30 个 Worker。

预期：

* 仍显示 100 个左右的完整合并结果，具体取决于其他节点本轮真实增减。
* B 的 30 个旧 Worker 保留。
* B 的行显示“未刷新”。
* 页面出现黄色提示。
* 提示明确说明沿用上一轮数据。
* B 的旧 Worker 不重复写库。
* B 的旧 Worker 不参与报警。
* 不生成错误 Actor 事件。
* `CurrentIncomplete=true`。

## 场景 3：节点恢复

给定：

* 下一轮 B 成功。

预期：

* B 数据用最新结果替换。
* “当前不完整”状态清除。
* 页面继续显示“过去一分钟曾失败，当前已恢复”。
* 最后一次失败满一分钟后提示自动消失。
* 不需要用户刷新页面。

## 场景 4：失败节点无历史数据

预期：

* 其他节点正常显示。
* 不伪造该节点进程。
* 提示“该节点暂无历史可用数据”。

## 场景 5：数据库只读或磁盘满

预期：

* 新采集数据仍显示在界面。
* 显示历史写入失败提示。
* 日志有明确存储阶段。
* 不更新完整成功时间。
* 不 panic。
* 采集循环继续尝试下一轮。

## 场景 6：多个大集群同时运行

预期：

* 所有请求总并发不超过 `GlobalConcurrency`。
* 每个集群节点详情并发不超过 `Concurrency`。
* 停止应用后等待请求迅速取消。
* 无 goroutine 泄漏。
* 无 data race。

## 场景 7：六项阈值

预期：

* 六项配置均可触发。
* 无数据分母时不误触发或误恢复。
* GPU 文案明确为分配率。

## 场景 8：配置保存失败

预期：

* 内存配置不变。
* 磁盘旧配置不损坏。
* Manager 运行状态不变。
* 前端收到明确错误。

## 场景 9：运行超过保留周期

预期：

* 原始快照表的数据量进入稳定范围。
* 事件与报警保留。
* 清理不长时间锁死采集。
* WAL 可正常复用。

---

# 二十二、最终构建与质量门槛

完成后必须运行：

```bash
cd ray_api

gofmt -w .
go test ./...
go test -race ./...
go test ./... -count=20
go vet ./...

cd frontend
npm ci
npm run test -- --run
npm run build
cd ..

wails build
```

若前端没有 `test` script，补充 Vitest 配置和 script。

还需运行：

```bash
git diff --check
git status --short
```

验收要求：

* 所有命令成功。
* 无 data race。
* 无 TypeScript 错误。
* 无未使用 import。
* 无格式错误。
* 无被忽略的数据库写入错误。
* 无 `_ = c.store.Write...`。
* 不通过删除断言或降低测试严格性获得通过。
* 生成的 Wails bindings 若仓库跟踪，则一并提交。
* 不提交构建产物、数据库、日志、临时配置或 `node_modules`。

---

# 二十三、人工调试方法

为了真实验证 UI，增加只用于开发或测试的故障注入方式，不得默认在正式构建中开启。

可选实现：

```text
环境变量 RAY_MONITOR_TEST_FAIL_NODE=<nodeID>
环境变量 RAY_MONITOR_TEST_FAIL_STAGE=node-detail|cluster|jobs|storage
```

或在测试 fake server 中提供切换接口。

要求能够演示：

1. 全部节点成功。
2. 指定节点连续失败两轮。
3. 进程列表没有骤降。
4. 页面出现当前失败提示。
5. 失败节点进程显示“未刷新”。
6. 节点恢复。
7. 页面显示一分钟内恢复提示。
8. 一分钟后自动消失。

最终报告中提供：

* 正常状态截图。
* 当前部分失败截图。
* 恢复后一分钟内截图。
* 对应日志片段。
* 故障前后 Worker 数量对比。

禁止把测试故障开关暴露为正式用户功能。

---

# 二十四、提交组织

建议拆分提交：

```text
fix(ray-api): retain per-node snapshots on partial collection failure
feat(ray-api): expose collection health and recent incomplete status
feat(frontend): show collection integrity warning and stale worker markers
fix(ray-api): preserve actor ids and safe per-node event diff
fix(ray-api): propagate storage errors and separate acquisition health
fix(ray-api): enforce global request concurrency and context cancellation
fix(ray-api): implement all configured alert thresholds
fix(ray-api): make config updates atomic and validated
fix(ray-api): unify runtime database path resolution
feat(ray-api): add bounded snapshot retention cleanup
test(ray-api): add partial failure and reliability regression suite
```

每个提交应可构建，避免一个无法审查的超大提交。

---

# 二十五、最终交付报告格式

完成后必须提交一份报告，包含以下内容。

## 1. 根因说明

说明原来为何进程列表会突然减少：

```text
单节点详情失败
→ 失败节点被跳过
→ 成功节点结果整体覆盖旧快照
→ 失败节点 Worker 暂时消失
→ 下一轮恢复后重新出现
```

## 2. 修改文件清单

逐个文件说明修改目的。

## 3. 数据一致性说明

明确回答：

* 失败节点数据如何保留。
* 数据何时被认为 stale。
* stale 数据是否写库。
* stale 数据是否参与报警。
* stale 数据是否参与 diff。
* 节点真正移除时如何清理。

## 4. UI 行为说明

列出：

* 当前失败提示。
* 恢复后一分钟提示。
* 存储失败提示。
* 失败节点详情。
* 提示消失条件。

## 5. 并发与取消说明

提供：

* 单集群并发测试峰值。
* 全局并发测试峰值。
* context cancel 测试结果。
* goroutine 泄漏检查结果。
* race test 结果。

## 6. 测试结果

列出所有命令及退出状态：

```text
go test ./...
go test -race ./...
go test ./... -count=20
go vet ./...
npm run test -- --run
npm run build
wails build
```

## 7. 数据库迁移与保留策略

说明：

* 新字段默认值。
* 旧配置兼容。
* 清理表。
* 永久保留表。
* 默认保留天数。
* 清理频率。
* 索引变化。

## 8. 已知限制

不得隐瞒：

* Ray 不同版本的 Dashboard 私有接口差异。
* GPU 指标是资源分配率而非硬件利用率。
* 节点首次采集失败时没有可复用数据。
* 应用关闭期间不会继续采集。
* 采样监控无法捕获两次采样之间的所有瞬时状态。

## 9. 提交和 PR

提供：

* 分支名。
* commit 列表。
* PR 地址。
* 最终 HEAD SHA。
* 是否存在未提交文件。

---

# 二十六、禁止的“伪修复”

以下方案不得作为完成结果：

1. 只把 Timeout 从 8 秒改成 30 秒。
2. 只增加重试，但失败后仍覆盖为不完整列表。
3. 失败时完全停止刷新整个集群。
4. 每轮把旧数据重新写入数据库。
5. 给旧数据改成本轮时间戳。
6. 失败时直接显示空列表。
7. 只在日志提示，不在界面提示。
8. 只显示“采集失败”，但不说明当前展示的是旧数据。
9. 只创建 `globalSem`，不在请求路径 acquire。
10. 用 `context.Background()` 替代调用方 context。
11. 继续忽略数据库写入错误。
12. 把 Worker GPU 数量直接与 90 这个百分比阈值比较。
13. 因无法计算 Worker 内存百分比而悄悄忽略配置项。
14. 通过删除数据库历史功能解决数据库增长。
15. 通过清空旧数据库解决迁移问题。
16. 通过刷新整个 Collector 导致页面每次保存配置后短暂清空。
17. 通过移除现有配置项掩盖未实现阈值。
18. 通过关闭 race test 或跳过 Wails 构建获得通过。

---

# 二十七、完成定义

只有同时满足以下条件，任务才算完成：

* 部分节点失败时，其他节点和失败节点最后一次成功数据都能正确展示。
* 进程列表不再因单节点瞬时失败而大幅骤降。
* 当前失败和最近一分钟失败均有准确 UI 提示。
* 恢复满一分钟后提示自动消失。
* 陈旧数据不写库、不告警、不推进恢复、不污染事件。
* Actor ID 正确保留。
* 所有存储错误均被处理。
* 全局并发真实生效。
* HTTP 请求可取消。
* 六项阈值均有明确、经过测试的实现。
* 数据库路径显示和实际位置一致。
* 配置更新原子、可校验、失败可回滚。
* 原始快照有保留策略。
* 旧配置、旧数据库可无损启动。
* 后端、前端和 Wails 构建全部通过。
* Race test 通过。
* 有完整测试、截图、日志和最终报告。
