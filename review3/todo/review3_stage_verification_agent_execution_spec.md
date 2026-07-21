# review3 阶段验证套件收口与可锁定化执行规范

**文档用途：** 直接交给验收基础设施 Agent 执行。  
**适用仓库：** `StupidArthur/supcon_tools`  
**Git 根：** `G:/github/supcon_tools`  
**项目根：** `G:/github/supcon_tools/review3`  
**当前审查基线：** `82321dce61647bd0374b3350abc73dcf65efb75c`  
**相关提交：**
- `8f21ed4aa08e71d95201f9799b7365841ec88cab`：阶段 5～6 行为契约加固
- `82321dce61647bd0374b3350abc73dcf65efb75c`：阶段 7～8 prospective reviewer suites

---

# 1. 本轮任务目标

本轮不是继续增加更多验收文件，而是把现有阶段 5～8 prospective 套件修成真正可锁定、可长期执行、未来无需修改验收代码即可变绿的验收体系。

完成本轮后，必须达到：

1. 阶段 5～8 测试当前可以因业务能力缺失而失败；
2. 当对应业务能力未来实现后，同一批被锁定的验收测试可以自然通过；
3. 不存在无条件 `assert False`、`expect.fail()` 或 `t.Fatal()` 形式的永久失败；
4. 不把内部 helper、内部类、内部文件名和源码关键词当作产品契约；
5. 所有精确引用的公共名称都在受 Git 管理的验收规范中正式定义；
6. 阶段 7 并发、临时文件、实时互斥必须通过外部行为证明；
7. 阶段 8 由 Python、Go、前端和人工门禁共同组成，不要求单一测试框架模拟整个 Wails 桌面应用；
8. 本轮完成后，才能进入九个 manifest、精确锁定路径和 baseline 生命周期收口。

本轮仍然不实现阶段 5～8 业务。

---

# 2. Agent 身份与边界

你是验收基础设施 Agent。

## 2.1 允许修改

```text
review3/tools/stage_verification/**
review3/config-tool/acceptance/**
review3/config-tool/frontend/acceptance/**
review3/config-tool/frontend/vitest.acceptance.config.ts
review3/config-tool/frontend/package.json
review3/config-tool/frontend/package-lock.json
review3/todo/second_order_tank_* 中的验收规范说明
```

## 2.2 禁止修改

```text
review3/controller/engine.py
review3/datacenter/engine_api.py
review3/components/programs/pid.py
review3/components/programs/valve.py
review3/components/programs/cylindrical_tank.py
review3/components/programs/base.py
review3/datacenter/opcua_server.py
review3/config/单阀门二阶水箱.yaml
review3/config-tool/internal/** 的业务实现
review3/config-tool/frontend/src/features/** 的业务实现
```

例外：本轮不提供业务实现例外。即使测试失败，也只登记为 `ACCEPTANCE_BLOCKED`。

## 2.3 禁止的验收写法

```text
pytest.skip
pytest.mark.skip
xfail
describe.skip
test.skip
it.skip
test.only
describe.only
无条件 assert False
无条件 expect.fail
无条件 t.Fatal
只检查文件存在
只扫描源码关键词
只检查函数或类存在
通过注释中的字符串满足验收
通过建议文件名限制实现目录
固定端口
直接覆盖内置 YAML
启动进程后不在 finally/defer 中清理
```

---

# 3. 最重要的定义：Implementation-passable

所有 prospective 验收必须满足“实现后可通过”。

## 3.1 正确定义

一个 prospective 测试当前失败，是因为：

- 公共 HTTP 路由不存在；
- 公共 Binding 方法不存在；
- 公共组件或纯函数不存在；
- 公共行为与契约不一致；
- 真实外部效果尚未实现。

对应能力未来实现后，测试直接通过，不需要修改锁定验收文件。

## 3.2 错误示例

```python
assert False, "阶段 8 业务尚未实现"
```

```ts
const capabilityReady = { "STAGE8-E2E-001": true }
expect.fail(allOtherSteps)
```

```go
func TestFullWorkflowNotReady(t *testing.T) {
    t.Fatal("not implemented")
}
```

这些代码永远不会因业务实现而自动变绿，禁止进入 baseline。

## 3.3 正确示例

