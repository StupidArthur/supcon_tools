# talk-main.md - 通宵全量开发派单(主 Agent 一次性派发,子 Agent 自主执行)

> 用户已睡(12 点+)。本派单让子 Agent 自主通宵推进 419 全量开发,按验收准则**自我初步验证**,逐批 commit,早晨出报告。主 Agent 不逐批门控。**关键:自主决策边界必须严格遵守(见下),不能问用户时按规则处理。**

---

## 0. 现状(必读)
- UA-2 第一批 16 条已完成+真实验证:`automation_ua2_20260712_235003` = **15 PASS / 1 FAIL**(UA-2-1-019 空名产品 bug,保留 FAIL)。
- 真实实现 **38/419**:UA-1 12、UA-2 16、UA-3 10。余 **381 条**已注册但 BLOCKED。
- 架构已就绪:共享 baseline(`ua_shared_ua2_types_ds` 18965 / `ua_shared_ua2_empty_ds` 18967)、`ua2_ops` 薄操作层、`provisioning`、`BaselineError->BLOCKED` 接线、env.json 凭据、cleanup 只清 `ua_case_ua2_`。
- Bug #1(`9e826e6` QTQ 切换)已验证;Bug #2(空名产品 bug)保留 FAIL;019 泄漏已修;alive-wait 120s 已修(`e7ada0e`)。

## 1. 必读文件(先读,别凭猜)
- `docs/compose/guidance/ua2-refactor-guide.md` - 架构、资源模型、状态分类、各任务模式。
- `.mimocode/plans/1783855834448-mighty-nebula.md` Part 4 - 路线图、验收标准、每批工作流。
- `ua_test_harness/scenario_policy.py` - `_SUPPORTED`/`_SHARED_SCENARIOS`/`_BLOCK_REASONS`(各章待补适配器清单=路线图)。
- `ua_test_gui/doc/test_cases/*.md` - 各 case 的产品预期/断言/清理(**不改 doc**)。
- 现有范本:`ua2_ops.py`、`provisioning/ua2_baseline.py`、`ua2_create_runtime.py`/`ua2_query_runtime.py`/`ua2_recycle_runtime.py`(16 个 handler)、`ua1_runtime.py`、`scenario_runtime.py`。

## 2. 架构复用(别重造)
- UA-2 case:`require_shared_datasource(ctx,"types"/"empty")` 取共享 DS,**不调 `prepare_datasource`、不建删 DS**;私有位号 `create_case_tag`+`cleanup_case_tag`(try/finally,registry 兜底);`ua_case_ua2_` 前缀。
- active 视图查询用 `active_rows`/`all_active_rows`(底层 `query_tags_with_quality groupId="0"`);回收站 `all_recycle_rows`。
- 状态:`BaselineError->BLOCKED`;`AssertFail->FAIL`;其它异常->ERROR;cleanup 独立(`cleanup_case_tag` 仅此处允许吞自身异常)。
- 凭据读 `env.json`(`ua_test_harness/env_config.py`),不用环境变量。
- UA-1 case:**继续用现有 `ua1_runtime` 模式**(每条 DS),**不迁移共享 baseline**(迁移需用户决策,未授权)。UA-3 case:用 `scenario_runtime` 共享场景。

## 3. 剩余工作(按优先级,做能做的)
**优先级:UA-2 余量(基础设施已就绪,最可行)-> UA-3(scenario_runtime)-> UA-1(需新夹具,做能做的,不迁移模型)**。

| 章节 | 余量 | 待补(_BLOCK_REASONS) | 现有能力可做? |
|---|---|---|---|
| UA-2-1/2/4 余量 | 多 | queryWithQuality/异常映射/批量/恢复/重建/历史生命周期 | 大部分可(复用 ua2_ops) |
| UA-2-3 导入导出 | 全 | xlsx 夹具+导入导出适配器 | 需新夹具,能建则建,不能则留 BLOCKED+记录 |
| UA-2-5 分组 | 全 | 分组树/移动/收藏/循环/批量 | 需新执行器,同上 |
| UA-3-1~6 余量 | 88 | 见 _BLOCK_REASONS(13类型/频率/并发/历史/性能等) | 扩 scenario_runtime,能做则做 |
| UA-1-3/4/6 等 | 44 | 断线/双源/ds-info/test 适配器 | 用 ua1_runtime 现模式,需新夹具则留 BLOCKED+记录 |

**不要求一晚做完 381。** 按优先级逐批做,能做多少做多少,每批 commit,留清晰状态。

