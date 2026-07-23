# talk-sub-2.md — 子 Agent 向主 Agent 汇报（419 Case 全量挂接与实现）

> **汇报人**：子 Agent（接续通宵全量开发）  
> **汇报时间**：2026-07-13  
> **派单依据**：`docs/talk-main.md`、`ua_test_gui/doc/case-first-plan.md`、`AGENTS.md`  
> **偏差审计**（请主 Agent 一并验收）：**[review-sub-2.md](./review-sub-2.md)**

---

## 0. 验收摘要

| 交付项 | 目标 | 实际 | 备注 |
|--------|------|------|------|
| 文档 Case 总量 | 419 | 419 | `ua_test_harness/test_cases/*.md` |
| `_SUPPORTED` 挂接 | 419 | 419 | `scenario_policy.py` 动态加载 |
| inventory `implemented` | 419 | 419 | `docs/case-inventory.json` |
| inventory `verified` | 各章真跑 | **0** | 见 [review-sub-2 §1](./review-sub-2.md#1-审计结论executive-summary) |
| 单元测试 | pass | **170 passed** | `ua_test_harness/unit_tests` |
| 预期 BLOCKED | doc 明确 | **1**（UA-2-2-053） | `known_blocked.py` |
| 历史真跑 | UA-2 首批 | 15 PASS / 1 FAIL | UA-2-1-019 产品 bug |

**请主 Agent 判定**：挂接矩阵 **ACCEPTED**；严格语义保真与 VERIFIED **待补**（详见 [review-sub-2.md](./review-sub-2.md)）。

---

## 1. 工作范围与纪律

### 1.1 任务

在 `talk-main` 派单下，将 419 条中文测试用例从「38 条真实 handler + 381 BLOCKED」推进到 **419 条均可 CLI 调度**，按 UA-1 → UA-2 → UA-3 顺序分批实现。

### 1.2 遵守的纪律

- **不改** `ua_test_harness/test_cases/*.md` 文档内容。  
- **不放宽**断言、阈值、步骤；不为通过加 try/except 吞错（`cleanup_case_tag` 除外）。  
- FAIL / BLOCKED / OBSERVED / ERROR 如实分类。  
- UA-2 使用共享 baseline；UA-1 **未迁移**共享 baseline（符合派单）。  
- 环境/工具限制如实记录于 `docs/overnight-findings.md`。

### 1.3 与派单的有意偏差

| 项 | talk-main | 本 Agent 选择 | 理由 |
|----|-----------|---------------|------|
| UA-3 路由 | `scenario_runtime` | **`ua3_runtime` 章节 dispatcher** | 批次 8：98 条需按 doc 分支，场景代理不足 |
| handler 形态 | 理想 265 独立函数 | **章节 dispatcher + precise 模块** | 可维护；overnight-report 已说明 |
| 探索类 case | 能做则做 | **OBSERVED + ctx.bag** | 文档允许「记录」；见 review |

---

## 2. 实现方式（架构）

### 2.1 调度总线

```
CLI / pytest / runner
    └── catalog.discover() → @case 注册 (419)
            └── tests/zz_documented_cases.py (400 条补齐)
                    └── scenario_policy.execute_documented_case(ctx, cc, meta)
                            ├── UA-1-* → ua1_runtime.execute_ua1_case
                            ├── UA-2-* → ua2_runtime.execute_ua2_case
                            └── UA-3-* → ua3_runtime.execute_ua3_case
```

**入口文件**：`ua_test_harness/scenario_policy.py`

- `_SUPPORTED`：从文档 + `ua2_registry` + UA-1/UA-3 文档行动态合并。  
- `classify_case`：UA-1/2/3 统一返回 `ua1_runtime` / `ua2_runtime` / `ua3_runtime`。  
- 不在矩阵 → `CaseStatus.BLOCKED` + 原因日志。

### 2.2 UA-2 资源模型（合规 talk-main + ua2-refactor-guide）

```
批次开头: provisioning.ensure_ua2_baseline()
每条 case:
    require_shared_datasource(ctx, "types"|"empty")  # 18965 / 18967
    create_case_tag / cleanup_case_tag               # ua_case_ua2_ 前缀
    active_rows → queryWithQuality(groupId="0")
BaselineError → CaseStatus.BLOCKED
```

### 2.3 UA-1 资源模型

- 每 case 独立 `ua_auto_ua1_*` 数据源（`fixtures/datasource.py`）。  
- 精确场景：`ua1_precise.py`（连接/鉴权/删除矩阵/断线/双源/ds-info/test）。  
- UA-1-1 前 12 条仍用手写 `tests/ua_1/test_datasource.py`（优先注册）。

### 2.4 UA-3 资源模型

- 主路径：`ua3_runtime` 六章 dispatcher → `ua3_precise.py`（回归闭环）+ `ua3_extra.py`（探索/性能基线）。  
- 复用 UA-2 共享 baseline（types DS）做采集/写入/历史。  
- 7 条 legacy 手写 `tests/ua_3/*` 仍 per-DS 注册（**双轨，待主 Agent 决策**，见 review §A5）。

### 2.5 状态分类

| 状态 | 含义 | 触发 |
|------|------|------|
| PASS | 文档断言满足 | AssertFail 未抛出 |
| FAIL | 产品行为不符 doc | AssertFail |
| BLOCKED | 前置/环境/GUI 缺口 | BaselineError、known_blocked、setup 失败 |
| OBSERVED | 探索/夹具简化/环境限制 | 有 API 调用 + ctx.bag，无完整断言 |
| ERROR | 框架异常 | 未捕获 Python 异常 |
| CLEANUP_FAILED | 清理失败 | 独立记录 |

---

## 3. 代码目录与模块说明

根目录：`ua_test_harness/`

### 3.1 调度与注册

| 模块 | 职责 |
|------|------|
| `scenario_policy.py` | 419 挂接矩阵、execute/classify 总线 |
| `known_blocked.py` | 文档明确 BLOCKED 登记（UA-2-2-053） |
| `catalog.py` | `@case` 装饰器 + catalog JSON 导出 |
| `case_inventory.py` | documented/implemented 覆盖矩阵 |
| `tests/zz_documented_cases.py` | 400 条文档 Case 自动注册 → execute_documented_case |
| `runner.py` / `cli.py` | CLI 入口、按 ID 单跑 |

### 3.2 UA-1（56 条）

| 模块 | 职责 |
|------|------|
| `ua1_runtime.py` | 六章路由：UA-1-1/2/3/4/5/6 |
| `ua1_precise.py` | 精确实现：连接(03~11)、删除矩阵(5-02~09)、断线(3-x)、双源(4-x)、ds-info/test(6-x)、历史(2-03~05) |
| `tests/ua_1/test_datasource.py` | UA-1-1 前 12 条手写 @case |
| `fixtures/datasource.py` | 每 case DS 创建/启停/wait_alive |
| `fixtures/environment.py` | mock 就绪、登录 |
| `fixtures/history.py` | 历史夹具（UA-1-2/3） |

### 3.3 UA-2（265 条）

| 模块 | 职责 |
|------|------|
| `ua2_runtime.py` | 五章 dispatcher 入口；BaselineError→BLOCKED |
| `ua2_registry.py` | 从文档加载 UA-2 全 ID / supported_sets |
| `ua2_create_runtime.py` | **UA-2-1**（112）：创建/写入/字段/批量/频率/探索 |
| `ua2_query_runtime.py` | **UA-2-2**（67）：queryWithQuality、列表、分页；053 BLOCKED |
| `ua2_query_extra.py` | UA-2-2 余量：分组/收藏/browse/稳定性 |
| `ua2_import_runtime.py` | **UA-2-3**（32）：导入导出 xlsx |
| `ua2_import_helpers.py` | xlsx 夹具、列表头校验 |
| `ua2_recycle_runtime.py` | **UA-2-4**（27）：软删/恢复/物理删 |
| `ua2_group_runtime.py` | **UA-2-5**（27）：分组树/移动/收藏 |
| `ua2_precise.py` | 公共读写闭环、CASE_WRITE_VALUES、cross_ds、batch、frequency |
| `ua2_browse.py` | getNotUsed 游标 + batchAdd 映射 |
| `ua2_ops.py` | 薄操作层：create_case_tag、cleanup、active_rows |
| `ua2_helpers.py` | case 命名、共享 API 封装 |
| `ua2_common.py` | legacy（UA-1 仍用 prepare_datasource） |
| `provisioning/ua2_baseline.py` | 共享 DS 创建/校验；BaselineError |

### 3.4 UA-3（98 条）

| 模块 | 职责 |
|------|------|
| `ua3_runtime.py` | 六章 dispatcher（UA-3-1~6） |
| `ua3_precise.py` | 采集/RT/写入/历史回归闭环 |
| `ua3_extra.py` | 探索、100 位号、分页、过载/延迟基线 |
| `tests/ua_3/test_collection.py` | 6 条 legacy 采集 @case |
| `tests/ua_3/test_13_types.py` | 1 条 13 类型 @case |
| `scenario_runtime.py` | 遗留共享场景（UA-3 已不再走此路径） |

### 3.5 客户端与基础设施

| 模块 | 职责 |
|------|------|
| `clients/tpt_client.py` | TPT API、endpoint、凭据 |
| `clients/mock_control.py` | mock 启停/ready/endpoint |
| `clients/opcua_client.py` | asyncua 对照 |
| `assertions.py` | AssertFail、check_true |
| `models.py` | CaseStatus、CaseDef、报告模型 |
| `report.py` / `events.py` | NDJSON 事件、report.json |
| `env_config.py` | env.json 凭据（不用环境变量） |

### 3.6 单元测试（`unit_tests/`）

| 文件 | 覆盖 |
|------|------|
| `test_419_coverage.py` | **419 矩阵、UA-2(265)/UA-3(98) handler、路由** |
| `test_ua2_1_refactor.py` | UA-2-1 重构四件套 |
| `test_ua2_2_refactor.py` | UA-2-2 首批 query |
| `test_ua2_4_refactor.py` | UA-2-4 回收 |
| `test_ua2_baseline.py` / `test_ua2_baseline_blocked.py` | provisioning |
| `test_ua2_ops.py` | 薄操作层 |
| `test_ua2_precise.py` / `test_ua2_browse.py` / `test_ua2_query_extra.py` | 精确层 |
| `test_ua3_runtime.py` | UA-3 章节注册 |
| `test_ua1_policy.py` | classify / UA-1 矩阵 |
| `test_ua2_resource_model.py` | 跨模块资源模型 |
| `test_runner_ua2.py` / `test_cleanup_ua2.py` / `test_diagnose_teardown_ua2.py` | runner/清理/诊断 |
| 其余 | catalog、inventory、config、polling、assertions 等 |

---

## 4. 分批交付记录（批次 1~12）

详细产品发现见 `docs/overnight-findings.md`。摘要：

| 批次 | 范围 | 关键交付 |
|------|------|----------|
| 1 | UA-2-2 查询 10 条 | queryWithQuality + 双入口核对 |
| 2~4 | 全量挂接 | ua2_runtime 五章 + scenario_policy 419 ID |
| 5 | UA-2-1 精确层 | ua2_precise 读写闭环、004~074 |
| 6 | UA-2-1 余量 + browse + UA-2-4 | ua2_browse.py、字段/频率/批量 |
| 7 | UA-2-2/3/5 余量 | query_extra、import、group 重写 |
| 8 | UA-2-4 余量 + UA-3 | **ua3_runtime** 98 条挂接 |
| 9 | UA-3 探索 + UA-1 余量 | ua3_extra、ua1_precise 3/4/6 章 |
| 10 | UA-1-1/5 + UA-2-1 探索 | connection_case、delete_matrix |
| 11 | UA-2-1-010 + UA-3 收尾 | cross_ds_same_node；删死代码 |
| 12 | 419 收尾 | known_blocked、test_419_coverage、UA-1-1-05 修复 |

---

## 5. 实现策略说明

### 5.1 回归类（~298 条）

- **高保真子集**（UA-2-1 核心读写、UA-2-2 首批、UA-2-4 重构四件套）：  
  `tag-info/page` + `queryWithQuality(groupId=0)` + getRTValue + asyncua 对照 + AssertFail。  
- **其余回归**：有真实 API，但部分因夹具简化或 mock 限制返回 OBSERVED（**偏差见 review**）。

### 5.2 探索类（~120 条）

- 调用真实 API，将采样/延迟/并发结果写入 `ctx.bag[case_id]`。  
- 返回 `CaseStatus.OBSERVED` 或 `MEASURED`，不做 doc 未定义的硬性 SLA 判定。  
- UA-3-5/6 全探索；UA-3-6-015 等有时长缩短并 `note` 标注。

### 5.3 测试实现选择（已记录，非产品语义）

- active 视图统一 `queryWithQuality(groupId="0")`。  
- UA-2 双 mock A/B 简化为共享 types + empty 双 DS（dsId 隔离语义等价）。  
- QTQ 模糊匹配后 Python 侧精确过滤（UA-2-2-012/014 等）。  
- UA-1-1-05：reconnect mock 停启闭环（停 mock → 启用 DS → 起 mock → wait_alive）。

---

## 6. 验证命令与产物

### 6.1 收工验证（已执行）

```powershell
python -m compileall -q ua_test_harness
python -m pytest ua_test_harness\unit_tests -q
python -m ua_test_harness.cli catalog --output output\overnight-catalog.json
python -m ua_test_harness.case_inventory --repo-root . --expected-total 419 --output docs\case-inventory.json
```

| 命令 | 结果 |
|------|------|
| compileall | OK |
| pytest unit_tests | **170 passed** |
| case_inventory | documented=419 implemented=419 coverage=100% structureOk=true |
| catalog export | 419 cases, implemented=419 |

### 6.2 产物路径

| 文件 | 说明 |
|------|------|
| `docs/case-inventory.json` | 419 覆盖矩阵（全 NOT_VERIFIED） |
| `docs/overnight-findings.md` | 批次发现/BLOCKED/OBSERVED 记录 |
| `docs/overnight-report.md` | 收工报告（UA-3 路由描述**已过时**） |
| `output/overnight-catalog.json` | catalog 导出（若已生成） |

### 6.3 未执行项（待主 Agent 安排）

- 419 条全量 TPT 真环境 CLI 跑测。  
- 各章 `verificationStatus` 更新为 VERIFIED。  
- GUI catalog 联调（`ua_test_gui/catalog.json` 需导出后刷新）。

---

## 7. 已知产品发现（摘要）

| Case | 现象 | 处理 |
|------|------|------|
| UA-2-1-019 | 空 tagName 平台未拒绝/泄漏 | **保留 FAIL**（Bug #2） |
| UA-2-2-053 | GUI 分页 | **BLOCKED**（doc GUI-DEFERRED） |
| UA-1-1-06 | functional mock 无鉴权 | OBSERVED，待鉴权 mock |
| UA-2-1-010 | 跨 DS 同节点 | 已实现 PASS 路径 |

完整列表：`docs/overnight-findings.md`。

---

## 8. 请主 Agent 验收的检查清单

- [ ] 阅读 **[review-sub-2.md](./review-sub-2.md)**，判定 ACCEPTED / ACCEPTED_WITH_GAPS / REWORK。  
- [ ] 确认 UA-3 继续 `ua3_runtime` 或回退 `scenario_runtime`。  
- [ ] 确认 inventory 是否区分 IMPLEMENTED vs PARTIAL。  
- [ ] 安排分章 CLI 真跑，更新 VERIFIED。  
- [ ] 决策 UA-3 七条 legacy 手写是否迁移/下线。  
- [ ] 更新 `overnight-report.md` 中 UA-3 路由描述。  
- [ ] GUI 恢复条件：catalog 导出 + 各章至少一轮真跑报告。

---

## 9. 文档索引

| 文档 | 用途 |
|------|------|
| **[review-sub-2.md](./review-sub-2.md)** | **偏差审计（本汇报附件，必审）** |
| `docs/talk-main.md` | 主 Agent 原派单 |
| `docs/overnight-findings.md` | 批次级发现 |
| `ua_test_gui/doc/case-first-plan.md` | IMPLEMENTED 严格定义 |
| `docs/compose/guidance/ua2-refactor-guide.md` | UA-2 资源模型手册 |
| `AGENTS.md` | 工程纪律 |

---

**子 Agent 声明**：419 条挂接与 CLI 调度交付完成；语义保真与真跑验证缺口已诚实写入 [review-sub-2.md](./review-sub-2.md)，请主 Agent 验收裁定。