```python
response = client.post("/api/instances/runtime_a/writes", json=request)
assert response.status_code < 300, "STAGE5-ATOMIC-001: /writes is required"
```

当前路由不存在时失败；未来路由实现并满足行为时通过。

```ts
const module = await importContractModule(
  candidatesFor(frontendSrc("features", "runtime", "controlQuality")),
  "STAGE6-QUALITY-001",
  "computeControlQuality is required",
)
const result = module.computeControlQuality(samples, options)
expect(result.settled).toBe(true)
```

当前模块不存在时明确失败；未来模块存在并计算正确时通过。

---

# 4. 契约依据必须受 Git 管理

`review3/todo/7.md` 已停止版本跟踪，不得继续作为唯一或主要契约依据。

## 4.1 新增正式规范

新增：

```text
tools/stage_verification/acceptance/SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md
```

该文件必须受 Git 管理，并成为阶段 5～8 验收条款的正式来源。

## 4.2 更新引用

更新：

```text
tools/stage_verification/acceptance/CONTRACT_SURFACES.md
```

将所有：

```text
todo/7.md §...
```

替换为：

```text
tools/stage_verification/acceptance/SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md §...
todo/second_order_tank_repository_contracts.md
todo/second_order_tank_implementation_playbook.md
```

`todo/7.md` 可以继续作为本地 Agent 任务提示，但不得被 manifest、baseline 或 acceptance 文档引用。

## 4.3 SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md 必须包含

1. 阶段 5 `/writes` HTTP 契约；
2. 阶段 5 PID Faceplate 模式契约；
3. 阶段 5 runtime override 与 DSL 写回契约；
4. 阶段 6 趋势缓冲、事件和质量指标契约；
5. 阶段 7 Batch、CSV、下采样和互斥契约；
6. 阶段 8 跨层 E2E 步骤及各测试框架责任；
7. retrospective 与 prospective 的区别；
8. 人工 gate 的证据要求；
9. 契约编号与测试文件对应关系。

---

# 5. 固定公共契约：阶段 5

本节内容直接视为本项目正式验收契约。除非验收规范本身经过 reviewer 审核并重新记录 baseline，否则业务实现 Agent 不得自行更改。

## 5.1 原子写 HTTP API

### 路由

```http
POST /api/instances/{runtimeName}/writes
GET  /api/instances/{runtimeName}/writes/{batchId}
```

允许额外提供取消或显式过期路由，但不是核心完成条件。

### 请求

```json
{
  "writes": [
    {
      "tag": "pid2.SV",
      "value": 0.8
    },
    {
      "tag": "pid2.PB",
      "value": 25.0
    }
  ],
  "confirm_timeout_s": 3.0
}
```

规则：

- `runtimeName` 是运行实例名，例如 `acceptance_runtime`；
- `pid2` 是实例内部 program 名；
- `tag` 必须是完整 tag，例如 `pid2.SV`；
- 一次请求表示一个不可拆分的 batch；
- `confirm_timeout_s` 可选，缺省值由实现定义，但必须为有限正数。

### 接受响应

```json
{
  "ok": true,
  "batch_id": "uuid-or-stable-id",
  "status": "pending",
  "writes": [
    {"tag": "pid2.SV", "value": 0.8},
    {"tag": "pid2.PB", "value": 25.0}
  ],
  "accepted_cycle_count": 120
}
```

必须字段：

```text
ok
batch_id
status
```

`status` 在 POST 成功时必须为 `pending`，不得直接返回 `applied`。

`writes` 和 `accepted_cycle_count` 可以通过 POST 响应或后续状态查询取得，但验收必须能识别原始 batch 内容和接受时周期。

### 查询响应

```json
{
  "ok": true,
  "batch_id": "uuid-or-stable-id",
  "status": "pending|applied|failed",
  "writes": [
    {"tag": "pid2.SV", "value": 0.8},
    {"tag": "pid2.PB", "value": 25.0}
  ],
  "accepted_cycle_count": 120,
  "confirmed_cycle_count": 121,
  "error": null
}
```

语义：

- `pending`：HTTP 已接受，但尚未从同一 snapshot 周期确认全部目标；
- `applied`：同一 `cycle_count` 的 snapshot 已确认 batch 全部目标；
- `failed`：验证失败、执行失败或确认超时；
- 任意单字段成功不得使整个 batch 变为 `applied`；
- 不同 batch 的状态、ID 和内容必须隔离。

