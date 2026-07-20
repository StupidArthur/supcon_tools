# Acceptance Contract Surfaces

本文件登记**锁定验收**可精确引用的公共表面。  
未登记名称不得作为 acceptance 完成条件。

规则：

1. repository contracts 已规定的名称可直接登记。
2. implementation playbook 的“建议文件路径”**不**自动成为强制公共接口。
3. 新 acceptance seam 必须在此标明“验收 API”。
4. 内部 helper / manager / 私有文件名不得登记。

---

## STAGE5-ATOMIC — HTTP `/writes`

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-ATOMIC-001 … 015 |
| 阶段 | 5 |
| 公共表面 | Atomic online write HTTP API |
| 类型 | HTTP |
| 名称或路径 | `POST /api/instances/{runtimeName}/writes` |
| 输入 | JSON：`{"writes":[{"tag":string,"value":number}, ...]}`；路径参数 `runtimeName` 来自 `/api/status.instance_name` |
| 输出 | 接受时：`{ "ok": true, "batch_id": string, "status": "pending" }`（字段名可等价扩展，但必须可查询 pending/applied/failed）；拒绝时：HTTP 4xx + 指出失败字段 |
| 错误语义 | 整批验证失败 → 4xx，**零**部分入队；unknown/readonly/derived 字段拒绝；runtimeName 不匹配 → 404 |
| 依据文档章节 | `todo/7.md` §十二；playbook 阶段 5 `/writes` 契约 |
| 是否允许实现内部自由变化 | **是** — 不得锁定 `AtomicWriteBatch` / `WriteBatchManager` 等内部类型名 |

兼容表面（不得当作新原子接口）：

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-ATOMIC-014 |
| 公共表面 | Legacy param update |
| 类型 | HTTP |
| 名称或路径 | `POST /api/instances/{name}/params` |
| 说明 | 可继续存在；acceptance **不得**把 `/params` 当作原子写完成条件 |

---

## STAGE5-MODE — PidFaceplate

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-MODE-001 … 006 |
| 阶段 | 5 |
| 公共表面 | `PidFaceplate` React component |
| 类型 | React component |
| 名称或路径 | `config-tool/frontend/src/features/templates/secondOrderTank/PidFaceplate.tsx`（验收组件；实现可移动但必须保留同名导出或在此更新登记） |
| 输入（Props / Store） | 至少：`mode`（AUTO/MAN/CAS）、现场值 `PV/SV/CSV/MV/PB/TI/TD/KD/MODE/SWPN`、写状态 `pending\|applied\|failed\|idle`、`onSubmit(writes)` |
| 输出 | 可访问表单控件：`data-testid` 建议 `faceplate-sv` / `faceplate-mv` / `faceplate-csv` / `faceplate-pv` 等；提交触发 `onSubmit` |
| 错误语义 | 只读字段不可编辑；提交失败显示 failed 原因 |
| 依据文档章节 | `todo/7.md` §十二 Faceplate |
| 是否允许实现内部自由变化 | **是** — 不得要求 `FACEPLATE_MODE_POLICY` 等内部常量名 |

---

## STAGE5-ATOMIC (frontend) — submitAtomicWrites

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-ATOMIC-001 … 013（前端侧） |
| 阶段 | 5 |
| 公共表面 | `submitAtomicWrites` |
| 类型 | TypeScript module |
| 名称或路径 | `config-tool/frontend/src/features/runtime/runtimeWrites.ts` → `submitAtomicWrites` |
| 输入 | `{ apiHost, apiPort, runtimeName, writes: {tag,value}[], signal? }` |
| 输出 | `{ batchId: string, status: "pending" }`；后续由 snapshot 观察升为 applied / 超时 failed |
| 错误语义 | 客户端预校验失败不发 fetch；HTTP 4xx 抛错且不标记 applied |
| 依据文档章节 | `todo/7.md` §十二 |
| 是否允许实现内部自由变化 | **是** |

---

