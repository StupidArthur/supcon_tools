# UA-2 资源模型重构 — 执行指导与验收手册

> 本文件是给**执行 Agent**的操作手册。主 Agent(技术负责人)负责架构、任务拆分、验收准则和最终验收;执行 Agent 按本文件逐任务实现。主 Agent **不派子 Agent**(避免重复消耗高成本 token)。
>
> 参考代码: `docs/compose/plans/2026-07-12-ua2-resource-refactor.md`(总 Plan,含各任务参考实现代码)。执行 Agent 实现时以本文件的行为要求为准,参考总 Plan 的代码骨架,但**以真实代码为准**;两者冲突时停止扩大修改并报告。

---

## 0. 工作方式(执行 Agent 必读)

1. **一次只做一个任务**,按 §3 顺序。做完一个、回报、等主 Agent 验收通过,再做下一个。
2. 每个任务: 读本文件对应章节 → 读"先读"列出的真实代码 → 读总 Plan 对应 Task 的参考代码 → 实现 → 跑"验收命令" → commit → 按 §5 格式回报。
3. **严禁扩大范围**: 只改"允许修改/新增"的文件。"禁止修改"的文件一行都不许动。
4. **发现 Plan/参考代码与真实代码不一致**: 停止扩大修改,在回报里精确报告差异(哪个函数签名不同、哪个字段不存在),**不要擅自偏离或猜**。
5. **测试用 fake/monkeypatch**,不连真实 TPT。不用 `inspect.getsource()` 做字符串检查来伪造覆盖(除非该任务明确要求源码结构断言)。
6. commit 只暂存本任务文件,**不要 `git add .`**;不碰子模块 `review3`/`data_factory_server`;不提交 `output/`、密码、token、真实 IP。
7. 每个 commit 用本任务给定的 commit message。

---

## 1. 架构概要(必读,影响所有任务)

- **共享数据源活在 TPT 服务器上,不是 Python registry。** runner 每条 case 跑独立子进程,跨进程无法共享 registry。所以:provisioning 在批次开头调用一次,在 TPT 服务器上创建/校验两个共享 DS;每条 case 子进程用 `require_shared_datasource(ctx, "types"/"empty")` 按固定名字查回来用,**不创建、不删除、不登记 cleanup**。
- 两个共享 DS(固定名):
  - `ua_shared_ua2_types_ds` → mock `ua2_types.yaml` 端口 18965
  - `ua_shared_ua2_empty_ds` → mock `ua2_empty.yaml` 端口 18967(空,无位号)
- **普通 case 只查共享 DS,自己创建/删除 `ua_case_ua2_` 前缀的私有位号。** 创建→测试→物理删除→确认消失,全部在 case 代码里显式可见。registry 只作异常兜底。
- **状态分类**: 产品断言失败=`FAIL`;Python 异常/参数错=`ERROR`;共享DS不存在/配置错/Mock没起/endpoint冲突=`BLOCKED`;清理失败=`CLEANUP_FAILED`(与 case 状态**独立记录**)。**禁止为通过测试放宽产品断言。**
- **`BaselineError` → `BLOCKED` 的接线由主 Agent 亲自做**(在 B 完成后改 `ua2_runtime.py` 3 行),**不交给执行 Agent**。执行 Agent 只管 B 模块本身。
- **不动 UA-1**: `fixtures/datasource.py`、`fixtures/tag.py`、`ua2_common.py`、`ua1_runtime.py` 全部保留给 UA-1/legacy。新代码进新模块。
- `tpt_api` 的 import 路径由 `ua_test_harness/_paths.py` 注入(`tpt_api/python`),现有单测已能 `import tpt_api`,新测试文件放 `ua_test_harness/unit_tests/` 下即可继承。

---

## 2. 全局禁令(所有任务继承)

- 不修改 UA-1 相关: `fixtures/datasource.py`、`fixtures/tag.py`、`ua1_runtime.py`、`ua2_common.py` 中的 `prepare_datasource`(保留)。
- 不自动删除共享资源(`ua_shared_ua2_*`)。
- 不为通过测试吞掉 cleanup 异常(唯一例外: `ua2_ops.cleanup_case_tag` 明确允许吞,以防止清理掩盖 case 原始状态)。
- 不放宽产品断言、不改 case 步骤顺序、不改阈值。
- 不用 `git add .`;不碰子模块;不提交 `output/`、密码、token、真实内网 IP、运行日志。
- 不开发 UA-2 第二批;不改 GUI。
- 禁止执行: `git reset --hard`、`git clean -fd`、`git checkout .`、`git restore .`、`git stash`。

---

## 3. 任务分解与顺序

> A 已由主 Agent 完成并验证。执行 Agent 从 B 开始。

| 任务 | 允许改/增文件 | 测试文件 | 依赖 | 阶段 |
|---|---|---|---|---|
| A. Empty Mock | `ua_mocker/ua2_empty.yaml` | — | 无 | 1(已完成) |
| B. Baseline provisioning | 增 `provisioning/__init__.py`、`provisioning/ua2_baseline.py` | `test_ua2_baseline.py` | 无 | 1 |
| C. Thin ops | 增 `ua2_ops.py` | `test_ua2_ops.py` | 无 | 1 |
| G. Cleanup 工具 | 改 `scripts/cleanup_ua2_resources.py` | `test_cleanup_ua2.py` | 无 | 1 |
| *(主 Agent)* BaselineError→BLOCKED 接线 | 改 `ua2_runtime.py`(3行) | — | B 完成 | 1→2 之间 |
| D. UA-2-1 重构 | 改 `ua2_create_runtime.py` | `test_ua2_1_refactor.py` | B+C+接线 | 2 |
| E. UA-2-2 重构 | 改 `ua2_query_runtime.py` | `test_ua2_2_refactor.py` | B+C+接线 | 2 |
| F. UA-2-4 重构 | 改 `ua2_recycle_runtime.py` | `test_ua2_4_refactor.py` | B+C+接线 | 2 |
| H. Teardown+Diagnose | 增 `scripts/teardown_ua2_baseline.py`、`scripts/diagnose_ua2_datasource.py` | `test_diagnose_teardown_ua2.py` | B、A | 3 |
| I. Runner | 改 `scripts/run_automation_ua2.py`、`run_automation_ua2.ps1` | `test_runner_ua2.py` | B、A、G | 3 |
| J. 跨模块回归 | 增 `test_ua2_resource_model.py` | — | 全部 | 4(主 Agent) |
| K. 真实环境 | — | — | 全部 | 5(主 Agent,需环境) |

