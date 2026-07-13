# memory.md - UA-2 资源模型重构 & 419 全量开发 交接文档

> 本文件是新会话接手的**第一份必读**。记录项目背景、已完成工作、当前状态、架构、决策、通宵派单、文件地图、下一步。读完本文件再读 `docs/talk-main.md`、`docs/BACKGROUND.md`、`bugs.md`。

---

## 0. 一句话现状
UA-2 位号测试资源模型重构已完成并真实验证(16 条第一批 = 15 PASS / 1 产品 bug FAIL);419 全量开发进行中(真实实现 38/419);子 Agent 正通宵自主开发剩余 case,结果落在 `docs/overnight-report.md` + `docs/overnight-findings.md`。

---

## 1. 项目背景
- 仓库:`F:\github\supcon_tools`(Windows PowerShell)。
- 被测对象:TPT/DataHub 平台的 OPC UA 数据源、位号、采集、实时、历史、性能。
- **419 条文档 case**,定义在 `ua_test_gui/doc/test_cases/*.md`:
  - UA-1 数据源 56 条、UA-2 位号 265 条、UA-3 采集/实时/写/历史/性能 98 条。
- 每条 case 有 markdown 预期(前置/步骤/断言/清理);测试代码实现 handler,跑真实 TPT 验证产品行为。
- 工程纪律见 `AGENTS.md`:Case 跑不过不改 Case;不绕路;环境问题说出来;不吞错(除 `cleanup_case_tag`);不降阈值;不碰子模块 `review3`/`data_factory_server`;不提交 output/密码/token/真实 IP/日志;禁止 `git reset --hard`/`clean -fd`/`checkout .`/`restore .`/`stash`;不 `git add .`。

## 2. 已完成并验证(资源模型重构)
- **旧问题**:每条 case 自建自删数据源 -> endpoint 冲突("currently in use" / "endpoint already exists") -> UA-2 第一批 0/16 全 FAIL。
- **新模型**:两个共享数据源在 TPT 服务器上 provision 一次,所有 case 复用;case 只建删自己的私有位号。
- **UA-2 第一批 16 条已完成 + 真实验证**:K 跑 `output/automation_ua2_20260712_235003` = **15 PASS / 1 FAIL / 0 ERROR / 0 BLOCKED / 0 cleanupFailed**。
  - 1 FAIL = UA-2-1-019 空名产品 bug(平台接受空名,保留 FAIL,按用户决策不改)。
- 凭据改用本地 `env.json`(不用环境变量)。

## 3. 当前状态
- **真实实现 38/419**:UA-1 12、UA-2 16、UA-3 10。余 381 条已注册但 BLOCKED(无 handler)。
- HEAD commit = `e7ada0e`。工作树干净(只剩子模块 `review3`/`data_factory_server` 移动 + untracked 文档)。
- 单测 142 passed(唯一失败 `test_e2e_smoke::test_run_cli_dry_run` 是预先存在的 GBK 解码环境问题,非回归)。
- catalog=419、inventory documented=419/implemented=419/unimplemented=0/structureOk。