## STAGE5-WRITEBACK — ApplyRuntimeOverrides

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE5-WRITEBACK-001 … 005 |
| 阶段 | 5 |
| 公共表面 | `TemplateConfigBinding.ApplyRuntimeOverrides` |
| 类型 | Go Binding |
| 名称或路径 | `config-tool/internal/bindings` → `(*TemplateConfigBinding).ApplyRuntimeOverrides` |
| 输入 | 结构化请求：目标 YAML 路径、expected hash、runtime override 字段集、写回勾选白名单 |
| 输出 | 保存结果（新 hash / 路径）；校验失败不写盘 |
| 错误语义 | 禁止 PV、实时液位、实时阀位；MV 默认不写回；校验失败 → error 且文件不变 |
| 依据文档章节 | `todo/7.md` §十二 写回 DSL |
| 是否允许实现内部自由变化 | **是** — **不得**要求特定 `writeback.go` 文件名或源码字符串扫描 |

前端对应行为通过 Template Store / 写回 UI 验证，不锁定内部 reducer 名。

---

## STAGE6-QUALITY — computeControlQuality

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE6-QUALITY-001 … 006 |
| 阶段 | 6 |
| 公共表面 | `computeControlQuality` |
| 类型 | TypeScript module |
| 名称或路径 | `config-tool/frontend/src/features/runtime/controlQuality.ts` → `computeControlQuality` |
| 输入 | 时间序列 samples：`{ t: number, pv: number\|null, sv: number\|null, mv: number\|null }[]` + 选项（误差带、液位上下限、参数事件时刻） |
| 输出 | 数值指标：稳态误差、超调、稳定时间（秒）、MV 饱和时间、高低限触碰次数、分段归档等；**禁止**用 NaN 作为成功指标 |
| 错误语义 | 非有限样本跳过/计入 invalid，不得污染其余指标为 NaN |
| 依据文档章节 | `todo/7.md` §十三 |
| 是否允许实现内部自由变化 | **是** — 不得仅检查常量/函数存在 |

Fixture 目录：`tools/stage_verification/fixtures/quality/*.json`

---

## STAGE6-TREND — RuntimeTrendPanel / events

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE6-TREND-* / STAGE6-EVENT-* |
| 阶段 | 6 |
| 公共表面 | `RuntimeTrendPanel`；趋势事件列表 UI/Store 可读状态 |
| 类型 | React component / Store 可观察状态 |
| 名称或路径 | `RuntimeTrendPanel` 组件；事件以 UI/`data-testid` 或公开 store 选择器暴露 |
| 输入 | series、previousRunSeries、events、stale |
| 输出 | 双轴图、曲线开关、PV 绑定说明、事件 pending/applied/failed 可见 |
| 依据文档章节 | `todo/7.md` §十三 |
| 是否允许实现内部自由变化 | **是** — 不得要求 `trendPolicy` / reducer 内部名，除非另行登记为公共纯函数 |

已有可复用公共表面：`TrendBuffer`（容量 1200、FIFO）— 阶段 4 已存在，阶段 6 可继续行为断言。

---

## STAGE7 — Batch / downsample / dialogs

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE7-BATCH-* / STAGE7-STATE-* / STAGE7-CSV-* / STAGE7-DOWNSAMPLE-* |
| 阶段 | 7 |
| 公共表面 | `SystemBinding.RunBatch` / `ExportBatch` / `AllocateBatchWorkDir` / `CanRunBatch`；前端 `BatchPanel`、`canStartBatch`/`canStartRealtime`；`downsample`；`batchExportDialogOptions` |
| 类型 | Go Binding / React / TypeScript |
| 依据 | `todo/7.md` §十四 |
| 是否允许实现内部自由变化 | **是** |

## STAGE8 — E2E scenario

| 字段 | 内容 |
|------|------|
| 契约 ID | STAGE8-E2E-001 … 029 |
| 阶段 | 8 |
| 公共表面 | `tools/stage_verification/fixtures/e2e/stage_8_scenario.json` + 既有 HTTP/Binding/UI 公共表面组合 |
| 类型 | JSON scenario + 外部进程效果 |
| 依据 | `todo/7.md` §十五 |
| 是否允许实现内部自由变化 | **是** |

---

## 变更记录

| 日期 | 说明 |
|------|------|
| 2026-07-20 | 批次 5.1 初版：登记 stage 5～6 公共表面，剔除内部 helper 锁定 |
| 2026-07-20 | 批次 6：登记 stage 7～8 Batch/E2E 公共表面 |