**依赖图**: `A→I`; `B→D/E/F/H/I`; `C→D/E/F`; `B+C+接线→D/E/F`; `A+B→H/I`。
**并行规则**: 同阶段文件不重叠才可并行。但本流程是**串行逐任务验收**,不并行。

---

## 4. 验收准则框架(主 Agent 如何验收每个任务)

每个任务回报后,主 Agent 按此顺序验收:

1. **commit 范围**: `git show --stat <sha>` — 只改了允许的文件;无敏感信息;无子模块;无 output;无无关重构。
2. **读关键实现**: 资源所有权是否正确、是否隐藏业务步骤、是否误吞异常、是否把 Harness ERROR 当产品 FAIL、是否把 BLOCKED 当 ERROR、是否有错误自动清理、是否有闭包晚绑定、查询是否真把条件传给 API、测试是否只靠源码字符串。
3. **跑该任务测试命令**。
4. **跑相关回归**(不只跑新测试)。
5. **结论**: `ACCEPTED` / `ACCEPTED_WITH_SMALL_FIX`(主 Agent 直接补 fix commit) / `REWORK_REQUIRED`(回执行 Agent,附修正 Plan) / `PLAN_REVISION_REQUIRED` / `BLOCKED_BY_PRODUCT_SEMANTICS` / `BLOCKED_BY_ENVIRONMENT`。

---

## 5. 执行 Agent 回报格式(每个任务完成后必须按此回报)

```
**任务**: <任务字母. 名称>
**状态**: success | partial | failed | blocked
**摘要**: 一行
**修改/新增文件**: 列表
**测试结果**: pytest 摘要(N passed) + compileall 结果
**commit SHA**: 完整 sha
**git status --short**: 输出
**与 Plan/真实代码的差异**: 精确列出(函数签名/字段不同等);无则写"无"
**已知风险**: 无则写"无"
```

---

## 6. 任务详单

### A. Empty Mock — 已完成(主 Agent)

`ua_mocker/ua2_empty.yaml` 已落盘并验证(`port=18967, nodes=[]`,config_loader 可加载)。执行 Agent 跳过此任务。

---

### B. Baseline provisioning 层

**背景**: 16 条 case 现在每条都 `prepare_datasource` 自建自删数据源,导致 endpoint 冲突和"currently in use"删除失败。本任务建 provisioning 层,在 TPT 服务器上创建/校验两个共享 DS,供所有 case 复用。

**修改范围**:
- 新增: `ua_test_harness/provisioning/__init__.py`、`ua_test_harness/provisioning/ua2_baseline.py`
- 新增: `ua_test_harness/unit_tests/test_ua2_baseline.py`
- 禁止改: 任何其它文件(尤其 `fixtures/`、`ua2_common.py`、`ua2_runtime.py`、`resources.py`)。

**先读(真实代码)**:
- `ua_test_harness/context.py`(RunContext: config, bag)
- `ua_test_harness/config.py`(RunConfig: `mock.endpoints.functional`、`local_ip`、`timeouts.ds_connect_sec`、`subject.*`)
- `ua_test_harness/fixtures/environment.py`(`ensure_logged_in(ctx)`)
- `ua_test_harness/clients/tpt_client.py`(`get_api(ctx)`)
- `tpt_api/python/tpt_api/datahub.py` 核实签名: `list_ds_info(page,page_size,sort,data)`、`add_ds_info(ds_name,ds_tar_url,ds_sub_type=4,...)`(默认参数可用,直接 `add_ds_info(api,ds_name=,ds_tar_url=)`)、`change_ds_state(ds_id,enabled)`、`delete_ds_info(ids)`、`list_tags(page,page_size,sort,data)`(data 支持 `{"dsId":..}`)、`list_recycle_tags(page,page_size,group_id,tag_type,sort)`(返回 `{tagInfoList:{records}}`)。
- 总 Plan "Task 2" 节(参考代码)。

**实现要求(行为)**:
- 常量: `SHARED_TYPES_DS_NAME="ua_shared_ua2_types_ds"`、`SHARED_EMPTY_DS_NAME="ua_shared_ua2_empty_ds"`。
- `class BaselineError(Exception)`。
- `@dataclass Ua2Baseline(types_ds_id:int, types_ds_name:str, types_endpoint:str, empty_ds_id:int, empty_ds_name:str, empty_endpoint:str)`。
- `ensure_ua2_baseline(ctx)->Ua2Baseline`:
  - `ensure_logged_in(ctx)` 开头调。
  - types endpoint = `ctx.config.mock.endpoints.functional`(空则 `BaselineError`)。
  - empty endpoint = `os.environ.get("UA2_EMPTY_ENDPOINT")` 或 `f"opc.tcp://{ctx.config.local_ip or '127.0.0.1'}:18967/ua_mocker/"`。
  - 每个 DS: 按 `list_ds_info(data={"dsName":name})` 查;不存在→`add_ds_info`+`change_ds_state(True)`+轮询 alive;存在→endpoint 必须精确匹配(不匹配 `BaselineError`,**绝不自动删**),不 alive 则 enable+等待。**绝不登记 cleanup,绝不删除。**
  - 仅 empty DS: ensure 后必须确认无活动位号(`list_tags(data={"dsId":id})` records 为空)**且**无回收站关联位号(分页 `list_recycle_tags` page_size=200 循环,按 dsId 本地过滤)。非空→`BaselineError`(**绝不自动清空**)。
- `require_shared_datasource(ctx, logical_name)->dict`: `logical_name ∈ {"types","empty"}`。按固定名查;不存在/endpoint 不匹配/not alive → `BaselineError`。**不创建、不删除、不登记 cleanup**。开头 `ensure_logged_in(ctx)`。返回 `{"id","name","endpoint","alive"}`。
- `teardown_ua2_baseline(ctx,*,confirm=False)`: `confirm` 非 True → `BaselineError`;True 则 best-effort disable + delete 两个。
- `__init__.py` 导出: `BaselineError, Ua2Baseline, ensure_ua2_baseline, require_shared_datasource, teardown_ua2_baseline, SHARED_TYPES_DS_NAME, SHARED_EMPTY_DS_NAME`。

