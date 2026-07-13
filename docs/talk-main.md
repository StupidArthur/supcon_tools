# talk-main.md - 主 Agent 验收后派单(子 Agent 修,主 Agent 验收+commit)

> 通宵 419 挂接已验收 **ACCEPTED_WITH_GAPS**,主 Agent 已 commit(`1c11987`)。本派单把审核问题 + 两个已定决策交给子 Agent。**你不得 commit(主 Agent 把控);改完回报,主 Agent 验收后 commit。**

## 0. 纪律(先读)
- **不许 commit。** 改完 -> 自验 -> 回报 -> 主 Agent 验收+commit。你若 commit 会被 revert。
- 不改 doc markdown;不放宽断言/阈值/步骤;不加 try/except 吞错(除 `cleanup_case_tag`);不改产品语义。
- **OBSERVED 改真实断言后,产品不符 doc -> 保留 FAIL,不许退回 OBSERVED 混过。** FAIL 是有效产出。
- 复用现有架构(共享 baseline、`ua2_ops`、`query_tags_with_quality groupId=0`);env.json 凭据;不碰子模块/output/密码。

## 1. 已定决策(主 Agent + 用户)
- **决策一(保留 `ua3_runtime`)**:UA-3 继续走 `ua3_runtime` 章节 dispatcher(与 UA-1/UA-2 一致)。`scenario_runtime` + `_SHARED_SCENARIOS` + `_ua3_scenario_for` 现为死代码,需清理(见任务 F)。
- **决策二(inventory 加 `PARTIAL`)**:`IMPLEMENTED` 收紧为"严格"(有真实 doc 断言、满足 case-first-plan 8 条);新增 `PARTIAL`(已派发但仅 OBSERVED/夹具简化,无完整断言);`UNIMPLEMENTED`(无派发)。让 `implemented` 不再虚高(见任务 G)。

## 2. 任务(按优先级,分批做,每批回报)

### 任务 G(先做):inventory 加 PARTIAL 状态,建立诚实基线
**目标**:让 `case_inventory` 区分 `IMPLEMENTED`(严格)/`PARTIAL`(派发但无完整断言)/`UNIMPLEMENTED`(无派发)。
**做法**:
- 新增 `ua_test_harness/case_fidelity.py`,维护两个集合:`STRICT_IMPLEMENTED: set[str]`(有真实 doc 断言的)和 `OBSERVED_ONLY: set[str]`(派发但 OBSERVED 回退/夹具简化,无完整断言)。
- 初始填充:把现有高保真 case(UA-2 第一批 16、UA-2-1/2/4 核心有 `check_*` 断言的)放 `STRICT_IMPLEMENTED`;~120 探索 + 简化回归放 `OBSERVED_ONLY`。逐模块扫一遍 handler 是否调 `check_eq`/`check_true` 等(可静态 grep 辅助,但以你审 handler 为准)。
- 改 `case_inventory.py`:`implementationStatus` = `IMPLEMENTED`(有派发且在 STRICT) / `PARTIAL`(有派发但不在 STRICT,或在 OBSERVED_ONLY)/ `UNIMPLEMENTED`(无派发)。`summary` 加 `partial` 计数;`coveragePercent` 改为 strict/documented。
- **不改** doc;不破坏现有 inventory strict-structure 检查(documented=419、malformedRows=0 等)。
- 验收:`python -m ua_test_harness.case_inventory --repo-root . --expected-total 419 --strict-structure --output ...` 仍 structureOk;输出含 IMPLEMENTED/PARTIAL/UNIMPLEMENTED 三计数。
- 回报:STRICT/PARTIAL/UNIMPLEMENTED 各多少,列出 PARTIAL 的 case ID(或按章汇总)。

