# memory.md - UA-2 资源重构 & 419 全量开发 完整交接(2026-07-13 更新)

> 新会话第一份必读。记录项目全貌、已完成里程碑、剩余问题分类、下一步。读完再读 `docs/talk-main.md`、`docs/overnight-findings.md`、`bugs.md`。

---

## 0. 一句话现状

UA-2 资源模型重构完成;419 全量挂接 + 304 严格 IMPLEMENTED;全部 304 条已真跑(~203 VERIFIED / ~61 FAIL / ~12 BLOCKED);剩余 ~61 FAIL 分三类(产品 bug / mock 不足 / doc 可能错),115 探索 PARTIAL 是正确终态。

---

## 1. 里程碑(已完成)

| 维度 | 数值 |
|---|---|
| 文档登记 | 419 |
| 严格 IMPLEMENTED(有真实断言) | 304(72.55%) |
| PARTIAL(探索,doc 无硬断言) | 115(正确终态,NOT_VERIFIED) |
| UNIMPLEMENTED | 0 |
| VERIFIED(真跑通过) | **~203** |
| VERIFIED_FAIL(产品 bug 保留) | **~61** |
| VERIFIED_BLOCKED | ~12 |
| 单测 | 190 passed(+1 已知 GBK 环境失败) |
| catalog | 419 cases / 17 chapters |
| inventory | documented=419 / implemented=304 / partial=115 / structureOk |

**从接手时**(38 真实实现 / UA-2 0/16 全 FAIL endpoint 冲突)**到现在**(304 严格 / ~203 VERIFIED / 资源模型重构 + 全章真跑)。

## 2. 架构(已落地,实现 case 时复用)