## 4. 架构(实现 case 时复用)
- **共享 DS**:`ua_shared_ua2_types_ds`(mock 18965)/ `ua_shared_ua2_empty_ds`(mock 18967)。`require_shared_datasource(ctx,"types"/"empty")` 按名查回复用,**不建不删不登记 cleanup**。provisioning 在 `ua_test_harness/provisioning/ua2_baseline.py`(`ensure_ua2_baseline`)。
- **case 私有位号**:`ua_case_ua2_` 前缀;`create_case_tag` 建 + 登记 registry 兜底;`cleanup_case_tag` 在 try/finally 显式物理删 + 确认 + pop(吞自身异常只为不掩盖 case 状态)。
- **薄操作层** `ua_test_harness/ua2_ops.py`:每函数单动作,无隐式预删/auto-enable/auto-cleanup。含 `create_case_tag`/`cleanup_case_tag`/`active_rows`/`all_active_rows`/`all_recycle_rows`/`physical_delete_tag`/`soft_delete_tag`/`restore_tag`/`create_tag_raw` 等。
- **provisioning**:`ensure_ua2_baseline` 创建/校验共享 DS;`BaselineError -> BLOCKED`(已在 `ua2_runtime.execute_ua2_case` 接线)。
- **状态分类**:FAIL(产品断言不符)/ERROR(Python 框架异常)/BLOCKED(共享DS/环境)/CLEANUP_FAILED(清理,与 case 状态独立记录)。
- **active 视图查询**:用 `query_tags_with_quality(groupId="0")`(经 `ua2_ops.active_rows`);**不要用 `list_tags`**(它含软删记录,Bug #1)。回收站用 `all_recycle_rows`。
- **alive-wait**:provisioning 业务级专用 `BASELINE_ALIVE_WAIT_SEC=120`/`BASELINE_ALIVE_POLL_SEC=1.0`(与通用 `ds_connect_sec` 解耦;停过又起的 DS 恢复需 1~2 分钟)。
- **UA-2 case 不调 `prepare_datasource`**;UA-1 继续用 `ua1_runtime` 现模式(**不迁移**,需用户决策);UA-3 用 `scenario_runtime` 共享场景。
- **凭据**:读 `env.json`(`ua_test_harness/env_config.py`),不用环境变量。`env.json` 已 gitignored;`env.json.example` 是模板(密码留空)。

## 5. Bug 决策(用户已定)
- **Bug #1 = A**:接受 `9e826e6`(QTQ 切换)。`list_tags`(tag-info/page)含软删记录,不是 active 视图;`query_tags_with_quality(groupId=0)` 是平台自己的 active 视图。测试原本用错端点,切换合理。已真实验证(UA-2-4-001 转 PASS)。
- **Bug #2 = A**:产品 bug。平台 `add_tag(tag_name="")` 接受空名并生成 `tagName="2_"` 位号,与 doc "空名必拒" 不符。**保留 UA-2-1-019 为 FAIL**,不改断言,作为产品缺陷上报。
- **019 泄漏已修**(`04e4628`):handler 加 try/finally 兜底清理(check_true 抛 AssertFail 后也清掉平台偷建的位号),不改 FAIL 结局。
- **alive-wait 已修**(`e7ada0e`):60s -> 120s 业务级专用。
- 详见 `bugs.md`。

## 6. 通宵派单(子 Agent 自主执行)
- 用户已睡。新子 Agent 按 `docs/talk-main.md`(任务+决策边界+工作流)+ `docs/BACKGROUND.md`(背景+文件地图)通宵自主开发剩余 381 case。
- **优先级**:UA-2 余量(基础设施已就绪)-> UA-3(scenario_runtime)-> UA-1(需新夹具,做能做的,不迁移模型)。
- **决策边界**:测试代码 bug 可修;产品 FAIL/模糊语义/缺夹具 -> 保留现状记 `docs/overnight-findings.md`,不掩盖不让步;**绝不放宽断言/改产品语义/加 try/except 过**。
- **早晨交付**:`docs/overnight-report.md`(批清单/计数/单测/catalog/inventory/真跑/发现/缺口/commits)+ `docs/overnight-findings.md`(逐条待决策)。
- **新会话接手后**:先读这两个文件,陪用户 triage 产品发现和缺口;再继续未完成批次。

## 7. 文件地图(去哪读什么)
- **任务/派单**:`docs/talk-main.md`(通宵全量开发)、`docs/BACKGROUND.md`(新 Agent 背景与地图)。
- **路线图/验收/工作流**:`.mimocode/plans/1783855834448-mighty-nebula.md`(Part 1 env.json、Part 2 K、Part 3 alive-wait、Part 4 全量 419 路线图)。
- **架构/验收细则**:`docs/compose/guidance/ua2-refactor-guide.md`。
- **总 Plan(参考代码)**:`docs/compose/plans/2026-07-12-ua2-resource-refactor.md`。
- **case 规格(不改)**:`ua_test_gui/doc/test_cases/UA-*.md`。
- **派发注册 + 各章缺口**:`ua_test_harness/scenario_policy.py`(`_SUPPORTED` 已支持清单 / `_SHARED_SCENARIOS` UA-3 场景 / `_BLOCK_REASONS` 各章待补适配器=路线图)。
- **现有 handler 范本**:
  - UA-2:`ua_test_harness/ua2_create_runtime.py`、`ua2_query_runtime.py`、`ua2_recycle_runtime.py`(16 个已实现 handler)。
  - UA-1:`ua_test_harness/ua1_runtime.py`。
  - UA-3:`ua_test_harness/scenario_runtime.py`(共享场景 rt_read/rt_write/history/response_time/performance)。
- **薄操作层**:`ua_test_harness/ua2_ops.py`。
- **provisioning**:`ua_test_harness/provisioning/ua2_baseline.py`。
- **tpt_api 真实签名(实现前核实)**:`tpt_api/python/tpt_api/datahub.py` -- `add_tag`/`list_tags`/`query_tags_with_quality`/`delete_tags`(软)/`delete_tags_physical`/`remove_tag_group_relation`/`list_recycle_tags`/`list_ds_info`/`add_ds_info`/`change_ds_state`/`delete_ds_info`。
- **config/runner/脚本**:`ua_test_harness/config.py`、`context.py`、`runner.py`、`ua2_runtime.py`;`scripts/run_automation_ua2.py`、`cleanup_ua2_resources.py`、`diagnose_ua2_datasource.py`、`teardown_ua2_baseline.py`、`run_with_timeout.py`。
- **bug 记录**:`bugs.md`。
- **env.json 模板**:`env.json.example`(真实 `env.json` 本地、gitignored;password 没有就问用户)。
- **工程纪律**:`AGENTS.md`、`ua_test_gui/doc/case-first-plan.md`。
- **真实跑产物**:`output/automation_ua2_20260712_235003/`(最新有效 K 跑);旧废产物 221246/225922/230301。

## 8. commit 链(本会话新增,基于接手时 `9fb5685`)
```
e7ada0e fix(ua2): dedicated business-level baseline alive-wait (120s/1s poll)
04e4628 fix(ua2): clean up leaked tag in UA-2-1-019 finally; record bug decisions
9e826e6 fix(ua2): replace list_tags with query_tags_with_quality (groupId=0/1)
e213cea docs(ua2): fix stale precheck comment to reflect env.json
473fbce refactor(ua2): replace env-var config with local env.json for UA-2 automation
2ea2dbd refactor(ua2): runner starts two mocks, provisions baseline, keeps shared DS   (I)
ca2de29 feat(ua2): add baseline teardown and read-only datasource diagnostic         (H)
6b3d99b refactor(ua2): UA-2-4 delete/restore cases use shared datasource              (F)
785c7d2 refactor(ua2): UA-2-2 query cases use shared datasources + push filters        (E)
16fdc10 refactor(ua2): UA-2-1 cases use shared datasource and explicit tag cleanup    (D)
856b779 feat(ua2): map BaselineError to BLOCKED in UA-2 dispatch           (主Agent接线)
f3899c3 refactor(ua2): cleanup tool scoped to case-private resources                   (G)
263a8a6 feat(ua2): add shared baseline datasource provisioning layer                   (B)
491d02d feat(ua2): add thin single-action ops layer for UA-2 cases                     (C)
9fb5685 (接手时 HEAD,旧反模式第一批实现)
```
任务字母对应 `.mimocode/plans` 与 guidance 的任务分解:A(Empty Mock,`fe119c5` 在 0cb9780 之前)、B/C/G(基础设施)、D/E/F(UA-2 三章重构)、H/I(脚本)、J(跨模块回归 `0cb9780`)、K(真实环境)。

## 9. 关键 gotchas
- `list_tags` 含软删记录,active 视图必须用 `query_tags_with_quality(groupId=0)`(Bug #1)。
- 共享 DS 停过又起恢复 alive 需 1~2 分钟,provisioning alive-wait 已设 120s。
- `test_e2e_smoke::test_run_cli_dry_run` 在 Windows GBK 区域会失败(子进程 UTF-8 输出用 GBK 解码),非回归,不要修。
- 子 Agent 是**外部便宜 Agent**,经 `docs/talk-main.md` 派单,**不要用主 Agent 的 actor 工具**(消耗高成本 token)。主 Agent 角色:架构/验收/triage,非测试代码问题问用户。
- 不要改 doc markdown 产品预期;不要为通过放宽断言。
- UA-1 资源模型迁移到共享 baseline 需用户决策(未授权,先别动)。

## 10. 下一步(新会话)
1. 读本文件 + `docs/overnight-report.md` + `docs/overnight-findings.md`(若子 Agent 已产出)。
2. 陪用户 triage 产品发现(Bug #2 类)和缺口(需新夹具的章节)。
3. 继续未完成的 419 批次:按 `.mimocode/plans/1783855834448-mighty-nebula.md` Part 4 路线图,逐章派单 `docs/talk-main.md` -> 子 Agent 实现 -> 主 Agent 验收。
4. 验收每批:commit 范围/资源模型/状态分类/断言未放宽/单测+回归/catalog-inventory 仍 419。
5. 最终:catalog 419、`_SUPPORTED`∪`_SHARED_SCENARIOS` 全覆盖、各章真实跑+残留检查、compileall 干净。

---
**生成时间**:2026-07-13(本地凌晨)。**生成者**:主 Agent(MiMoCode)。用户已睡,子 Agent 通宵开发中。