**必须的单测**(`test_ua2_baseline.py`,用 fake/monkeypatch,断言调用与状态,非源码字符串):
建 `_ctx()` 用真实 `RunContext` + `MagicMock` emitter;monkeypatch `tpt_api.datahub` 各函数与 `ua_test_harness.clients.tpt_client.get_api`;monkeypatch 你的 alive 轮询 helper 返回 True(不 sleep)。
1. ensure 复用已存在 types DS(name+endpoint+alive 正确)→ `add_ds_info` 未调用;`baseline.types_ds_id`==已存在 id。
2. ensure 不存在时创建 → `add_ds_info` 调一次;`change_ds_state(True)` 调;返回新 id。
3. ensure endpoint 不匹配 → `BaselineError`;`delete_ds_info` 未调用。
4. ensure empty DS 有活动位号(`list_tags(data={"dsId":id})` 返回1条)→ `BaselineError`。
5. ensure empty DS 有回收站关联位号(fake 2 页,1 条 dsId 匹配)→ `BaselineError`。
6. `require_shared_datasource("types")` 存在+alive → 返回 dict;无 create/delete。
7. require 不存在 → `BaselineError`。
8. require alive=False → `BaselineError`。
9. require endpoint 不匹配 → `BaselineError`。
10. teardown `confirm=False` → `BaselineError`;`confirm=True` → disable+delete 两个。

**验收命令**(在 `F:\github\supcon_tools`):
```
python -m compileall -q ua_test_harness\provisioning
python -m pytest ua_test_harness\unit_tests\test_ua2_baseline.py -q
```

**commit**: `git add ua_test_harness\provisioning\__init__.py ua_test_harness\provisioning\ua2_baseline.py ua_test_harness\unit_tests\test_ua2_baseline.py` → `git commit -m "feat(ua2): add shared baseline datasource provisioning layer"`

**验收准则(主 Agent)**:
- [ ] 只新增 3 个文件,未碰禁止文件。
- [ ] 共享 DS 未登记到任何 registry;config 不匹配时 raise 不删;empty DS 非空时 raise 不清空。
- [ ] `require_shared_datasource` 不 create/delete/register。
- [ ] 10 个单测全过;compileall 通过。
- [ ] 回归: `python -m pytest ua_test_harness\unit_tests\test_ua2_first_batch.py -q` 仍全过(未碰旧代码)。

---

### C. Thin ops 层

**背景**: 旧 fixture 隐式预删同名、隐式登记 cleanup,case 读不懂资源生命周期。本任务建薄操作层,每函数只做一件事,无隐式行为。case 将显式管理私有位号;`create_case_tag` 登记的 registry 项是**兜底**。

**修改范围**:
- 新增: `ua_test_harness/ua2_ops.py`、`ua_test_harness/unit_tests/test_ua2_ops.py`
- 禁止改: 任何其它文件。

**先读**:
- `tpt_api/python/tpt_api/datahub.py` 核实: `add_tag(tag_name,data_type,tag_type,ds_id,group_id,unit,only_read,frequency,need_push,tag_desc,is_vector,tag_base_name,...)`、`list_tags`、`delete_tags(ids)`(软)、`delete_tags_physical(ids)`、`remove_tag_group_relation(group_id,tag_ids)`、`add_ds_info`、`delete_ds_info`、`change_ds_state`、`list_ds_info`、`list_recycle_tags`。
- `tpt_api/python/tpt_api/types.py` 核实名: `DataTypes`、`TagTypes`(确认 key `"一次位号"`)、`DsSubTypes`(确认 `"OPC_UA_SERVER"`)。
- `ua_test_harness/resources.py`(`ResourceRegistry`: `register(name,kind,cleanup,payload=None)`、`pop(name)->Resource|None`、`snapshot()`、`size()`)。
- `ua_test_harness/context.py`、`ua_test_harness/clients/tpt_client.py`。
- 总 Plan "Task 3" 节(参考代码)。

**实现要求(行为)**:
- 常量: `CASE_TAG_PREFIX="ua_case_ua2_"`、`CASE_DS_PREFIX="ua_case_ua2_ds_"`。
- 数据源 ops(单动作,无隐式): `create_datasource_raw(ctx,name,endpoint,*,sub_type="OPC_UA_SERVER")->dict`(只 `add_ds_info`,不 enable/不查/不删同名);`find_datasource_by_name`、`find_datasource_by_id`;`enable_datasource`、`disable_datasource`;`wait_datasource_alive(ctx,ds_id,timeout=60.0)->bool`、`wait_datasource_offline(ctx,ds_id,timeout=30.0)->bool`(find_by_id 为 None 即 True);`delete_datasource_raw(ctx,ds_id,*,disable_first=True)`(best-effort disable→delete→wait_offline)。
- 位号 ops(单动作,无预删): `create_tag_raw(ctx,name,ds_id,*,data_type="INT",tag_base_name=None,tag_desc=None,frequency=1)->dict`(只 `add_tag`,**绝不调 `delete_tags_physical`**;`tag_base_name` 默认 `"2_"+name`);`find_tag_by_name`、`find_tag_by_id`(用 `all_active_rows`);`soft_delete_tag(ctx,tag_id)`、`restore_tag(ctx,tag_id)`(`remove_tag_group_relation` group_id="1")、`physical_delete_tag(ctx,tag_id)`、`wait_tag_absent(ctx,name,timeout=30.0)->bool`。
- case 位号 helpers: `case_tag_name(ctx,cc,suffix)->str`(`f"{CASE_TAG_PREFIX}{case_id}_{run_id[:12]}_{suffix}_{time_ns%1e6}"`,case_id/run_id 的 `-`→`_`);`create_case_tag(ctx,cc,ds_id,*,suffix="tag",data_type="INT",tag_base_name=None,tag_desc=None)->dict`(name=`case_tag_name`;`create_tag_raw`;在 `cc.registry` 登记**兜底** key `f"tag:{name}"` → `lambda: physical_delete_tag(ctx,tag_id)`);`cleanup_case_tag(ctx,cc,tag_id,tag_name)->None`(`try: physical_delete_tag + wait_tag_absent + cc.registry.pop(f"tag:{tag_name}"); except Exception: pass` — **明确允许吞**,防止清理掩盖 case 状态;pop 未执行则兜底仍登记)。
- 查询 helpers: `active_rows(ctx,**filters)->list`(单页 `list_tags(data=filters or {})`,`.records or []`,filters 下推 API);`all_active_rows(ctx,**filters)->list`(分页 page_size=500 至 <page_size);`all_recycle_rows(ctx)->list`(分页 `list_recycle_tags` page_size=200,展平 `tagInfoList.records`);`exact(rows,field,value)->list`。

