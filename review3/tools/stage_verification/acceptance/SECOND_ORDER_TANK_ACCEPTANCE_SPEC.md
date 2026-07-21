# 单阀门二阶水箱 — 锁定验收规范

**文件：** `tools/stage_verification/acceptance/SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md`  
**状态：** 受 Git 管理的正式验收契约  
**范围：** 阶段 5～8（及 retrospective / prospective 语义）  
**非依据：** 未跟踪的本地任务提示笔记（已停止跟踪，不得作为 acceptance 依据）

相关受 Git 管理文档：

- `todo/second_order_tank_repository_contracts.md`
- `todo/second_order_tank_implementation_playbook.md`
- `tools/stage_verification/acceptance/CONTRACT_SURFACES.md`

业务实现可自由选择内部文件、helper 与数据结构；**仅下列公共表面**可作为锁定验收完成条件。

---

# 1. Retrospective 与 Prospective

| 模式 | 含义 |
|------|------|
| **retrospective** | 业务已实现；验收套件追认现状；全绿后方可 `--record-baseline` / finalize |
| **prospective** | 业务尚未实现；验收先锁定；当前允许因公共能力缺失而失败；**实现后同一批测试必须自然变绿**，不得再改锁定验收 |

Prospective 测试禁止：

- 无条件 `assert False` / `expect.fail` / `t.Fatal`（永不因实现变绿）
- skip / xfail
- 仅检查内部文件名、源码关键词、内部 helper 名

---

# 2. 阶段 5 — 原子在线写与 Faceplate / 写回

## 2.1 HTTP `/writes`

### 路由

```http
POST /api/instances/{runtimeName}/writes
GET  /api/instances/{runtimeName}/writes/{batchId}
```

### 请求

```json
{
  "writes": [
    {"tag": "pid2.SV", "value": 0.8},
    {"tag": "pid2.PB", "value": 25.0}
  ],
  "confirm_timeout_s": 3.0
}
```

- `runtimeName`：运行实例名（如 `acceptance_runtime`），来自 `/api/status.instance_name`
- `pid2`：实例内 program 名，不得与 runtimeName 混淆
- `tag`：完整位号（如 `pid2.SV`）
- 一次请求 = 一个不可拆分 batch
- `confirm_timeout_s` 可选，缺省须为有限正数

### 接受响应（必须字段 `ok` / `batch_id` / `status`）

```json
{
  "ok": true,
  "batch_id": "uuid-or-stable-id",
  "status": "pending",
  "writes": [{"tag": "pid2.SV", "value": 0.8}],
  "accepted_cycle_count": 120
}
```

POST 成功时 `status` **必须**为 `pending`，不得直接 `applied`。

### 查询响应

```json
{
  "ok": true,
  "batch_id": "...",
  "status": "pending|applied|failed",
  "writes": [...],
  "accepted_cycle_count": 120,
  "confirmed_cycle_count": 121,
  "error": null
}
```

| 状态 | 语义 |
|------|------|
| pending | HTTP 已接受，尚未在同一 snapshot 周期确认全部目标 |
| applied | 同一 `cycle_count` 的 snapshot 已确认全部目标 |
| failed | 验证失败、执行失败或确认超时 |

### 拒绝（HTTP 4xx）

- 不得返回成功 `batch_id`
- 不得部分入队 / 部分修改 Engine
- 错误须指出失败字段或原因
- 拒绝：unknown tag、`pid2.PV`、实时液位/阀位、AUTO/CAS 派生状态、非有限值、模式违规、不存在的 runtimeName

### 兼容

`POST /api/instances/{runtimeName}/params` 可保留，**不得**视为原子 batch 接口。

### 契约编号

| ID | 含义 |
|----|------|
| STAGE5-ATOMIC-001 | `/writes` 存在，不得用 `/params` 代替 |
| STAGE5-ATOMIC-002～004 | 无效混合 batch：4xx、无 batch_id、驱动周期后合法字段未应用、无 pending |
| STAGE5-ATOMIC-005～006 | 合法 batch：pending→同周期全部生效→applied |
| STAGE5-ATOMIC-007～009 | unknown / PV / AUTO·CAS 拒绝且状态不变 |
| STAGE5-ATOMIC-010 | runtimeName 先于 programName |
| STAGE5-ATOMIC-011～013 | pending / applied / failed（超时） |
| STAGE5-ATOMIC-014 | legacy `/params` 兼容存在 |
| STAGE5-ATOMIC-015 | 并发 batch ID/内容/状态隔离 |

**测试文件：** `tools/stage_verification/acceptance/stage_5/test_atomic_writes_acceptance.py`

