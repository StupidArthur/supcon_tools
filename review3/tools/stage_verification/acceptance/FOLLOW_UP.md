# Acceptance Follow-up（非阻塞）

本文件记录**非致命**改进项。不得因此暂停验收基础设施收口或新增子批次。

正式契约真源仍为：

- `SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md`
- `CONTRACT_SURFACES.md`
- `manifest.schema.json`
- `README.md`

## 非阻塞事项

1. Stage 7 `RunBatch` 共享 `_batch_export.csv`：已由外部并发验收暴露；待业务修复后同一测试应变绿。
2. Stage 7 `Status.Running=true` 时 `RunBatch`/`ExportBatch` 未互斥：已由 STAGE7-STATE-004 暴露。
3. Stage 7 `RunBatch` 对空 CSV 仍可能返回成功空结果：STAGE7-BATCH-007。
4. Stage 5 `/writes`、`ApplyRuntimeOverrides`、PidFaceplate 等业务能力尚未实现：prospective baseline 允许，不得 finalize。
5. Stage 2 Space 键选择：见 `ACCEPTANCE_BLOCKED.md`；修复前不得 retrospective finalize。
6. CSV `expected_columns.json` 与 `standalone_main` 当前导出列（排除 `sim_time`/`cycle_count`）可能不一致：保持正式表头契约，业务对齐后变绿。
7. Accepted checkpoint schema 未单独字段化 `BUSINESS_BLOCKED` 列表：现状用 `ACCEPTANCE_BLOCKED.md` + baseline mode 表达。
8. Stage 8 OPC UA 外部写值的全自动 live harness 仍依赖人工 gate 补证。
9. Manifest `required_paths` 中部分历史业务路径名可能与最终落点不同：以 reviewer acceptance 与 CONTRACT_SURFACES 为准。
10. README 中“阶段 5–8 reviewer suite 现在故意不存在”的旧表述可在文档润色时更新（不阻塞）。