### 任务 A:回归类 OBSERVED -> 真实 doc 断言(移 PARTIAL->IMPLEMENTED)
**目标**:doc 有明确断言的回归 case,实现真实 `check_*` 断言,删 OBSERVED 回退。改一条就从 `OBSERVED_ONLY` 移到 `STRICT_IMPLEMENTED`。
**第一批(高保真价值)**:UA-2-2 余量(003/006/007/009/010/012/014/017/018/020~032 除 053)+ UA-2-1 余量回归类。逐条读 `ua_test_gui/doc/test_cases/UA-2-*.md` 断言列 -> handler 实现 `check_*` -> 单测(mock 验证断言触发)。
**边界**:doc 无硬断言的探索类(UA-3-5/6 等)保留 OBSERVED + 留在 `OBSERVED_ONLY`;产品不符 -> FAIL 保留。

### 任务 F:清理 UA-3 死代码(决策一)
- 删除/下沉 `scenario_runtime.py` 中不再被调用的路由(`execute_documented_case` 的共享场景分发)。
- 删除 `scenario_policy.py` 的 `_SHARED_SCENARIOS`(line 57-68)、`_ua3_scenario_for`(line 71-90)-- UA-3 已走 `ua3_runtime`,这些不再用。
- **先检查** `scenario_runtime` 里是否有值得复用的 helper(rt_read/rt_write/history 等场景函数);有则迁进 `ua3_precise` 并更新引用,再删 `scenario_runtime`。
- 不破坏 UA-3 现有 dispatch;`_execute_shared` 兜底若不再需要一并清理。
- 验收:compileall + 全量 pytest;grep 确认 `scenario_runtime`/`_SHARED_SCENARIOS` 无残留引用(或已删)。

### 任务 C:UA-3 七条 legacy 双轨合并
- `tests/ua_3/test_collection.py`(6)+ `test_13_types.py`(1)与 `ua3_runtime` 双轨。迁进 `ua3_runtime`/`ua3_precise` 单一调度,或下线 legacy(保留行为)。不破坏现有 7 条真实 API 调用。

### 任务 B:规模/时长简化还原或登记
- 逐条查审计 §C(UA-2-3-032 100->min(100,20)、UA-3-6-015 30min->50 等)。能还原 doc 规模的还原;不能的在 `docs/overnight-findings.md` 明确登记"规模缩减+理由",不静默缩减。

### 任务 D:`docs/overnight-report.md` UA-3 路由描述过时修正(已走 ua3_runtime)。

### 任务 E(可选,env 可用时):VERIFIED 真跑
- 高保真章改完后用 `scripts/run_automation_ua2.ps1` 或分章 CLI 真跑,更新 `verificationStatus`。产品 FAIL 保留。

## 3. 工作流
1. 先做任务 G(建立 PARTIAL 基线)。
2. 再任务 A 第一批(移 PARTIAL->IMPLEMENTED)。
3. 任务 F/C/B/D 跟进(可并行无依赖的)。
4. 每批:自验(compileall + 该批单测 + 全量 pytest 不破 + catalog/inventory structureOk)-> **不 commit** -> 回报。
5. 主 Agent 验收 + commit;通过后下一批。

## 4. 回报格式
```
**任务**: <任务字母+批次>
**状态**: success|partial|blocked
**修改文件**: ...
**关键变更**: (如 PARTIAL/IMPLEMENTED 计数变化、OBSERVED->断言 清单、删除的死代码)
**新增 FAIL(产品问题)**: case ID + 现象(保留 FAIL)
**单测结果**: compileall + pytest 摘要
**catalog/inventory**: documented/IMPLEMENTED/PARTIAL/UNIMPLEMENTED/structureOk
**git status --short**: 输出(未 commit)
**差异/风险**: 无则"无"
```

---
**一句话**: 决策已定(保留 ua3_runtime + 清死代码;inventory 加 PARTIAL)。先做任务 G 建立 PARTIAL 基线,再任务 A 把回归类 OBSERVED 改真实断言(FAIL 保留),F/C/B/D 跟进。**不许 commit,改完回报我验收。**