### 拒绝响应

任一写入无效时：

```text
HTTP 4xx
不得返回成功 batch_id
不得部分入队
不得部分修改 Engine
错误内容必须指出失败字段或失败原因
```

拒绝对象包括：

```text
unknown tag
pid2.PV 等只读 tag
实时液位
实时阀位
AUTO/CAS 等派生状态字段
非有限数值
违反模式约束的写值
不存在的 runtimeName
```

### 兼容路由

```http
POST /api/instances/{runtimeName}/params
```

可以继续存在，但不得被视为新的原子 batch 接口。

## 5.2 阶段 5 Python 原子写测试必须验证的时间顺序

测试不得只比较 POST 前后的当前 snapshot。

### 无效混合批次

必须执行：

```text
1. 记录 before snapshot；
2. POST 一个合法字段 + 一个非法字段；
3. 断言 4xx；
4. 断言没有成功 batch_id；
5. 驱动至少一个 Engine 周期；
6. 再次读取 snapshot；
7. 断言合法字段仍未改变；
8. 断言不存在 pending batch。
```

这可以发现“合法字段被错误部分入队但暂未应用”的缺陷。

### 合法批次

必须执行：

```text
1. 记录 before snapshot 与 before cycle_count；
2. POST 多个合法字段；
3. 断言响应 pending；
4. POST 返回后、驱动周期前再次读取 snapshot；
5. 断言所有目标均未提前应用；
6. 驱动一个 Engine 周期；
7. 读取 snapshot；
8. 断言所有目标在同一 cycle_count 出现；
9. 查询 batch；
10. 断言 applied 且 confirmed_cycle_count 等于该 snapshot 周期。
```

### 并发批次

必须明确断言：

```text
batch A id != batch B id
A 查询结果 batch_id == A id
B 查询结果 batch_id == B id
A.writes 只包含 A 的字段
B.writes 只包含 B 的字段
确认 A 不得改变 B 的状态
A 失败不得使 B 失败
```

禁止使用天然为真的弱断言，例如：

```python
sa.batch_id != id_b or sa.writes != sb.writes
```

## 5.3 PID Faceplate 公共组件

正式公共表面：

```text
PidFaceplate
```

正式输入契约：

```ts
type WriteStatus = "idle" | "pending" | "applied" | "failed"

interface PidFaceplateProps {
  mode: "AUTO" | "MAN" | "CAS"
  values: {
    PV: number | null
    SV: number | null
    CSV: number | null
    MV: number | null
    PB: number | null
    TI: number | null
    TD: number | null
    KD: number | null
    MODE: string | number | null
    SWPN: string | number | null
  }
  writeStatus: WriteStatus
  writeError?: string | null
  onSubmit: (writes: Array<{tag: string; value: number}>) => void | Promise<void>
}
```

允许通过 Store selector 提供同等数据，但测试必须通过公开 props、公开 Store 或渲染行为观察，不能要求内部常量存在。

### 模式行为

```text
AUTO：SV 可编辑，MV 禁用
MAN：MV 可编辑；SV 不得显示成实际操纵值
CAS：CSV 是有效给定；SV 不得显示成当前有效给定
PV：所有模式均只读
```

必须显示：

```text
PV
SV
CSV
MV
PB
TI
TD
KD
MODE
SWPN
pending
applied
failed
```

## 5.4 前端原子写客户端

正式公共表面：

```ts
submitAtomicWrites(input)
```

建议正式签名：

```ts
interface AtomicWriteInput {
  apiHost: string
  apiPort: number
  runtimeName: string
  writes: Array<{tag: string; value: number}>
  confirmTimeoutSeconds?: number
  signal?: AbortSignal
}

interface AtomicWriteAccepted {
  batchId: string
  status: "pending"
}

declare function submitAtomicWrites(
  input: AtomicWriteInput
): Promise<AtomicWriteAccepted>
```

验收必须验证：

```text
URL 使用 /writes
请求体一次包含完整 batch
客户端验证失败时不发 fetch
HTTP 成功后仅为 pending
部分 snapshot 匹配仍为 pending
全部目标在同一周期匹配后为 applied
超时或 API 错误为 failed
runtimeName 来自 Runtime Store，不得硬编码 pid2
```