**必须的单测**(`test_ua2_ops.py`,用真实 `ResourceRegistry` 作 `cc.registry`,monkeypatch `tpt_api.datahub`+`get_api`,断言调用与状态):
1. `create_tag_raw` 只调 `add_tag` 一次;**从不**调 `delete_tags_physical`。
2. `create_datasource_raw` 只调 `add_ds_info` 一次;**从不**调 `change_ds_state`。
3. `case_tag_name(ctx,cc,"dup")` 以 `"ua_case_ua2_"` 开头且含 case_id。
4. `create_case_tag` 登记兜底: `registry.size()==1` 且 `snapshot()[0]["name"]=="tag:{name}"`。
5. `cleanup_case_tag` 后: `physical_delete_tag` 被调,`wait_tag_absent` 返回 True(fake),`registry.size()==0`(已 pop)。
6. `cleanup_case_tag` 吞异常: monkeypatch `physical_delete_tag` raise → `cleanup_case_tag` **不** raise;registry 项**仍在**(未 pop)。
7. `create_case_tag` 不预删(即使同名存在,`delete_tags_physical` 从不调)。
8. `all_active_rows` 分页: fake `list_tags` 返回 2 满页(各500)再空 → 收集 1000。
9. `all_recycle_rows` 分页: fake `list_recycle_tags` 返回 2 页 → 全收集。

**验收命令**:
```
python -m compileall -q ua_test_harness\ua2_ops.py
python -m pytest ua_test_harness\unit_tests\test_ua2_ops.py -q
```

**commit**: `git add ua_test_harness\ua2_ops.py ua_test_harness\unit_tests\test_ua2_ops.py` → `git commit -m "feat(ua2): add thin single-action ops layer for UA-2 cases"`

**验收准则(主 Agent)**:
- [ ] 只新增 2 文件。
- [ ] `create_tag_raw`/`create_case_tag` 无预删;`create_datasource_raw` 无 auto-enable。
- [ ] `cleanup_case_tag` 吞自身异常(且只在它这里允许吞);成功路径 pop 兜底。
- [ ] `active_rows` 把 filters 下推 `data=`;`all_*` 真分页。
- [ ] 9 单测全过;compileall 通过。
- [ ] 回归: `test_ua2_first_batch.py` 仍全过。

---

### G. Case 私有资源 cleanup 工具

**背景**: 现 cleanup 工具前缀 `ua_auto_ua2_`、单页 500(漏残)、默认删数据源、可能误删共享资源。本任务改为只清 `ua_case_ua2_`、分页、默认不删数据源、**绝不**碰 `ua_shared_ua2_*`。

**修改范围**:
- 改(重写): `scripts/cleanup_ua2_resources.py`
- 新增: `ua_test_harness/unit_tests/test_cleanup_ua2.py`
- 禁止改: 任何其它文件。

**先读**:
- `scripts/cleanup_ua2_resources.py`(现有实现,你将重写)。
- `tpt_api/python/tpt_api/datahub.py` 核实: `list_tags`、`list_recycle_tags`(→`{tagInfoList:{records}}`)、`list_ds_info`、`delete_tags_physical`、`change_ds_state`、`delete_ds_info`。
- 注意: 此脚本作为独立进程运行,直接用 `tpt_api.client.AlgAPI` 登录(见现有 `_login`),**不用** ua_test_harness context。测试 monkeypatch `tpt_api.datahub` + `tpt_api.client.AlgAPI`。
- 总 Plan "Task 7" 节(参考代码)。

**实现要求(行为)**:
- 常量: `PREFIX="ua_case_ua2_"`、`CASE_DS_PREFIX="ua_case_ua2_ds_"`、`SHARED_PREFIX="ua_shared_ua2_"`。
- `_login(ctx)` 沿用(AlgAPI + login)。
- `_collect_tag_ids(api,name_prefix)->(active_ids,recycle_ids)`: 活动 `list_tags` page_size=500 **分页循环**+tagName startswith 过滤;回收 `list_recycle_tags` page_size=200 **分页循环**+过滤。不许单页 500 漏。
- `_collect_case_ds_ids(api)->list[int]`: `list_ds_info(data={"dsName":CASE_DS_PREFIX})` 分页循环,dsName/name startswith `CASE_DS_PREFIX`。
- `main()`: 参数 `--base-url`、`--username`、`--prefix`(默认 `PREFIX`)、`--include-case-datasources`(store_true)、`--dry-run`、`--result`(默认 `"-"`)。`args.prefix.startswith(SHARED_PREFIX)` → stderr 报错 return 2。需 `DATAHUB_PASSWORD` env(缺 return 2)。收集 tags + (若 `--include-case-datasources`) case DS。非 dry-run: `delete_tags_physical`(active+recycle 去重排序);若请求 case DS: 逐个 disable 后 `delete_ds_info`。**之后复核**(重新收集);log `residualActive/residualRecycle/residualCaseDatasources`;有 case 私有残留则 exitCode=1 否则 0。JSON 写 `--result`(或 `"-"` stdout)。
- **默认(无 `--include-case-datasources`)不删任何数据源。** 共享 DS 永不被删(shared 前缀守卫 + 只看 `CASE_DS_PREFIX`)。

