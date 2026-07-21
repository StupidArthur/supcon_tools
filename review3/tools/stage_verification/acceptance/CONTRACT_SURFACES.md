# Acceptance Contract Surfaces

本文件登记**锁定验收**可精确引用的公共表面。  
未登记名称不得作为 acceptance 完成条件。

**正式契约依据：**

- `tools/stage_verification/acceptance/SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md`
- `todo/second_order_tank_repository_contracts.md`
- `todo/second_order_tank_implementation_playbook.md`

规则：

1. repository contracts 已规定的名称可直接登记。
2. implementation playbook 的“建议文件路径”**不**自动成为强制公共接口。
3. 新 acceptance seam 必须在此标明“验收 API”。
4. 内部 helper / manager / 私有文件名不得登记。
5. **不得**引用未跟踪的本地任务提示笔记作为契约依据。

---

## STAGE5-ATOMIC — HTTP `/writes`

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-ATOMIC-001 … 015 |
| 阶段 | 5 |
| 公共表面 | Atomic online write HTTP API |
| 类型 | HTTP |
| 名称或路径 | `POST /api/instances/{runtimeName}/writes`；`GET /api/instances/{runtimeName}/writes/{batchId}` |
| 输入 | JSON：`{"writes":[{"tag":string,"value":number},...],"confirm_timeout_s"?:number}`；`runtimeName` 来自 `/api/status.instance_name` |
| 输出 | 接受：`ok`、`batch_id`、`status:"pending"`；查询：`pending\|applied\|failed` + writes；拒绝：HTTP 4xx、无成功 batch_id |
| 错误语义 | 整批验证失败 → 4xx，零部分入队；unknown/readonly/derived 拒绝；runtimeName 不匹配 → 404 |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §2.1；repository contracts / playbook 阶段 5 |
| 是否允许实现内部自由变化 | **是** |

兼容表面：

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-ATOMIC-014 |
| 公共表面 | Legacy param update |
| 类型 | HTTP |
| 名称或路径 | `POST /api/instances/{name}/params` |
| 说明 | 可继续存在；**不得**当作原子写完成条件 |

---

## STAGE5-MODE — PidFaceplate

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-MODE-001 … 006 |
| 阶段 | 5 |
| 公共表面 | `PidFaceplate` |
| 类型 | React component |
| 名称或路径 | 导出 `PidFaceplate`（建议路径 `features/templates/secondOrderTank/PidFaceplate.tsx`，可移动但须保留同名导出或更新本表） |
| 输入 | 正式 Props：见 `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §2.2；须覆盖字段 **PV / SV / CSV / MV / PB / TI / TD / KD / MODE / SWPN**；模式 AUTO / MAN / CAS |
| 输出 | 可访问控件（建议 testid：`faceplate-sv` / `faceplate-mv` / `faceplate-csv` / `faceplate-pv` / `faceplate-write-status` 等）；writeStatus：`pending` / `applied` / `failed` |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §2.2 |
| 是否允许实现内部自由变化 | **是** — 不得要求内部常量名 |

---

## STAGE5-ATOMIC (frontend) — submitAtomicWrites

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-ATOMIC-*（前端侧） |
| 阶段 | 5 |
| 公共表面 | `submitAtomicWrites` |
| 类型 | TypeScript module |
| 名称或路径 | `features/runtime/runtimeWrites.ts` → `submitAtomicWrites`（可移动，须保留导出名或更新本表） |
| 输入 / 输出 | 见 `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §2.3 |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §2.3 |
| 是否允许实现内部自由变化 | **是** |

---

## STAGE5-WRITEBACK — ApplyRuntimeOverrides

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-WRITEBACK-001 … 005 |
| 阶段 | 5 |
| 公共表面 | `TemplateConfigBinding.ApplyRuntimeOverrides` |
| 类型 | Go Binding |
| 名称或路径 | `(*TemplateConfigBinding).ApplyRuntimeOverrides(ApplyRuntimeOverridesRequest) (ApplyRuntimeOverridesResult, error)` |
| 输入 / 输出 DTO | 见 `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §2.4（字段名正式锁定） |
| 错误语义 | 禁止 PV/实时位；`IncludeMV=false` 且 Overrides 含 MV → **整批拒绝、文件不变**；ExpectedHash 冲突；校验失败不写盘；禁直接覆盖内置模板；成功时 AppliedFields 非空 |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §2.4 |
| 是否允许实现内部自由变化 | **是** — 不得要求特定 `.go` 文件名 |

---

## STAGE6-QUALITY — computeControlQuality

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE6-QUALITY-* |
| 阶段 | 6 |
| 公共表面 | `computeControlQuality` |
| 类型 | TypeScript module |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §3.1 |
| Fixture | `tools/stage_verification/fixtures/quality/*.json` |
| 是否允许实现内部自由变化 | **是** |

---

## STAGE6-TREND — RuntimeTrendPanel / TrendBuffer

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE6-TREND-* / STAGE6-EVENT-* |
| 阶段 | 6 |
| 公共表面 | `RuntimeTrendPanel`；`TrendBuffer`（已有） |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §3.2 |
| 是否允许实现内部自由变化 | **是** |

---

## STAGE7 — Batch / downsample

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE7-* |
| 阶段 | 7 |
| 公共表面 | `SystemBinding.RunBatch` / `ExportBatch`；`downsample`；Batch UI / 状态纯函数（若导出） |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §4 |
| 说明 | 并发/临时文件/互斥以**外部行为**验收，不强制内部分配器方法名 |
| 是否允许实现内部自由变化 | **是** |

---

## STAGE8 — 分层 E2E

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE8-E2E-001 … 029 |
| 阶段 | 8 |
| 公共表面 | `fixtures/e2e/stage_8_scenario.json` + 阶段 0～7 已登记公共表面组合 |
| 依据文档章节 | `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md` §5 |
| 是否允许实现内部自由变化 | **是** |

---

## 变更记录

| 日期 | 说明 |
|------|------|
| 2026-07-20 | 批次 5.1 / 6 初版登记 |
| 2026-07-21 | 提交 A：去除未跟踪任务笔记引用；依据改为 `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md`；固化 Go DTO 与 `/writes` 查询表面 |
| 2026-07-21 | 提交 A.1：`IncludeMV=false`+MV 整批拒绝；成功 AppliedFields 非空 |