## 2.2 PidFaceplate

公共组件：`PidFaceplate`

```ts
type WriteStatus = "idle" | "pending" | "applied" | "failed"

interface PidFaceplateProps {
  mode: "AUTO" | "MAN" | "CAS"
  values: {
    PV: number | null; SV: number | null; CSV: number | null; MV: number | null
    PB: number | null; TI: number | null; TD: number | null; KD: number | null
    MODE: string | number | null; SWPN: string | number | null
  }
  writeStatus: WriteStatus
  writeError?: string | null
  onSubmit: (writes: Array<{tag: string; value: number}>) => void | Promise<void>
}
```

模式：

- AUTO：SV 可编辑，MV 禁用
- MAN：MV 可编辑；SV 不得显示为实际操纵值
- CAS：CSV 为有效给定；SV 不得显示为当前有效给定
- PV：始终只读

须覆盖字段 PV/SV/CSV/MV/PB/TI/TD/KD/MODE/SWPN 与 pending/applied/failed。

**契约：** STAGE5-MODE-001…006  
**测试：** `config-tool/frontend/acceptance/stage_5/pid_faceplate.acceptance.test.tsx`  
**Python 交叉：** `test_pid_faceplate_acceptance.py`

## 2.3 前端 `submitAtomicWrites`

```ts
interface AtomicWriteInput {
  apiHost: string; apiPort: number; runtimeName: string
  writes: Array<{tag: string; value: number}>
  confirmTimeoutSeconds?: number; signal?: AbortSignal
}
interface AtomicWriteAccepted { batchId: string; status: "pending" }
declare function submitAtomicWrites(input: AtomicWriteInput): Promise<AtomicWriteAccepted>
```

须验证：URL `/writes`、整批 body、预校验失败不发 fetch、成功仅 pending、部分 snapshot 仍 pending、同周期全匹配 applied、超时/错误 failed、runtimeName 非硬编码 `pid2`。

**测试：** `runtime_writes.acceptance.test.ts`

## 2.4 Go `ApplyRuntimeOverrides`

```go
func (b *TemplateConfigBinding) ApplyRuntimeOverrides(
    req ApplyRuntimeOverridesRequest,
) (ApplyRuntimeOverridesResult, error)

type ApplyRuntimeOverridesRequest struct {
    TargetPath   string             `json:"targetPath"`
    ExpectedHash string             `json:"expectedHash"`
    Overrides    map[string]float64 `json:"overrides"`
    IncludeMV    bool               `json:"includeMV"`
}

type ApplyRuntimeOverridesResult struct {
    Path          string   `json:"path"`
    ContentHash   string   `json:"contentHash"`
    AppliedFields []string `json:"appliedFields"`
}
```

写回规则：

- 默认可写：SV、PB、TI、TD、KD、有组态意义的白名单模式字段
- 默认禁止：PV、实时 level、`current_opening`、实时流量、派生状态、MV（仅 `IncludeMV=true` 且规范允许时可写）
- ExpectedHash 防冲突；校验失败文件不变；原子替换；保存后可被 TemplateService / DSLParser 加载；不改变 running identity；不得直接覆盖内置模板

**契约：** STAGE5-WRITEBACK-001…005  
**测试：** `config-tool/acceptance/stage_5/template_writeback_acceptance_test.go`  
**前端：** `writeback.acceptance.test.ts`

---

# 3. 阶段 6 — 趋势、事件与控制品质

## 3.1 `computeControlQuality(samples, options)`

输入：`QualitySample { t, pv, sv, mv }`、`QualityOptions`（errorBand、stableWindowSeconds=60、mv/level 上下限、events）  
输出：可观察 `steadyStateError`、`overshoot`、`settled`、`settlingTime`、`mvSaturationTime`、`levelHighHits`/`levelLowHits`、`invalidSampleCount`、`segments`/`archivedSegments`

数值语义：

- 连续 60s 在误差带内才 settled；59s 不算
- 不规则采样按时间积分
- 液位触碰按边沿计数
- NaN/Infinity → invalid，不得污染其余指标为 NaN
- 参数 applied 事件：归档当前 segment 并开启新 segment

**Fixture：** `tools/stage_verification/fixtures/quality/*.json`  
**契约：** STAGE6-QUALITY-*  
**测试：** `frontend/acceptance/stage_6/control_quality.acceptance.test.ts`

## 3.2 趋势与事件

- TrendBuffer 最大 1200、FIFO；heartbeat/stale 不追加；Stop 不清空；restart 归档 previousRun
- 左轴：tank_2.level、SV；右轴：MV、valve current_opening
- 显示 `pid2.PV ← tank_2.level`；曲线可开关
- 事件 pending/applied/failed；applied 时间用 snapshot 确认时刻