**必须的单测**(`test_cleanup_ua2.py`,monkeypatch `tpt_api.datahub`+`tpt_api.client.AlgAPI` 使 `_login` 返回 fake;调 `main()` 带 temp `--result`,查 JSON+返回码):
1. 模块 `PREFIX == "ua_case_ua2_"`。
2. `--prefix ua_shared_ua2_` → return 2,无任何 delete 调用。
3. 不删共享资源: fake ds 含 `ua_shared_ua2_types_ds` 一行;运行后 `delete_ds_info` 从未以其 id 调用;它存活。
4. 分页活动位号: fake `list_tags` 返回 3 页(500+500+1)→ 收集全部 1001 id 并 `delete_tags_physical` 传全部。
5. 分页回收: fake `list_recycle_tags` 返回 2 页 → 全部回收 id 收集+删除。
6. 默认不删数据源: 即使有 case DS,`delete_ds_info` 不调(除非 `--include-case-datasources`)。
7. 复核 exit code: 有残留→1;干净→0。

**验收命令**:
```
python -m compileall -q scripts\cleanup_ua2_resources.py
python -m pytest ua_test_harness\unit_tests\test_cleanup_ua2.py -q
python -m pytest ua_test_harness\unit_tests\test_ua2_first_batch.py -q
```

**commit**: `git add scripts\cleanup_ua2_resources.py ua_test_harness\unit_tests\test_cleanup_ua2.py` → `git commit -m "refactor(ua2): cleanup tool scoped to case-private resources, paginated, no shared deletion"`

**验收准则(主 Agent)**:
- [ ] 只改 1 + 新增 1 文件。
- [ ] 默认前缀 `ua_case_ua2_`;`ua_shared_ua2_` 前缀被拒(return 2)。
- [ ] 活动+回收均分页;默认不删数据源;共享 DS 永不删。
- [ ] 复核 exit code 正确。
- [ ] 7 单测全过;`test_ua2_first_batch.py` 回归仍全过;compileall 通过。

---

### D. UA-2-1 创建相关 Runtime 重构

**前置**: B、C 已验收通过,且主 Agent 已完成 BaselineError->BLOCKED 接线(`ua2_runtime.py`)。

**背景**: 4 条创建 case 现在每条 `prepare_datasource` 自建数据源。改为查共享 `types` DS + 显式管理 `ua_case_ua2_` 私有位号。

**修改范围**:
- 改: `ua_test_harness/ua2_create_runtime.py`(重写 4 个 handler + helpers)
- 新增: `ua_test_harness/unit_tests/test_ua2_1_refactor.py`
- 禁止改: `ua2_runtime.py`(主 Agent 已动过接线,你别碰)、`ua2_query_runtime.py`、`ua2_recycle_runtime.py`、`fixtures/`、`ua2_common.py`、`provisioning/`、`ua2_ops.py`。

**先读**:
- `ua_test_harness/ua2_create_runtime.py`(现状)、`ua_test_harness/ua2_ops.py`(C 产出,你将调用)、`ua_test_harness/provisioning/ua2_baseline.py`(B 产出,`require_shared_datasource`)。
- `ua_test_harness/fixtures/environment.py`(`ensure_mock_ready`、`ensure_logged_in`)。
- `ua_test_harness/ua2_common.py`(`_make_length_name` 已有,保持同名同行为旧测试不破)。
- `ua_test_harness/test_cases/UA-2-1.md` 中 017/019/021/022 的产品预期(确认不放宽断言)。
- 总 Plan "Task 4" 节(参考代码)。

**实现要求(行为)**:
- 删除所有 `prepare_datasource` 调用;改用 `require_shared_datasource(ctx, "types")`。
- 每条 case 结构: `ensure_mock_ready`+`ensure_logged_in` -> `require_shared_datasource(ctx,"types")` -> `create_case_tag`(或对边界名 case 用 `create_tag_raw` + 手动登记兜底) -> `try: 产品步骤+断言; return CaseStatus.PASS; finally: cleanup_case_tag(...)`。
- **UA-2-1-017** 重名: 建 case tag -> 断言原始记录存在 -> 再 `add_tag` 同名必须被拒(`try/except` 捕获 rejected=True,这是测试动作不是吞错) -> 断言仅1条且字段未覆盖。
- **UA-2-1-019** 空名: 不建 case tag(空名必被拒);`add_tag(name="")` 必须失败;断言无空名残留;若泄漏 id 则防御性 `physical_delete_tag` 并返回 `FAIL`。
- **UA-2-1-021/022** 长度边界: 用 `_make_length_name` 生成精确 127/128 字节名(前缀 `ua_case_ua2_tag_len127_`);`create_tag_raw` 建边界名 tag + 登记 `tag:{name}` 兜底;接受路径断言字节一致;拒绝路径断言无半截记录;finally `cleanup_case_tag(ctx,cc,b_id,name)`。**不要**先建 case_tag 再删再建的绕路写法。
- case tag 名必须以 `ua_case_ua2_` 开头(由 `create_case_tag`/`case_tag_name` 保证)。
- **不创建、不禁用、不删除数据源。**

**必须的单测**(`test_ua2_1_refactor.py`,monkeypatch `require_shared_datasource`/`create_case_tag`/ops/`active_rows`,跑 handler 全流程):
1. 017: `prepare_datasource` 未调;`require_shared_datasource(ctx,"types")` 调一次;PASS 时 tag 被物理删 + pop;返回 PASS。
2. 017 断言失败保留: fake 重名未被拒 -> handler 抛 `AssertFail`;`cleanup_case_tag` 仍执行(tag 删);registry pop。
3. 019: 空名被拒 -> 返回 PASS;无残留。
4. 021 接受路径: tag 建后清理。
5. 022 拒绝路径: 无泄漏,PASS。
6. 4 个 handler 都不调 `prepare_datasource`(monkeypatch `ua2_common.prepare_datasource` 为 raise,assert 不触发)。

**验收命令**:
```
python -m compileall -q ua_test_harness\ua2_create_runtime.py
python -m pytest ua_test_harness\unit_tests\test_ua2_1_refactor.py -q
python -m pytest ua_test_harness\unit_tests\test_ua2_first_batch.py -q -k "length_name or soft_delete_one_signature or restore_one_signature or supported_ua2"
```

**commit**: `git add ua_test_harness\ua2_create_runtime.py ua_test_harness\unit_tests\test_ua2_1_refactor.py` -> `git commit -m "refactor(ua2): UA-2-1 cases use shared datasource and explicit tag cleanup"`