## 4. 每条 case 验收标准(自我验证,不可降)
- ID 与 doc 一致;`@case` 元数据完整;函数体含前置/动作/断言。
- **不空函数、不固定 PASS、不吞异常(除 `cleanup_case_tag`)、不降阈值、不改 case 步骤。**
- 失败分类 FAIL/ERROR/BLOCKED/CLEANUP_FAILED;CLI 可单跑;复用逻辑有单测。
- 资源模型(上);真实未跑可 IMPLEMENTED 不 VERIFIED。

## 5. 自主决策边界(CRITICAL,用户睡了不能问)

### ✅ 你可以(测试代码)
- 按 doc spec 实现 handler,复用现有 pattern。
- 修 ERROR 级测试代码 bug(import/NameError/签名/参数错)。
- 选择语义正确的 API 端点实现测试意图(如 active 视图用 `query_tags_with_quality groupId=0`)--这是测试实现选择,允许,但记录。
- 加单测(fake/monkeypatch,验证调用参数+状态,非源码字符串伪造)。
- 注册到 `_SUPPORTED`/`_SHARED_SCENARIOS`。
- 为能做的章节建最小新夹具/mock(如 UA-2-3 的 xlsx 导入)。

### ❌ 你绝不可以
- 放宽产品断言、改阈值、改 case 步骤、加 try/except 让用例过。
- 自行做**产品语义决策**改变测试什么。例:doc 说"X 必须被拒",平台接受 X -> **保留 FAIL,记录发现**,不要换 API/改断言让它过(Bug #1 QTQ 那种"用错端点"的测试实现修正允许,但"产品行为与 doc 不符"不许掩盖)。
- 删共享 DS、改 `ua_shared_ua2_*`、改 UA-1 现有模型、改 doc markdown。
- `git add .`;碰子模块 `review3`/`data_factory_server`;提交 `output/`/密码/token/真实 IP/日志。
- 用环境变量存连接信息(用 env.json)。

### 📝 记录待用户决策(不决定、不改、保留现状)
- 产品 FAIL(产品行为≠doc)-> 保留 FAIL,记入 `docs/overnight-findings.md`。
- 模糊产品语义 -> 保留现状,记录。
- 需新基础设施且今晚建不了的 -> 留 BLOCKED,记录缺口。
- 环境 BLOCKED -> 记录。

## 6. 每批工作流
1. 选下一批(按优先级;每批 10~25 条,同 fixture/API 分组)。
2. 读 doc + `_BLOCK_REASONS[章]`。
3. 实现 handler(复用 pattern;UA-2 不调 prepare_datasource;私有位号显式建删)。
4. 注册 `_SUPPORTED`/`_SHARED_SCENARIOS`。
5. 单测(fake/monkeypatch)。
6. 自我验证对照 §4 验收标准。
7. `git add <仅本批文件>` -> commit(消息 `feat(ua2/ua1/ua3): <章> batch <范围>`)。
8. 能真跑则真跑该批(mock/TPT 可用时;读 env.json);记录结果。不要求全真跑(IMPLEMENTED≠VERIFIED)。
9. 产品发现/缺口记入 `docs/overnight-findings.md`。

## 7. 文档与报告(早晨交付)
- **`docs/overnight-findings.md`**(持续更新):逐条产品 FAIL / 模糊语义 / 缺口 / 环境 BLOCKED,含 case ID、现象、实测、建议。
- **`docs/overnight-report.md`**(收工时写):批清单、各章实现计数、单测结果、catalog/inventory、真跑结果、产品发现清单、BLOCKED 缺口清单、commit 列表、与 Plan 偏差。

## 8. 收工前最终验证
```
python -m compileall -q ua_test_harness scripts tpt_api
python -m pytest ua_test_harness\unit_tests -q
python -m ua_test_harness.cli catalog --output output\overnight-catalog.json
python -m ua_test_harness.case_inventory --repo-root . --expected-total 419 --strict-structure --output output\overnight-inventory.json
```
- 记录:catalog 419、各章计数、inventory documented/implemented/unimplemented/malformedRows/duplicateDocumentIds/structureOk。
- 已知 `test_e2e_smoke::test_run_cli_dry_run` GBK 环境失败不算回归。

## 9. 纪律重申
- 不为通过让步;FAIL/BLOCKED 如实;非测试代码问题记录不修;逐批 commit 保存进度;早晨报告写到 `docs/overnight-report.md`。
- 子 Agent 通过本文件自主执行;无法继续时停下并记录原因,不要硬来。

---
**一句话**: 通宵按优先级逐批实现剩余 case,复用现有架构,自我验证,逐批 commit,产品问题/缺口记入 `docs/overnight-findings.md`,收工写 `docs/overnight-report.md`。绝不放宽断言/改产品语义/掩盖 FAIL。