**契约：** STAGE6-TREND-* / STAGE6-EVENT-*  
**人工 gate（unsigned）：** `evidence/stage_6/trend_visual_review.md`

---

# 4. 阶段 7 — Batch / CSV / 下采样 / 互斥

## 4.1 公共 Binding（已有）

```go
func (b *SystemBinding) RunBatch(configPath string, cycles int) (BatchResult, error)
func (b *SystemBinding) ExportBatch(configPath string, cycles int, exportPath string) error
```

不得强制导出内部 `AllocateBatchWorkDir` / `CanRunBatch` 等为完成条件（并发与互斥用**外部行为**证明）。

## 4.2 行为契约

| ID | 内容 |
|----|------|
| STAGE7-BATCH-001 | 2000 周期成功、退出码 0 |
| STAGE7-BATCH-002 | Unicode YAML/CSV 路径 |
| STAGE7-BATCH-003～004～008 | 每任务唯一临时路径、并发不覆盖、清理 |
| STAGE7-BATCH-005～007 | 退出码/stderr 传播；空输出不得成功 |
| STAGE7-STATE-001～005 | dirty/校验阻止 batch；BATCH_RUNNING 阻实时；实时阻 batch；失败可恢复 |
| STAGE7-CSV-* | 表头、行数契约、时间单调、YAML/CSV 对话框分离 |
| STAGE7-DOWNSAMPLE-* | ≤3000、首尾、局部极值、顺序、小数据不改写 |

行数契约须在实现前固定为「恰好 2000」或「含初值 2001」之一。

**测试：** `acceptance/stage_7/*`  
**人工 gate（unsigned）：** `evidence/stage_7/single_page_batch_review.md`

---

# 5. 阶段 8 — 分层 E2E

阶段 8 **不是**单一测试文件，而是组合门禁：

| 层 | 权威测试 | 职责 |
|----|----------|------|
| Python | `test_end_to_end_acceptance.py` | DataFactory、REST/WS、/writes、Batch、OPC UA、端口/进程清理 |
| Go | `application_acceptance_test.go` | Binding 组合、Start/Stop、writeback、Batch 入口 |
| Frontend | `full_workflow.acceptance.test.tsx` | 打开/编辑/阻止、Faceplate、趋势、Batch UI |
| Manual | stage_8 evidence | 完整桌面操作与设计项逐条 PASS/FAIL/N/A |

场景步骤：`fixtures/e2e/stage_8_scenario.json`（STAGE8-E2E-001…029）

清理：随机端口、finally 停进程、端口释放、不污染内置 YAML、临时文件在 tmp。

**人工 gate（unsigned）：**  
`evidence/stage_8/complete_e2e_review.md`、`design_acceptance_review.md`

---

# 6. 人工 Gate 证据要求（摘要）

| Gate | 阶段 | 要求 |
|------|------|------|
| trend_visual_review | 6 | 双轴、previous run 次级样式、曲线开关、事件状态、PV 绑定、stale 冻结；unsigned |
| single_page_batch_review | 7 | 同页入口、进度/失败/导出、非空成功图、互斥、CSV 对话框；unsigned |
| complete_e2e_review | 8 | 录屏/截图、YAML hash、端口、runtimeName、写值前后 snapshot、趋势、Batch、CSV、OPC UA、清理证明；unsigned |
| design_acceptance_review | 8 | 逐项 PASS/FAIL/N/A + 证据，禁止总勾选；unsigned |

---

# 7. 契约编号 ↔ 测试文件映射

| 前缀 | 主要测试文件 |
|------|----------------|
| STAGE5-ATOMIC-* | `acceptance/stage_5/test_atomic_writes_acceptance.py`；前端 `runtime_writes.acceptance.test.ts` |
| STAGE5-MODE-* | `pid_faceplate.acceptance.test.tsx`；`test_pid_faceplate_acceptance.py` |
| STAGE5-WRITEBACK-* | `template_writeback_acceptance_test.go`；`writeback.acceptance.test.ts` |
| STAGE6-QUALITY-* | `control_quality.acceptance.test.ts`；`test_trend_quality_acceptance.py` |
| STAGE6-TREND-* / EVENT-* | `trend_*.acceptance.test.tsx` |
| STAGE7-* | `acceptance/stage_7/**` |
| STAGE8-E2E-* | `acceptance/stage_8/**` + scenario JSON |

公共表面登记见 `CONTRACT_SURFACES.md`。

---

# 8. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-07-21 | 提交 A：初版正式规范，替代未跟踪任务笔记作为验收依据 |