**验收准则(主 Agent)**:
- [ ] 只改 `ua2_create_runtime.py` + 新增测试;未碰 `ua2_runtime.py`/其它 runtime/ops/provisioning。
- [ ] 4 handler 均不调 `prepare_datasource`;不创建/删除数据源。
- [ ] case tag 用 `ua_case_ua2_` 前缀;finally 显式 `cleanup_case_tag`。
- [ ] 017 的 `try/except` 是测试重名拒绝(非吞错);019 防御性删仅用于泄漏 id。
- [ ] `_make_length_name` 行为不变(旧 length_name 测试仍过)。
- [ ] 新测 + 指定回归全过;compileall 通过。

---

### E. UA-2-2 查询相关 Runtime 重构

**前置**: B、C + 接线。

**背景**: 8 条查询 case 改用共享 DS;把能下推的过滤(dsId/tagName)传给 API;回收站不支持 dsId 则分页本地过滤。**UA-2-2-019 用共享 empty DS,不建位号。**

**修改范围**:
- 改: `ua_test_harness/ua2_query_runtime.py`(重写 8 handler)
- 新增: `ua_test_harness/unit_tests/test_ua2_2_refactor.py`
- 禁止改: 其它 runtime、`ua2_runtime.py`、ops、provisioning、fixtures、`ua2_common.py`。

**先读**: `ua2_query_runtime.py`(现状)、`ua2_ops.py`、`provisioning/ua2_baseline.py`、`UA-2-2.md`(004/005/008/011/015/016/019/033 产品预期)、总 Plan "Task 5" 节。

**实现要求(行为)**:
- 全部 8 个: `prepare_datasource` -> `require_shared_datasource(ctx,"types")`(019 用 `"empty"`)。
- **019**: `require_shared_datasource(ctx,"empty")`;`active_rows(ctx, dsId=ds["id"])`(服务端下推);断言空集;不建位号;删除现有 dead code。
- **004/033、005、011、015**: `create_case_tag` 建私有位号 + finally `cleanup_case_tag`;查询用 `active_rows(ctx, tagName=name)` 下推。
- **011**: broad 查询用 `active_rows(ctx, dsId=ds_id)`(服务端 scope,非全局 fetch-all);两条 tag 各自显式 cleanup(**修复闭包晚绑定**:不要在循环里用共享变量注册 lambda,用 `create_case_tag`/`cleanup_case_tag` 逐个)。
- **008**: 不建位号;`active_rows(ctx, tagName=impossible)` 下推;断言空。
- **016**: 不建位号;`tagBaseName` API 不支持,用 `all_active_rows(ctx)` 分页后本地过滤;断言空。
- 不创建/删除数据源。

**必须的单测**(`test_ua2_2_refactor.py`):
1. 019: `require_shared_datasource(ctx,"empty")` 调;`list_tags` 以 `data={"dsId":..}` 调;不建 tag;返回 PASS。
2. 004: 共享 types DS;case tag 建+清理;返回 PASS。
3. 011 无闭包 bug: 两条 tag 都被清理(都物理删);registry 空。
4. 8 handler 都不调 `prepare_datasource`。
5. 016 用 `all_active_rows`(分页)非单页。

**验收命令**:
```
python -m compileall -q ua_test_harness\ua2_query_runtime.py
python -m pytest ua_test_harness\unit_tests\test_ua2_2_refactor.py -q
python -m pytest ua_test_harness\unit_tests\test_ua2_first_batch.py -q -k query_repeat_stable
```
(`query_repeat_stable` 源码断言要求保留 `first = sample()`/`second = sample()`/`third = sample()` - 重写时保留这三行。)

**commit**: `git add ua_test_harness\ua2_query_runtime.py ua_test_harness\unit_tests\test_ua2_2_refactor.py` -> `git commit -m "refactor(ua2): UA-2-2 query cases use shared datasources and push filters to API"`

**验收准则(主 Agent)**:
- [ ] 只改 `ua2_query_runtime.py` + 新增测试。
- [ ] 8 handler 不调 `prepare_datasource`;不创建/删除 DS;019 用 empty DS。
- [ ] 019/011 把 dsId 下推 API;016 分页;011 无闭包晚绑定。
- [ ] `query_repeat_stable` 保留三采样行(旧源码断言过)。
- [ ] 新测 + 回归全过;compileall 通过。

---

### F. UA-2-4 删除/恢复 Runtime 重构

**前置**: B、C + 接线。

**背景**: 4 条删除恢复 case 改用共享 DS + 显式位号生命周期(软删/恢复/物理删/状态确认)。

**修改范围**:
- 改: `ua_test_harness/ua2_recycle_runtime.py`(重写 4 handler)
- 新增: `ua_test_harness/unit_tests/test_ua2_4_refactor.py`
- 禁止改: 其它 runtime、`ua2_runtime.py`、ops、provisioning、fixtures、`ua2_common.py`。

**先读**: `ua2_recycle_runtime.py`(现状)、`ua2_ops.py`(`soft_delete_tag`/`restore_tag`/`physical_delete_tag`/`all_recycle_rows`/`active_rows`/`exact`)、`UA-2-4.md`(001/013/020/024 产品预期)、总 Plan "Task 6" 节。

**实现要求(行为)**:
- 全部 4 个: `prepare_datasource` -> `require_shared_datasource(ctx,"types")`;`create_case_tag` 建私有位号 + finally `cleanup_case_tag`。
- 用 ops: `soft_delete_tag(ctx,tag_id)`、`restore_tag(ctx,tag_id)`、`physical_delete_tag(ctx,tag_id)`、`all_recycle_rows`、`active_rows`、`exact`。`_wait_until` 可保留为本地轮询。
- **001**: 软删 -> 断言 active 消失 + 回收站出现同 ID;cleanup 物理删(从回收站)。
- **013**: 软删 -> 恢复 -> 断言 active 重现同 ID + 回收站消失;cleanup 删。
- **020**: 软删 -> 物理删(测试动作)-> `cc.registry.pop(f"tag:{name}")` 去掉兜底 -> 断言 active/recycle 均无;cleanup 是安全 no-op。
- **024**: 软删 -> 物理删 -> **真正尝试恢复**(测试动作,`try: restore_tag; except: pass` 此处允许,因测试目标是"恢复不可成功",最终状态断言为权威)-> 断言 active/recycle 均无该 ID;不 silently 放过--断言必须执行。
- 不创建/删除数据源。