## 5.5 Runtime override 写回 DSL

正式 Go Binding：

```go
func (b *TemplateConfigBinding) ApplyRuntimeOverrides(
    req ApplyRuntimeOverridesRequest,
) (ApplyRuntimeOverridesResult, error)
```

正式 DTO：

```go
type ApplyRuntimeOverridesRequest struct {
    TargetPath  string             `json:"targetPath"`
    ExpectedHash string            `json:"expectedHash"`
    Overrides   map[string]float64 `json:"overrides"`
    IncludeMV   bool               `json:"includeMV"`
}

type ApplyRuntimeOverridesResult struct {
    Path          string   `json:"path"`
    ContentHash   string   `json:"contentHash"`
    AppliedFields []string `json:"appliedFields"`
}
```

字段名以此为正式验收 API。业务实现可以自由选择内部文件、Service、helper 和数据结构。

### 写回规则

允许默认写回：

```text
SV
PB
TI
TD
KD
模式相关且确有组态意义的白名单字段
```

默认禁止：

```text
PV
实时 Tank level
实时 valve current_opening
实时流量
派生状态
MV
```

只有 `IncludeMV=true` 且后续正式规范允许时，MV 才可写回。

必须：

```text
使用 ExpectedHash 防冲突
保存前重新校验
校验失败文件不变
使用临时文件 + 原子替换
保存后 YAML 可被 TemplateService 和 Python DSLParser 重新加载
不得改变 running identity
```

## 5.6 Go 反射测试安全规则

在方法尚未实现时，可以通过反射避免编译失败，但反射代码不得 panic。

调用前必须检查：

```text
MethodByName 是否存在
NumIn == 1
参数 Kind == struct
参数字段名称和类型符合正式 DTO
NumOut == 2
第一个返回值类型符合 Result
第二个返回值实现 error
```

任何不匹配必须使用稳定契约编号 `t.Fatalf`，不得出现：

```text
index out of range
reflect: call of Value.IsNil
reflect: FieldByName of non-struct
reflect: Call using ...
```

方法实现后，测试必须实际断言文件效果，不能只检查签名。

---

# 6. 固定公共契约：阶段 6

## 6.1 控制品质纯函数

正式公共表面：

```ts
computeControlQuality(samples, options)
```

正式输入：

```ts
interface QualitySample {
  t: number
  pv: number | null
  sv: number | null
  mv: number | null
}

interface QualityEvent {
  t: number
  type: "parameter_applied"
}

interface QualityOptions {
  errorBand: number
  stableWindowSeconds: number
  mvLow: number
  mvHigh: number
  levelLow: number
  levelHigh: number
  events?: QualityEvent[]
}
```

正式输出：

```ts
interface QualitySegment {
  startTime: number
  endTime: number | null
  steadyStateError: number | null
  overshoot: number
  settled: boolean
  settlingTime: number | null
  mvSaturationTime: number
  levelHighHits: number
  levelLowHits: number
  invalidSampleCount: number
}

interface QualityResult extends QualitySegment {
  segments: QualitySegment[]
  archivedSegments: QualitySegment[]
}
```

允许增加字段，但以上行为必须可观察。

## 6.2 数值语义

```text
稳定窗口：连续 60 秒在误差带内才算 settled
59 秒不得算 settled
不规则采样：按时间差积分，不按样本数量累计
MV 饱和时间：按真实时间累计
液位触碰次数：按进入越界状态的边沿计数，不得每帧重复计数
NaN/Infinity：跳过或计入 invalidSampleCount，不得污染其余指标为 NaN
参数 applied 事件：结束当前 segment，归档并开启新 segment
```

## 6.3 趋势和事件

正式可观察行为：

```text
最大 1200 个真实 snapshot
FIFO 删除最旧点
heartbeat 不追加
stale 不追加
Stop 不自动清空
新 runtime 实例归档 previousRunSeries
不同实例数据不得混合
左轴：Tank 2 level、SV
右轴：MV、valve current_opening
显示 pid2.PV ← tank_2.level
曲线可开关
事件显示 pending/applied/failed
applied 时间使用 snapshot 确认时间，不使用 HTTP 返回时间
```