- **共享 DS**:`ua_shared_ua2_types_ds`(mock 18965)/ `ua_shared_ua2_empty_ds`(mock 18967);`require_shared_datasource(ctx,"types"/"empty")` 按名查回复用,不建不删。
- **case 私有位号**:`ua_case_ua2_` 前缀;`create_case_tag`+`cleanup_case_tag`(try/finally,registry 兜底)。
- **薄操作层** `ua2_ops.py`;**provisioning** `provisioning/ua2_baseline.py`(`BaselineError->BLOCKED`)。
- **active 视图**:用 `query_tags_with_quality(groupId="0")`(不用 `list_tags`,含软删记录 Bug#1)。
- **alive-wait**:provisioning 业务级专用 `BASELINE_ALIVE_WAIT_SEC=120`。
- **env.json** 凭据(不用环境变量);`case_fidelity.py` 三态(STRICT/PARTIAL/UNIMPLEMENTED)。
- **UA-3** 走 `ua3_runtime`(非 scenario_runtime,已删死代码)。
- **UA-1** 走 `ua1_runtime`(每条独立 DS,functional mock 18960,不迁共享 baseline)。
- **runner** `run_automation_ua2.py` 支持 `--chapter/--cases/--limit/--skip-prereqs/--chapter-timeout-sec`;UA-1 自动切 18960 mock。

## 3. Bug 决策(已定)

- **Bug #1=A**(`9e826e6`):`list_tags` 含软删记录 -> 改用 `query_tags_with_quality(groupId=0)`。已验证。
- **Bug #2=A**(`04e4628`):平台接受空名(产品 bug) -> UA-2-1-019 保留 FAIL。
- **019 泄漏**(`04e4628`):handler 加 finally 兜底。
- **alive-wait**(`e7ada0e`):60s->120s 业务级。
- **TPT DS 重连问题**:mock 停后 DS enabled+not-alive 不恢复(teardown+fresh provision 是 workaround,已登记 findings)。

## 4. 剩余问题分类(~61 FAIL)

### A. 产品 bug(doc 对、测试对、产品不符)-- ~23 条,交产品团队

| 聚类 | 条数 | 代表 case | 现象 |
|---|---|---|---|
| `opcua_matches_rt2` | 9 | UA-2-1-001/004/006 等 | OPC UA 源端值 ≠ RT 读回 |
| `by_id_hit` | 2 | UA-3-2-002/013 | 按 ID 查 RT 不返回,按名可以 |
| `tagTime_parseable` | 1 | UA-2-2-039 | tagTime 格式不可解析 |
| `has_quality` | 1 | UA-3-2-012 | quality 字段无效 |
| `rt_matches_write` | 1 | UA-3-3-003 | 写值不匹配 RT |
| `getRTValue timeout`(绑节点+等60s) | 9 | UA-2-3-008/021/028, UA-3-1/2 | mock 在提供数据但产品不采集 |

### B. Mock/测试基础设施问题(doc 对、测试对、mock 模拟不了)-- ~20 条,子 Agent 可修

| 聚类 | 条数 | 代表 case | 现象 | 修法 |
|---|---|---|---|---|
| `rt_changed`(UA-1-2/3) | 14 | UA-1-2-01~03/06~08, UA-1-3-01~08 | smoke.yaml `change=true` 节点应自变但 RT 不变 | **先确认 mock change 节点是否真的在变**:若不变=mock bug 修 smoke.yaml;若变但 TPT 不采集=转 A 类产品 bug |
| `BadNodeIdUnknown`(UA-1-6) | 4 | UA-1-6-02/04/07/10 | smoke.yaml 没有测试引用的节点 | **smoke.yaml 补节点** 或测试改引用已有节点 |
| `value_stable` 5.0 vs 9.0 | 2 | UA-2-2-040, UA-3-1-003 | mock 节点值与测试预期不符 | **对齐 mock 默认值与测试预期** |

### C. 可能的 doc/case 问题(doc 预期本身可能有误)-- ~5 条,需用户判断

| 聚类 | 条数 | 代表 case | 现象 | 判断点 |
|---|---|---|---|---|
| `no_dup_bases` expected=520 actual=26 | 1 | UA-2-2-055 | 520 从哪来?测试只建 26 个 | **doc 说 520 是否错?** 若错改 doc+调整预期 |
| 部分 `getRTValue timeout`(静态节点) | ~4 | UA-3-1/2 部分 | doc 预期 RT 有值,但 tag 绑的 mock 节点不提供数据流 | **doc 对 mock 能力预期是否现实?** 若不现实改 doc 或换动态节点 |

### 其他剩余

| 类别 | 条数 | 说明 |
|---|---|---|
| UA-1-4 双源 BLOCKED | 6 | 需 18965+18967,UA-1 runner 仅 18960(架构缺口,registered in known_blocked) |
| UA-3-4 历史造数 BLOCKED | 5 | `verify_history` 未达 min_count(产品/环境) |
| 115 PARTIAL 探索 | 115 | doc 无硬断言,正确终态(NOT_VERIFIED),不转 |

## 5. commit 链(本会话,基于接手时 `9fb5685`)

```
b0df8ee fix(ua): UA-1 DS name prefix fix (21 test-code FAIL eliminated)
823fd53 feat(ua): UA-1 chapter run + runner UA-1 mode (18960 functional mock)
3c87951 fix(ua): UA-3 triage - import/writeTagValues/node-binding fixes
8e48c9c feat(ua): UA-3-1~4 chapter runs - 22 VERIFIED + 17 product FAIL
fa61f7b feat(ua): UA-2-5 chapter run - 17 VERIFIED, 0 FAIL (cleanest)
de63f46 fix(ua): UA-2-3 RT timeout triage - bind tags to mock nodes
c2bb083 feat(ua): UA-2-4 chapter run - 8 VERIFIED + 2 FAIL
c34520c feat(ua): UA-2-2 chapter run - 39 VERIFIED + 4 FAIL
036812e fix(ua): registry.pop 2-arg bug + UA-2-3 chapter run
0e0cb97 fix(ua): restore_original BadTypeMismatch - opcua type coercion
6f348c2 fix(ua): UA-2-1 FAIL triage - onlyRead/quality/write/import
a3a234f feat(ua): task E UA-2-1 real-run - 34 VERIFIED + 48 FAIL
6f4b9d6 feat(ua): parameterize run_automation_ua2 for batch real-run
6ecfa45 feat(ua): tasks B+D+E - scale audit, report fix, VERIFIED 15/1
2ba0732 feat(ua): task A batch3 + task C - UA-2-1 exploration + merge legacy
7afa154 feat(ua): task A batch2 + task F - 11 assertions + delete dead code
0c14426 feat(ua): task A batch1 - 24 OBSERVED->real assertions
b33256b feat(ua): inventory PARTIAL status + case_fidelity registry
1c11987 feat(ua): overnight 419 case dispatch + chapter handlers (save-point)
... (earlier: e7ada0e alive-wait, 04e4628 bug decisions, 9e826e6 QTQ, etc.)
```

## 6. 下一步(新会话)

### 优先级 1:修 B 类 mock 问题(子 Agent 可做)
- **UA-1-2/3 `rt_changed`**(14 条):先诊断 smoke.yaml `change=true` 节点是否真的在变值(用 asyncua 直接读节点);若不变 -> 修 smoke.yaml/mock change 逻辑;若变但 TPT 不采集 -> 转 A 类产品 bug。
- **UA-1-6 `BadNodeIdUnknown`**(4 条):smoke.yaml 补测试引用的节点,或测试改引用已有节点。
- **`value_stable`**(2 条):对齐 mock 默认值与测试预期。

### 优先级 2:C 类 doc 判断(用户决策)
- `no_dup_bases` 520:doc 是否错?
- 静态节点 RT 预期:doc 对 mock 能力预期是否现实?

### 优先级 3:A 类产品 bug 交产品团队
- ~23 条附现象+证据上报。

### 优先级 4:其他
- UA-1-4 双源(6 BLOCKED):runner 为 UA-1-4 额外 provision 18965/18967,或标 BLOCKED 保留。
- UA-3-4 历史造数(5 BLOCKED):产品/环境排查。
- 115 探索 PARTIAL:正确终态,不动。
- overlay 集成进 CLI inventory(目前 verified 在 docs/case-inventory.json,CLI 显示 0)。

## 7. 关键文件地图

- **交接文档**:本文件 + `docs/talk-main.md`(任务派单) + `docs/overnight-findings.md`(批次发现/FAIL triage) + `bugs.md`(Bug#1/#2 决策)。
- **架构**: `docs/compose/guidance/ua2-refactor-guide.md` + `.mimocode/plans/1783855834448-mighty-nebula.md`。
- **case 规格**: `ua_test_gui/doc/test_cases/UA-*.md`(不改)。
- **调度/缺口**: `scenario_policy.py` + `case_fidelity.py` + `known_blocked.py`。
- **runtime**: `ua1_runtime.py`/`ua1_precise.py`、`ua2_*_runtime.py`/`ua2_precise.py`/`ua2_ops.py`、`ua3_runtime.py`/`ua3_precise.py`/`ua3_extra.py`。
- **provisioning**: `provisioning/ua2_baseline.py`。
- **runner**: `scripts/run_automation_ua2.py`(支持 --chapter)、`cleanup_ua2_resources.py`、`teardown_ua2_baseline.py`、`diagnose_ua2_datasource.py`。
- **tpt_api**: `tpt_api/python/tpt_api/datahub.py`(真实签名)。
- **env.json**: 本地凭据(gitignored),`env.json.example` 模板。
- **mock**: `ua_mocker/ua2_types.yaml`(18965)、`ua2_empty.yaml`(18967)、`smoke.yaml`(18960 functional)。
- **工程纪律**: `AGENTS.md`。
- **子 Agent 协作**: 经 `docs/talk-main.md` 派单,主 Agent 验收+commit,非测试代码问题问用户。

## 8. gotchas

- `list_tags` 含软删 -> 用 `query_tags_with_quality(groupId=0)`。
- 共享 DS 停过又起恢复 alive 慢(1-2 分钟)或卡死(teardown+fresh provision workaround)。
- `test_e2e_smoke::test_run_cli_dry_run` Windows GBK 失败(非回归,不修)。
- 子 Agent 经 talk-main.md 派单,不用主 Agent actor 工具(贵)。
- commit 由主 Agent 把控,子 Agent 不 commit。
- UA-1 用 functional mock(18960),不走共享 baseline。
- inventory CLI 不显示 verified(overlay 在 docs/case-inventory.json,未集成进 CLI)。

---
**更新时间**:2026-07-13 下午。**生成者**:主 Agent(MiMoCode)。全部 304 严格 IMPLEMENTED case 已真跑完毕。