**必须的单测**(`test_ua2_4_refactor.py`):
1. 001: 共享 types DS;tag 建后软删;回收站验证;cleanup 物理删;registry 空。
2. 013: 建->软删->恢复->active;cleanup 删。
3. 020: 物理删后 pop registry;finally cleanup 安全 no-op。
4. 024: 恢复尝试被捕获;断言 active/recycle 均 0;FAIL 不被掩盖。
5. 4 handler 都不调 `prepare_datasource`。

**验收命令**:
```
python -m compileall -q ua_test_harness\ua2_recycle_runtime.py
python -m pytest ua_test_harness\unit_tests\test_ua2_4_refactor.py -q
python -m pytest ua_test_harness\unit_tests\test_ua2_first_batch.py -q -k "soft_delete_one_signature or restore_one_signature"
```

**commit**: `git add ua_test_harness\ua2_recycle_runtime.py ua_test_harness\unit_tests\test_ua2_4_refactor.py` -> `git commit -m "refactor(ua2): UA-2-4 delete/restore cases use shared datasource and explicit tag lifecycle"`

**验收准则(主 Agent)**:
- [ ] 只改 `ua2_recycle_runtime.py` + 新增测试。
- [ ] 4 handler 不调 `prepare_datasource`;不创建/删除 DS。
- [ ] 020/024 物理删后 pop 兜底;024 恢复尝试是测试动作且最终断言执行(非吞错放行)。
- [ ] `soft_delete_one`/`restore_one` 签名仍是 `(ctx, cc)`(旧签名测试过)。
- [ ] 新测 + 回归全过;compileall 通过。

---

### H. Baseline teardown + Datasource diagnose

**前置**: B、A。

**背景**: 共享 baseline 需要显式 teardown 脚本(普通 runner 不调);为诊断旧数据源删除失败原因,加只读诊断脚本。

**修改范围**:
- 新增: `scripts/teardown_ua2_baseline.py`、`scripts/diagnose_ua2_datasource.py`
- 新增: `ua_test_harness/unit_tests/test_diagnose_teardown_ua2.py`
- 禁止改: 任何其它文件(尤其 `run_automation_ua2.py`、`cleanup_ua2_resources.py`)。

**先读**: `provisioning/ua2_baseline.py`(`teardown_ua2_baseline`、`SHARED_*_DS_NAME`)、`tpt_api/datahub.py`(`list_tags(data={"dsId":..})`、`list_recycle_tags`、`list_ds_info`、`change_ds_state`、`delete_ds_info`)、总 Plan "Task 8/9" 节。

**实现要求(行为)**:
- `teardown_ua2_baseline.py`: 需 `--confirm-delete-shared`;否则 return 2 不删。confirm 后调 `teardown_ua2_baseline(ctx, confirm=True)`。建 RunContext 从 env(`DATAHUB_*`、`UA_LOCAL_IP`)。
- `diagnose_ua2_datasource.py`: 默认只读。`--ds-id` 或 `--ds-name` 选 DS。输出 JSON: `{datasource:{id,name,enabled,alive,endpoint}, activeTags:[...], recycleTags:[...], activeTagCount, recycleTagCount}`。活动位号按 `list_tags(data={"dsId":id})` 分页(服务端);回收站分页 `list_recycle_tags` 后按 dsId 本地过滤。`--attempt-clean-delete`: 仅允许名以 `ua_case_ua2_` 或 `ua_auto_ua2_` 开头;有活动/回收位号则报 `TAG_DEPENDENCY` 不删;否则 disable->等 alive=false->delete->轮询确认 ID 消失。
- 两个脚本都 `sys.path.insert(0, repo_root)` 以便 import。

**必须的单测**(`test_diagnose_teardown_ua2.py`,monkeypatch `tpt_api.datahub`+provisioning):
1. diagnose 按dsId列活动位号: fake `list_tags(data={"dsId":X})` 返回2条 -> `activeTagCount==2`。
2. diagnose 回收站按dsId过滤: fake 回收(2页)有1条 dsId 匹配 -> `recycleTagCount==1`(其它排除)。
3. diagnose 只读不删: 默认不调 delete/disable。
4. `--attempt-clean-delete` 拒绝非 case 名: `--ds-name ua_shared_ua2_types_ds` -> 非零退出,不删。
5. `--attempt-clean-delete` 有位号拒删: case 名 DS 有活动位号 -> `TAG_DEPENDENCY`,不删。
6. `--attempt-clean-delete` 无位号: case 名 DS -> disable->delete->轮询 gone。
7. teardown 无 `--confirm-delete-shared` -> return 2;有 -> 调 disable+delete 两个共享 DS。

**验收命令**:
```
python -m compileall -q scripts\teardown_ua2_baseline.py scripts\diagnose_ua2_datasource.py
python -m pytest ua_test_harness\unit_tests\test_diagnose_teardown_ua2.py -q
```

**commit**: `git add scripts\teardown_ua2_baseline.py scripts\diagnose_ua2_datasource.py ua_test_harness\unit_tests\test_diagnose_teardown_ua2.py` -> `git commit -m "feat(ua2): add baseline teardown and read-only datasource diagnostic"`

**验收准则(主 Agent)**:
- [ ] 只新增 2 脚本 + 1 测试。
- [ ] diagnose 默认只读;`--attempt-clean-delete` 仅限 case 名、有 tag 拒删。
- [ ] teardown 需 `--confirm-delete-shared`;普通 runner 不调它(由主 Agent 在 I 验收时确认)。
- [ ] 活动按 dsId 服务端查;回收站分页本地过滤。
- [ ] 7 单测全过;compileall 通过。

---

### I. Runner 与状态分类

**前置**: B、A、G。

**背景**: runner 现在只起一个 mock(18965)、每条 case 后清理会删数据源。改为起两个 mock(18965+18967)、provision 共享 baseline、case 间只清 case 私有、批次结束不删共享 DS。