测试应通过公开 `TrendBuffer`、公开组件和渲染结果验证，不要求内部 `trendPolicy` 或 reducer 名称。

---

# 7. 固定公共契约：阶段 7

## 7.1 只锁定现有业务公共入口

当前正式公共入口：

```go
func (b *SystemBinding) RunBatch(
    configPath string,
    cycles int,
) (BatchResult, error)

func (b *SystemBinding) ExportBatch(
    configPath string,
    cycles int,
    exportPath string,
) error
```

不得强制业务实现导出：

```text
AllocateBatchWorkDir
CanRunBatch
BatchManager
TempDirectoryAllocator
```

这些属于内部设计。

## 7.2 并发和临时文件通过外部行为证明

当前 `RunBatch` 使用共享 `_batch_export.csv` 会产生并发覆盖风险。验收必须通过并发调用发现问题，而不是要求某个内部目录分配器存在。

### 并发验收

使用可注入的 fake DataFactory 命令或 helper process：

```text
1. 为任务 A 和 B 准备不同输出内容；
2. 同时调用 RunBatch；
3. 两个调用均完成；
4. A 的结果只包含 A 内容；
5. B 的结果只包含 B 内容；
6. 不存在交叉覆盖；
7. 执行结束后所有临时文件被清理。
```

测试可以使用现有内部测试注入能力，但 reviewer acceptance 不得要求新增导出 helper。

### 实时互斥

通过公开行为验证：

```text
1. 使 SystemBinding 处于 Running=true；
2. 调用 RunBatch 或 ExportBatch；
3. 必须返回明确错误；
4. 不启动第二个 DataFactory；
5. 不创建成功结果；
6. Stop 后可以再次执行 Batch。
```

不要求 `CanRunBatch` 方法存在。

## 7.3 Batch 结果

2000 周期验收：

```text
cycles = 2000
进程退出码为 0
CSV 存在且非空
表头正确
时间或周期列单调
行数符合明确契约
stderr/exit code 在失败时传播
空输出不能返回成功
Unicode YAML/CSV 路径有效
```

### 行数契约

实现必须在正式规范中选择并固定一种：

```text
A. 恰好 2000 行数据；
B. 包含初始点，因此 2001 行数据。
```

当前 acceptance 不能模糊使用“差不多”。在实现前由 reviewer 根据 DataFactory 的现有 batch 行为确定，并写入 fixture `expected_columns.json` 或 Stage 7 spec。

## 7.4 CSV 对话框

必须通过 Wails 对话框参数或前端 adapter 证明：

```text
YAML 打开/保存：*.yaml;*.yml
CSV 导出：*.csv
默认文件名为 .csv
CSV 导出不得复用 SaveYAMLFile
```

## 7.5 下采样

必须保持：

```text
输出 <= 3000
首点
尾点
局部极大值
局部极小值
时间顺序
小数据不重写
重复时间和缺失时间处理确定
```

如果现有 `trendBuffer.downsample` 是正式复用入口，可以直接锁定该公共函数。

---

# 8. 固定公共契约：阶段 8

阶段 8 不由一个测试文件独自完成。它是多个测试框架和人工证据的组合门禁。

## 8.1 责任划分

| 层 | 权威测试 | 负责内容 |
|---|---|---|
| Python | `test_end_to_end_acceptance.py` | 真实 DataFactory、REST、WebSocket、/writes、Batch、OPC UA、端口和进程清理 |
| Go | `application_acceptance_test.go` | Wails Binding 组合、Start/Stop、writeback、Batch 公共入口 |
| Frontend | `full_workflow.acceptance.test.tsx` | 打开、编辑、验证阻止、Faceplate、趋势、事件、Batch 页面状态 |
| Manual | stage 8 evidence | 完整桌面应用操作、视觉和设计验收 |

任何一层不得使用“其他层负责”为理由永久失败。

## 8.2 Python 阶段 8 必须改写

删除所有硬编码：

```text
fail("STAGE8-E2E-002", "missing ...")
...
assert failures
assert False
```

改为实际能力调用。

建议把测试分成多个独立测试，而不是一个 200 行的大测试：

