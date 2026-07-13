# BACKGROUND - 给新子 Agent 的背景与文件地图

> 你是一个**新接手的执行 Agent**,没有之前的上下文。先读本文件,再读 `docs/talk-main.md`(你的任务),然后开干。

---

## 1. 你是谁、要做什么
你是 OPC UA / DataHub 自动化测试项目(`F:\github\supcon_tools`)的执行 Agent。主 Agent(技术负责人)已规划好,你的任务是**通宵推进 419 条 case 的全量开发**,任务详情在 `docs/talk-main.md`。本文件只负责给你背景和"去哪读什么"。

## 2. 项目是什么
- 被测对象:一个 TPT/DataHub 平台的 OPC UA 数据源、位号、采集、实时、历史等功能。
- **419 条文档 case**,定义在 `ua_test_gui/doc/test_cases/*.md`,分三章:
  - UA-1 数据源 56 条、UA-2 位号 265 条、UA-3 采集/实时/写/历史/性能 98 条。
- 每条 case 有 markdown 文档预期(前置/步骤/断言/清理);测试代码实现 handler,跑真实 TPT 验证产品行为。
- **真实实现进度 38/419**(UA-1:12、UA-2:16、UA-3:10);其余 381 条已注册但 BLOCKED(无 handler)。

## 3. 已经做了什么(资源模型重构,已验证)
- **旧问题**:每条 case 自建自删数据源 -> endpoint 冲突("currently in use" / "endpoint already exists") -> UA-2 第一批 0/16 全 FAIL。
- **新模型**:两个共享数据源在 TPT 服务器上 provision 一次,所有 case 复用;case 只建删自己的私有位号。
- **已完成 + 真实验证**:UA-2 第一批 16 条 = **15 PASS / 1 FAIL**(UA-2-1-019 空名产品 bug,保留 FAIL)。
- 凭据改用本地 `env.json`(不用环境变量)。

## 4. 架构(必须理解,实现 case 时复用)
- **共享 DS**:`ua_shared_ua2_types_ds`(mock 端口 18965)/ `ua_shared_ua2_empty_ds`(mock 18967)。`require_shared_datasource(ctx,"types"/"empty")` 按名查回复用,**不建不删不登记 cleanup**。
- **case 私有位号**:`ua_case_ua2_` 前缀;`create_case_tag` 建 + 登记 registry 兜底;`cleanup_case_tag` 在 try/finally 显式物理删 + 确认 + pop(吞自身异常只为不掩盖 case 状态)。
- **薄操作层 `ua2_ops.py`**:每函数单动作,无隐式预删/auto-enable/auto-cleanup。
- **provisioning 层**:创建/校验共享 DS;`BaselineError -> BLOCKED`(已在 `ua2_runtime.execute_ua2_case` 接线)。
- **状态分类**:FAIL(产品断言不符)/ERROR(Python 框架异常)/BLOCKED(共享DS/环境)/CLEANUP_FAILED(清理,与 case 状态独立记录)。
- **active 视图查询**:用 `query_tags_with_quality(groupId="0")`(经 `ua2_ops.active_rows`);**不要用 `list_tags`**(它含软删记录,Bug #1)。回收站用 `all_recycle_rows`。
- **UA-2 case 不调 `prepare_datasource`**;UA-1 继续用 `ua1_runtime` 现模式(**不迁移**,需用户决策)。
- **凭据**:读 `env.json`(`ua_test_harness/env_config.py`),不用环境变量。

## 5. 去哪里读什么(文件地图)
- **你的任务**:`docs/talk-main.md`(通宵派单:决策边界、每批工作流、报告要求)。
- **架构/验收细则**:`docs/compose/guidance/ua2-refactor-guide.md`。
- **路线图/验收/工作流**:`.mimocode/plans/1783855834448-mighty-nebula.md`(Part 4)。
- **case 规格(不改)**:`ua_test_gui/doc/test_cases/UA-2-1.md`、`UA-2-2.md`、`UA-2-4.md`、`UA-2-3.md`、`UA-2-5.md`、`UA-1-*.md`、`UA-3-*.md`。
- **派发注册 + 各章缺口**:`ua_test_harness/scenario_policy.py`(`_SUPPORTED` 已支持清单 / `_SHARED_SCENARIOS` UA-3 场景 / `_BLOCK_REASONS` 各章待补适配器=路线图)。
- **现有 handler 范本(照着写)**:
  - UA-2:`ua_test_harness/ua2_create_runtime.py`、`ua2_query_runtime.py`、`ua2_recycle_runtime.py`(16 个已实现 handler)。
  - UA-1:`ua_test_harness/ua1_runtime.py`。
  - UA-3:`ua_test_harness/scenario_runtime.py`(共享场景 rt_read/rt_write/history/response_time/performance)。
- **薄操作层**:`ua_test_harness/ua2_ops.py`(`create_case_tag`/`cleanup_case_tag`/`active_rows`/`all_active_rows`/`all_recycle_rows`/`physical_delete_tag` 等)。
- **provisioning**:`ua_test_harness/provisioning/ua2_baseline.py`。
- **tpt_api 真实签名(实现前核实)**:`tpt_api/python/tpt_api/datahub.py` —— `add_tag`/`list_tags`/`query_tags_with_quality`/`delete_tags`(软)/`delete_tags_physical`/`remove_tag_group_relation`/`list_recycle_tags`/`list_ds_info`/`add_ds_info`/`change_ds_state`/`delete_ds_info`。
- **config/runner/脚本**:`ua_test_harness/config.py`、`context.py`、`runner.py`、`ua2_runtime.py`;`scripts/run_automation_ua2.py`、`cleanup_ua2_resources.py`、`diagnose_ua2_datasource.py`、`teardown_ua2_baseline.py`。
- **bug 记录**:`bugs.md`(Bug#1 QTQ 切换、Bug#2 空名产品 bug、019 泄漏修复、alive-wait 120s)。
- **env.json 模板**:`env.json.example`(真实 `env.json` 本地、gitignored;password 没有就问用户)。
- **工程纪律**:`AGENTS.md`(必读)。

## 6. 工程纪律(AGENTS.md 摘要,必守)
- Case 跑不过**不改 Case**;不绕路强修;环境问题说出来;不吞错(除 `cleanup_case_tag`);不降阈值。
- 不碰子模块 `review3`/`data_factory_server`;不提交 `output/`/密码/token/真实 IP/日志。
- 禁止 `git reset --hard`/`git clean -fd`/`git checkout .`/`git restore .`/`git stash`。
- 不 `git add .`,只暂存本批文件。
- 不改 doc markdown 产品预期(除非明确错误并记录)。

## 7. 你的产出
- 逐批实现 -> 单测 -> commit(`feat(ua2/ua1/ua3): <章> batch <范围>`)。
- 产品发现/缺口/待决策 -> `docs/overnight-findings.md`。
- 收工报告 -> `docs/overnight-report.md`(批清单/计数/单测/catalog/inventory/真跑/产品发现/BLOCKED 缺口/commits)。

## 8. 第一步
读本文件 -> `docs/talk-main.md` -> `docs/compose/guidance/ua2-refactor-guide.md` -> `ua_test_harness/scenario_policy.py` -> 开干。