**修改范围**:
- 改: `scripts/run_automation_ua2.py`、`scripts/run_automation_ua2.ps1`(minor)
- 新增: `ua_test_harness/unit_tests/test_runner_ua2.py`
- 禁止改: `cleanup_ua2_resources.py`、`ua2_*.py` runtime、ops、provisioning。

**先读**: `scripts/run_automation_ua2.py`(现状)、`scripts/run_automation_ua2.ps1`、`provisioning/ua2_baseline.py`(`ensure_ua2_baseline`、`BaselineError`)、`scripts/cleanup_ua2_resources.py`(G 产出)、总 Plan "Task 10" 节。

**实现要求(行为)**:
- 新编排顺序: 1.env检查 2.compileall 3.unit tests 4.catalog 5.inventory 6.起 types mock(18965) 7.起 empty mock(18967) 8.等两者 ready 9.`ensure_ua2_baseline` provision/校验共享 baseline(失败->BLOCKED,停 mock,exit 1) 10.逐条跑16 case(每条独立子进程,timeout 不变) 11.每条后只清 `ua_case_ua2_`(调 G 的 cleanup) 12.批次结束**不删共享 DS** 13.停两个 mock 14.报告。
- 把 `_start_mock` 泛化为 `_start_mock_at(yaml_name, port, ...)`,types 用 `ua2_types.yaml`/18965,empty 用 `ua2_empty.yaml`/18967。
- 每条 case 的 run-config JSON 增 `ua2Baseline` 段: `{typesDatasourceName,typesEndpoint,emptyDatasourceName,emptyEndpoint}`;并设子进程 env `UA2_EMPTY_ENDPOINT`。
- summary 增 `baseline`、`emptyMockProcess`。`_cleanup` 用 G 的 case-only 默认前缀;**不调** `teardown_ua2_baseline`。
- `.ps1` 若有死参数可不动;无需结构改动。

**必须的单测**(`test_runner_ua2.py`,monkeypatch subprocess + provisioning + _start_mock_at):
1. 起两个 mock: types(18965) 和 empty(18967) 都被起。
2. provision baseline: `ensure_ua2_baseline` 在 case 前调一次。
3. case run-config 含 `ua2Baseline` 段(两名+两 endpoint)。
4. 不 teardown 共享: 全程不调 `teardown_ua2_baseline`;共享 DS 不删。
5. case 清理用 case 前缀: 每条后 cleanup 以 `--prefix ua_case_ua2_`(默认)调。
6. case 失败也保留共享 DS。

**验收命令**:
```
python -m compileall -q scripts\run_automation_ua2.py
python -m pytest ua_test_harness\unit_tests\test_runner_ua2.py -q
python -m pytest ua_test_harness\unit_tests\test_ua2_first_batch.py -q -k "timeout_runner"
```

**commit**: `git add scripts\run_automation_ua2.py scripts\run_automation_ua2.ps1 ua_test_harness\unit_tests\test_runner_ua2.py` -> `git commit -m "refactor(ua2): runner starts two mocks, provisions baseline, keeps shared DS"`

**验收准则(主 Agent)**:
- [ ] 只改 runner 两文件 + 新增测试。
- [ ] 起两个 mock;provision baseline;case 间只清 case 私有;不删共享 DS;不调 teardown。
- [ ] run-config 含 baseline 段 + env `UA2_EMPTY_ENDPOINT`。
- [ ] timeout 隔离不破(旧 timeout_runner 测试过)。
- [ ] 新测 + 回归全过;compileall 通过。

---

### J. 跨模块回归与 catalog/inventory 完整性(主 Agent 亲自)

**前置**: A-I 全部验收通过。

**主 Agent 负责**:
- 新增 `ua_test_harness/unit_tests/test_ua2_resource_model.py`,覆盖跨模块断言:
  - 16 handler 都不调 `prepare_datasource`(monkeypatch 为 raise)。
  - 16 handler 都不创建数据源(monkeypatch `create_datasource_raw`/`fixtures.datasource.create_datasource` 为 raise)。
  - 16 handler 都不删 `ua_shared_ua2_*` 数据源。
  - 产品 FAIL 不被 cleanup 掩盖(cleanup_case_tag 吞自身异常,case AssertFail 仍传到 runner)。
- 全量验证:
```
python -m compileall -q ua_test_harness scripts tpt_api
python -m pytest ua_test_harness\unit_tests -q
python -m ua_test_harness.cli catalog --output output\ua2-resource-refactor-catalog.json
python -m ua_test_harness.case_inventory --repo-root . --expected-total 419 --strict-structure --output output\ua2-resource-refactor-inventory.json
```
- 确认: catalog total=419、UA-2=265;inventory documented=419/implemented=419/unimplemented=0/malformedRows=0/duplicateDocumentIds=0。

---

### K. 真实环境执行与结果分析(主 Agent 亲自,需环境)

**主 Agent 负责**:
- 需 `DATAHUB_PASSWORD` + 可连环境时跑 `powershell -ExecutionPolicy Bypass -File scripts\run_automation_ua2.ps1`。
- 分析 16 条真实结果;不调参美化。目标: 0 HARNESS ERROR;每条要么进目标产品行为要么明确 BLOCKED;产品异常保留 FAIL;cleanup 独立记录。
- 产出最终验收报告(任务要求的 18 项)。

---

## 附录:主 Agent 接线任务(BaselineError->BLOCKED)

在 B 验收通过后、D/E/F 开始前,主 Agent 亲自改 `ua_test_harness/ua2_runtime.py` 的 `execute_ua2_case`:

```python
def execute_ua2_case(ctx, cc, meta) -> CaseStatus:
    case_id = meta["id"]
    handler = _EXECUTE_UA2.get(case_id)
    if handler is None:
        raise AssertFail(...)
    try:
        ...  # 现有签名反射 + handler 调用
        return handler(**kwargs)
    except BaselineError as exc:
        return CaseStatus.BLOCKED  # 共享DS/环境阻塞,不是 ERROR
```

并 `from ua_test_harness.provisioning import BaselineError`。这是状态分类设计,由主 Agent 做并自验(`test_ua2_first_batch.py` 不受影响)。