```text
test_stage8_001_008_template_fixture_and_contract_inventory
test_stage8_009_013_real_runtime_start_and_snapshot
test_stage8_014_017_atomic_write_flow
test_stage8_018_trend_event_backend_evidence
test_stage8_019_021_writeback_restart_flow
test_stage8_022_023_batch_and_csv
test_stage8_024_025_opcua_external_write
test_stage8_026_029_cleanup_and_repo_integrity
```

当前能力不存在时，各测试在第一个真实公共调用处失败；能力实现后自然通过。

### Python 不负责的 UI 步骤

步骤 002～008 的 UI 渲染与交互由前端测试负责。Python 只需验证：

```text
scenario fixture 完整
临时模板和 Unicode 文件操作 helper 可用
对应前端 acceptance 文件存在
阶段 8 manifest 同时运行前端 acceptance
```

Python 不得因为无法驱动 Wails UI而永久失败。

## 8.3 前端阶段 8 必须改写

删除：

```ts
const capabilityReady = {
  "STAGE8-E2E-001": true,
}
expect.fail(...)
```

改成真实组件工作流。

建议拆分：

```text
打开模板并显示初值
选择全部对象
编辑 Tank 2 radius
Unicode Save As adapter
非法 SV 阻止保存和启动
恢复合法后允许启动
Faceplate 写值状态
趋势与事件显示
writeback UI
Batch 互斥与结果显示
```

每个测试动态导入正式公共组件；不存在时给稳定契约失败；存在时渲染和交互。

## 8.4 Go 阶段 8 必须改写

删除：

```go
TestAcceptanceStage8FullWorkflowNotYetGreen
```

Go acceptance 应测试真实 Binding 组合，而不是永久失败：

```text
NewSystemBinding 可构造
NewTemplateConfigBinding 可构造
Start/Stop 公共方法存在
ApplyRuntimeOverrides 公共方法符合正式 DTO
RunBatch/ExportBatch 公共方法存在
Cleanup 可安全执行
Wails app container 注册上述 Binding
```

对于尚未实现的 `ApplyRuntimeOverrides`，使用安全反射输出稳定失败；实现后继续验证行为。

不得只通过 `os.Stat(system.go)` 判断 Binding 可用。

## 8.5 阶段 8 清理规则

任何启动真实进程的测试必须：

```text
随机 API 端口
随机 OPC UA 端口
try/finally 或 defer
停止 ManagedProcess
确认 PID 不存在
确认 API 端口释放
确认 OPC UA 端口释放
确认临时 YAML/CSV 位于 tmp_path
确认内置模板 hash 不变
确认仓库 git status 没有新增运行产物
```

---

# 9. 本轮必须修改的文件

## 9.1 新增

```text
tools/stage_verification/acceptance/SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md
```

可按需要新增：

```text
tools/stage_verification/acceptance/stage_8/helpers.py
config-tool/frontend/acceptance/stage_8/helpers.ts
```

Helper 必须属于 reviewer acceptance，不得包含业务实现。

## 9.2 必须修改

```text
tools/stage_verification/acceptance/CONTRACT_SURFACES.md

tools/stage_verification/acceptance/stage_5/test_atomic_writes_acceptance.py
config-tool/acceptance/stage_5/template_writeback_acceptance_test.go

tools/stage_verification/acceptance/stage_7/test_batch_export_acceptance.py
config-tool/acceptance/stage_7/system_batch_acceptance_test.go

tools/stage_verification/acceptance/stage_8/test_end_to_end_acceptance.py
config-tool/acceptance/stage_8/application_acceptance_test.go
config-tool/frontend/acceptance/stage_8/full_workflow.acceptance.test.tsx

tools/stage_verification/acceptance/ACCEPTANCE_BLOCKED.md
```

## 9.3 按检查结果修改

```text
config-tool/frontend/acceptance/stage_5/runtime_writes.acceptance.test.ts
config-tool/frontend/acceptance/stage_5/pid_faceplate.acceptance.test.tsx
config-tool/frontend/acceptance/stage_5/writeback.acceptance.test.ts
config-tool/frontend/acceptance/stage_6/*.acceptance.test.ts*
config-tool/frontend/acceptance/stage_7/*.acceptance.test.ts*
```

---

# 10. 执行顺序

## 提交 A：规范与阶段 5 加固

建议提交：

```text
test(acceptance): define tracked contracts and strengthen stage 5
```

完成：

1. 新增正式 acceptance spec；
2. 更新 CONTRACT_SURFACES；
3. 阶段 5 无效批次增加 drive-after-reject；
4. 合法批次增加 pre-cycle 未应用断言；
5. 并发 batch 使用强断言；
6. Go writeback 反射安全；
7. 移除所有 `todo/7.md` 契约引用。

## 提交 B：阶段 7 外部行为化

建议提交：

```text
test(acceptance): verify stage 7 through public batch behavior
```

完成：

1. 删除 `AllocateBatchWorkDir` 完成条件；
2. 删除 `CanRunBatch` 完成条件；
3. 删除 `standalone_main.py` 源码字符串扫描；
4. 使用并发 helper process 验证输出隔离；
5. 验证共享临时 CSV 风险；
6. 通过 Running 状态调用 RunBatch 验证互斥；
7. 验证 Unicode、exit code、stderr、空输出和清理；
8. 保留数值下采样行为测试。

## 提交 C：阶段 8 implementation-passable

建议提交：

```text
test(acceptance): make stage 8 suites implementation-passable
```

完成：

1. 删除 Python 永久失败；
2. 拆分 Python 测试责任；
3. 删除 frontend capabilityReady 永久失败；
4. 改为真实组件和 Store 行为；
5. 删除 Go `FullWorkflowNotYetGreen`；
6. 改为真实 Binding 组合；
7. 保证所有进程和端口清理；
8. 保持 001～029 契约编号可追踪。

---

# 11. 测试命令

从 `review3` 执行。

## 11.1 验收器自测

```powershell
python -m pytest tools\stage_verification\tests -q
```

要求：

```text
exit 0
无新增失败
```

## 11.2 阶段 5～6

```powershell
python -m pytest `
  tools\stage_verification\acceptance\stage_5 `
  tools\stage_verification\acceptance\stage_6 `
  -q

Set-Location config-tool
go test ./acceptance/stage_5/... -count=1

Set-Location frontend
npm run test:acceptance -- acceptance/stage_5 acceptance/stage_6
```

允许业务契约失败，但不允许：

```text
collection error
compile error
reflect panic
fixture error
路径错误
配置错误
无稳定契约 ID 的失败
```

## 11.3 阶段 7～8

```powershell
Set-Location G:\github\supcon_tools\review3

python -m pytest `
  tools\stage_verification\acceptance\stage_7 `
  tools\stage_verification\acceptance\stage_8 `
  -q

Set-Location config-tool
go test ./acceptance/stage_7/... ./acceptance/stage_8/... -count=1

Set-Location frontend
npm run test:acceptance -- acceptance/stage_7 acceptance/stage_8
```

允许能力缺失失败，但必须：

```text
测试可收集
Go package 可编译
每个失败含 STAGE7-* 或 STAGE8-E2E-*
无永久失败占位
无残留进程
无端口占用
无仓库污染
```

## 11.4 搜索禁止模式

执行：

```powershell
rg -n `
  "assert False|expect\.fail|t\.Fatal\(|capabilityReady|not yet green|not implemented" `
  tools\stage_verification\acceptance\stage_8 `
  config-tool\acceptance\stage_8 `
  config-tool\frontend\acceptance\stage_8
```

注意：有条件的 `t.Fatal` 可以存在；必须人工确认不是无条件永久失败。

执行：

```powershell
rg -n `
  "todo/7\.md|AllocateBatchWorkDir|CanRunBatch|read_text.*batch|strings\.Contains.*batch" `
  tools\stage_verification\acceptance `
  config-tool\acceptance `
  config-tool\frontend\acceptance
```

预期：

```text
无 todo/7.md 作为正式依据
无 AllocateBatchWorkDir/CanRunBatch 强制契约
无通过源码 batch 字符串判断完成
```

---

# 12. 本轮退出条件

只有以下全部满足，才能宣布本轮完成：

```text
[ ] SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md 已受 Git 管理
[ ] CONTRACT_SURFACES 不再引用 todo/7.md
[ ] 阶段 5 无效批次会驱动周期后再确认未部分应用
[ ] 阶段 5 合法批次确认 POST 后、周期前未应用
[ ] 阶段 5 并发 batch 使用强隔离断言
[ ] Go writeback 反射不可能因签名不匹配 panic
[ ] 阶段 7 不要求 AllocateBatchWorkDir
[ ] 阶段 7 不要求 CanRunBatch
[ ] 阶段 7 不通过源码字符串判定 batch 能力
[ ] 阶段 7 通过并发外部效果验证输出隔离
[ ] 阶段 8 Python 无永久失败
[ ] 阶段 8 Frontend 无永久失败
[ ] 阶段 8 Go 无永久失败
[ ] 阶段 8 各框架责任明确
[ ] 所有真实进程在失败路径也清理
[ ] 所有测试失败均为稳定契约断言
[ ] verifier 自测仍全绿
[ ] 未修改阶段 5～8 业务实现
[ ] 未记录 baseline
[ ] 未 finalize
```

---

# 13. 本轮之后的下一批工作

本轮完成并审查通过后，才进入：

```text
批次 7：九个 manifest、精确 locked_acceptance_paths 和 baseline 生命周期收口
```

下一批包括：

1. 每阶段精确列出 reviewer acceptance 文件；
2. 将 verifier self-tests 加入每个阶段；
3. 加入 Python/Go/frontend acceptance command；
4. `verify_all.py --check-config` 九阶段通过；
5. 阶段 0～4 设置 `retrospective`；
6. 阶段 5～8 设置 `prospective`；
7. 阶段 5～8 在业务实现前记录 prospective baseline；
8. 阶段 0～4 根据 blocker 状态决定 baseline/finalize；
9. 阶段 2 Space 键 blocker 未修复前不得 finalize；
10. 不得将 expected-failing prospective suite 当作业务通过。

特别说明：

```text
prospective baseline 的目的，是锁定测试和 manifest。
它可以在业务测试仍然失败时记录。
finalize 必须等待所有自动门禁和人工门禁通过。
```

本轮不得提前做该批次。

---

# 14. 停止条件

出现以下任一情况，停止当前提交并汇报：

```text
需要修改 controller/engine.py 才能让测试本身运行
需要实现 /writes
需要实现 PidFaceplate
需要实现 controlQuality
需要实现 Batch 业务修复
需要修改内置模板
需要放宽验收契约
只能通过 skip/xfail 继续
无法避免测试永久失败
无法在失败路径清理真实进程
发现与当前 acceptance 文件重叠的未知用户修改
```

---

# 15. Agent 最终回报格式

```text
任务：阶段 5～8 prospective 验收可锁定化
结论：完成 / 部分完成 / 被阻塞

一、提交
- <SHA> <message>
- <SHA> <message>

二、正式契约
- SECOND_ORDER_TANK_ACCEPTANCE_SPEC：
- CONTRACT_SURFACES：
- 已删除的 todo/7.md 引用：

三、阶段 5 修正
- invalid batch 驱动后检查：
- pre-cycle 未应用：
- concurrent batch 隔离：
- Go 反射安全：

四、阶段 7 修正
- 删除的内部接口约束：
- 并发外部行为：
- 实时互斥：
- CSV/Unicode/清理：

五、阶段 8 修正
- Python 永久失败：
- Frontend 永久失败：
- Go 永久失败：
- 分层责任：
- 清理：

六、测试
- <完整命令> → <exit code / pass / fail>
- 失败是否均含稳定契约 ID：

七、基础设施错误
- 无 / 详情

八、业务能力缺失
- 契约 ID：
- 当前行为：
- 预期行为：

九、仓库状态
- git status --short：
- 是否修改业务实现：
- 是否记录 baseline：
- 是否 finalize：

十、是否允许进入 manifest/baseline 收口
- 是 / 否
- 依据：
```

---

# 16. Reviewer 判定标准

Reviewer 只在以下情况下回答“允许进入 manifest/baseline 收口”：

```text
阶段 5～8 的失败可以由未来业务实现自然消除；
不存在需要修改锁定测试才能变绿的硬编码失败；
公共契约定义完整且受 Git 管理；
测试证明外部行为，而不是内部命名；
真实进程、端口和临时文件生命周期可靠。
```

文件数量多、测试数量多、契约编号完整，都不能替代以上五项。
