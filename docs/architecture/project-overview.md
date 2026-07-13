# supcon_tools UA 自动化测试 - 项目概览

> 本文是项目的**单一权威文档**,覆盖理念、架构、设计、进度、未完成项。新会话/新成员先读本文,再按需读 `docs/memory.md`(交接)、`docs/talk-main.md`(当前任务)、`docs/overnight-findings.md`(批次发现)。

---

## 1. 理念

### 1.1 Case-first 开发
- 419 条文档 Case(`ua_test_gui/doc/test_cases/*.md`)是唯一需求源;代码实现 Case,不改 Case 文档(除非明确错误并报告)。
- **Case 怎么写就怎么实现**:不删断言、不放宽阈值、不改步骤、不为通过加 `try/except` 吞错。
- **跑通不是目标,真实结果才是**:FAIL(产品不符)= 有效产出;ERROR(框架 bug)= 要修;BLOCKED(环境)= 如实记录不绕路。

### 1.2 状态分类
| 状态 | 含义 | 触发 |
|---|---|---|
| PASS | 文档断言满足 | AssertFail 未抛出 |
| FAIL | 产品行为不符 doc | AssertFail |
| ERROR | 框架/测试代码异常 | 未捕获 Python 异常 |
| BLOCKED | 前置/环境/架构缺口 | BaselineError、known_blocked、setup 失败 |
| OBSERVED | 探索/采样,doc 无硬断言 | 有 API 调用 + ctx.bag,无 check_* |
| CLEANUP_FAILED | 清理失败(独立记录) | cleanup_case_tag 之外的清理异常 |

### 1.3 资源所有权模型
- **共享基础资源**(共享 DS、Mock)= 测试环境,批次 provision 一次,case 复用,不建不删。
- **Case 私有资源**(位号)= case 自己建/删,`try/finally` 显式清理,registry 兜底。
- **命名隔离**:共享 `ua_shared_ua2_` / Case 私有 `ua_case_ua2_` / UA-1 legacy `ua_auto_`。cleanup 默认只清 Case 私有。

### 1.4 工程纪律(AGENTS.md)
- 环境问题说出来不绕路;Case 跑不过不改 Case;不碰子模块 `review3`/`data_factory_server`;不提交 output/密码/token/真实 IP;禁止 `git reset --hard`/`clean -fd`/`checkout .`/`stash`;不 `git add .`。
- commit 由主 Agent 把控;子 Agent 经 `docs/talk-main.md` 派单,不自行 commit。

---

## 2. 架构

### 2.1 调度总线
```
CLI / pytest / runner
  └── catalog.discover() -> @case 注册 (419)
        └── zz_documented_cases.py (400 条文档 Case 自动注册)
              └── scenario_policy.execute_documented_case(ctx, cc, meta)
                    ├── UA-1-* -> ua1_runtime.execute_ua1_case (56 条)
                    ├── UA-2-* -> ua2_runtime.execute_ua2_case (265 条)
                    └── UA-3-* -> ua3_runtime.execute_ua3_case (98 条)
```
- `scenario_policy._SUPPORTED`:从文档 + `ua2_registry` + UA-1/UA-3 文档行动态合并,覆盖全 419。
- `case_fidelity.py`:`STRICT_IMPLEMENTED` / `OBSERVED_ONLY` 集合 -> inventory 三态(IMPLEMENTED / PARTIAL / UNIMPLEMENTED)。
- `known_blocked.py`:明确 BLOCKED 登记(如 UA-1-4 双源、UA-2-2-053 GUI-DEFERRED)。

### 2.2 UA-2 资源模型(核心)
```
批次开头: provisioning.ensure_ua2_baseline() -> provision 共享 DS(types 18965 / empty 18967)
每条 case:
    require_shared_datasource(ctx, "types"|"empty")   # 查回复用,不建不删
    create_case_tag(ctx, cc, ds_id, suffix=...)         # ua_case_ua2_ 前缀 + registry 兜底
    try:
        产品 API 调用 + check_* 断言
        return PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)     # 物理删 + 确认 + pop
    BaselineError -> BLOCKED
每条后: cleanup_ua2_resources.py (只清 ua_case_ua2_,不碰共享)
批次末: 不删共享 DS
```

### 2.3 UA-1 资源模型(legacy,不迁)
- 每条独立 `ua_auto_ua1_*` DS(functional mock 18960);`ua1_runtime._prepare` + `ua1_precise.py` 精确场景。
- 不迁共享 baseline(需用户决策)。

### 2.4 UA-3 资源模型
- `ua3_runtime` 六章 dispatcher -> `ua3_precise.py`(回归闭环)+ `ua3_extra.py`(探索/性能)。
- 复用 UA-2 共享 types DS(18965)做采集/写入/历史。
- `scenario_runtime` 已删(死代码,UA-3 统一走 ua3_runtime)。

### 2.5 薄操作层 ua2_ops.py
- 单动作函数,无隐式预删/auto-enable/auto-cleanup。
- `create_case_tag` / `cleanup_case_tag` / `active_rows`(QTQ groupId=0)/ `all_active_rows` / `all_recycle_rows` / `physical_delete_tag` / `soft_delete_tag` / `restore_tag`。

### 2.6 Provisioning
- `ensure_ua2_baseline(ctx)`:创建/校验共享 DS;`BaselineError -> BLOCKED`(接线在 `ua2_runtime.execute_ua2_case`)。
- alive-wait 业务级专用 `BASELINE_ALIVE_WAIT_SEC=120`(与 `ds_connect_sec` 解耦)。
- `require_shared_datasource(ctx, "types"/"empty")`:按名查 + 校验 endpoint/alive;不建删。
- `teardown_ua2_baseline(ctx, confirm=True)`:显式删共享 DS(需 `--confirm-delete-shared`)。

### 2.7 Runner
- `scripts/run_automation_ua2.py` 支持 `--chapter UA-2-1` / `--cases` / `--limit` / `--skip-prereqs` / `--chapter-timeout-sec`。
- UA-2: 起 types(18965)+empty(18967)mock -> provision baseline -> 逐条子进程 -> case-only cleanup -> 不删共享 DS。
- UA-1: 自动切 18960 functional mock + 跳 baseline + `ua_auto_` cleanup 前缀。
- 只跑 STRICT_IMPLEMENTED(跳 PARTIAL 探索 + 已 VERIFIED)。

### 2.8 凭据
- `env.json`(gitignored):`baseUrl`/`username`/`password`/`tenantId`/`localIp`。
- `ua_test_harness/env_config.py`:`load_env_json()` 读 repo_root/env.json。
- 不用环境变量(用户要求)。

### 2.9 测试基础设施
- `cleanup_ua2_resources.py`:只清 `ua_case_ua2_` 前缀,分页,不删共享,默认不删 DS。
- `teardown_ua2_baseline.py`:显式删共享 DS(`--confirm-delete-shared`)。
- `diagnose_ua2_datasource.py`:只读诊断 DS 状态 + active/recycle tags。
- Mock:`ua2_types.yaml`(18965,13 类型×2模式)、`ua2_empty.yaml`(18967,空)、`smoke.yaml`(18960,functional)。

---

## 3. 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 共享 DS vs 每条建 DS | 共享 baseline + case 私有位号 | 消除 endpoint 冲突("currently in use");DS 是环境不是 case 资源 |
| active 视图查询 | `query_tags_with_quality(groupId=0)` | `list_tags` 含软删记录(Bug#1);QTQ 是平台自己的 active 视图 |
| alive-wait 超时 | 120s 业务级专用(非通用 config) | 停过又起的 DS 恢复需 1-2 分钟;与 UA-1 的 ds_connect_sec 解耦 |
| UA-3 路由 | `ua3_runtime` 章节 dispatcher | 与 UA-1/UA-2 一致;`scenario_runtime` 成死代码已删 |
| inventory 状态 | 三态 IMPLEMENTED/PARTIAL/UNIMPLEMENTED | "419 implemented" 虚高;探索类应有 PARTIAL |
| 空 case 名(Bug#2) | 保留 FAIL(产品 bug) | 平台接受空名=产品缺陷,不改断言 |
| env.json vs 环境变量 | env.json | 被测系统账密不重要,直接写文件;不用环境变量 |
| commit 权限 | 主 Agent 把控 | 子 Agent 不 commit;主 Agent 验收后 commit |

---

## 4. 进度(2026-07-13)

### 4.1 总量
| 维度 | 数值 |
|---|---|
| 文档登记 | 419 |
| 严格 IMPLEMENTED(有真实断言) | 304(72.55%) |
| PARTIAL(探索,doc 无硬断言) | 115(正确终态) |
| UNIMPLEMENTED | 0 |
| VERIFIED(真跑通过) | **~203** |
| VERIFIED_FAIL(产品 bug 保留) | **~61** |
| VERIFIED_BLOCKED | ~12 |
| 单测 | 190 passed(+1 已知 GBK) |

### 4.2 各章验证状态
| 章 | 总数 | STRICT | VERIFIED | FAIL | BLOCKED | PARTIAL(未跑) |
|---|---|---|---|---|---|---|
| UA-1-1 | 12 | 5 | 9 | 0 | 0 | 3 |
| UA-1-2 | 8 | 5 | 0 | 6 | 0 | 3 |
| UA-1-3 | 8 | 8 | 0 | 8 | 0 | 0 |
| UA-1-4 | 6 | 6 | 0 | 0 | 6 | 0 |
| UA-1-5 | 9 | 2 | 2 | 0 | 0 | 7 |
| UA-1-6 | 13 | 12 | 3 | 2 | 0 | 1 |
| UA-2-1 | 112 | 88 | ~61 | ~23 | 1 | 24 |
| UA-2-2 | 67 | 55 | ~51 | 4 | 2 | 12 |
| UA-2-3 | 32 | 25 | 19 | 5 | 1 | 7 |
| UA-2-4 | 27 | 15 | 13 | 2 | 0 | 12 |
| UA-2-5 | 27 | 18 | 17 | 0 | 0 | 9 |
| UA-3-1 | 20 | 14 | 6 | 8 | 1 | 6 |
| UA-3-2 | 21 | 15 | 5 | 8 | 3 | 6 |
| UA-3-3 | 22 | 16 | 11 | 1 | 4 | 6 |
| UA-3-4 | 8 | 7 | 2 | 0 | 5 | 1 |
| UA-3-5 | 12 | 0 | 0 | 0 | 0 | 12(探索) |
| UA-3-6 | 15 | 0 | 0 | 0 | 0 | 15(探索) |
| **合计** | **419** | **304** | **~203** | **~61** | **~12** | **115** |

### 4.3 从接手到现在
- **接手时**:38 真实实现;UA-2 第一批 0/16 全 FAIL(endpoint 冲突);"419 implemented" 虚高。
- **现在**:304 严格 IMPLEMENTED;全部 304 条真跑完毕;~203 VERIFIED;~61 产品 FAIL 保留;115 探索 PARTIAL 正确终态;资源模型重构 + 全章真跑完成。

---

## 5. 未完成项

### 5.1 剩余 FAIL 分类(~61 条)

#### A. 产品 bug(doc 对、测试对、产品不符)-- ~23 条,交产品团队
| 聚类 | 条数 | 现象 |
|---|---|---|
| `opcua_matches_rt2` | 9 | OPC UA 源端值 ≠ RT 读回 |
| `by_id_hit` | 2 | 按 ID 查 RT 不返回,按名可以 |
| `tagTime_parseable` | 1 | tagTime 格式不可解析 |
| `has_quality` | 1 | quality 字段无效 |
| `rt_matches_write` | 1 | 写值不匹配 RT |
| `getRTValue timeout`(绑节点+等60s) | 9 | mock 在提供数据但产品不采集 |

#### B. Mock/测试基础设施问题(mock 模拟不了)-- ~20 条,子 Agent 可修
| 聚类 | 条数 | 现象 | 修法 |
|---|---|---|---|
| `rt_changed`(UA-1-2/3) | 14 | smoke.yaml change 节点应自变但 RT 不变 | 先诊断 mock 是否真在变;不变=修 smoke.yaml;变但 TPT 不采集=转 A 类 |
| `BadNodeIdUnknown`(UA-1-6) | 4 | smoke.yaml 没有测试引用的节点 | smoke.yaml 补节点或测试改引用 |
| `value_stable` | 2 | mock 节点值与预期不符 | 对齐 mock 默认值 |

#### C. 可能的 doc/case 问题(doc 预期可能有误)-- ~5 条,需用户判断
| 聚类 | 条数 | 判断点 |
|---|---|---|
| `no_dup_bases` expected=520 | 1 | doc 说 520 是否错?测试只建 26 个 |
| 静态节点 RT timeout | ~4 | doc 对 mock 能力预期是否现实? |

### 5.2 其他剩余
| 项 | 条数 | 说明 |
|---|---|---|
| UA-1-4 双源 BLOCKED | 6 | 需 18965+18967,UA-1 runner 仅 18960(known_blocked) |
| UA-3-4 历史造数 BLOCKED | 5 | verify_history 未达 min_count(产品/环境) |
| 115 探索 PARTIAL | 115 | doc 无硬断言,正确终态(NOT_VERIFIED),不转 |
| inventory overlay 未集成 CLI | - | verified 在 docs/case-inventory.json,CLI 显示 0 |
| TPT DS 重连问题 | - | mock 停后 DS 不恢复(teardown+fresh workaround) |

### 5.3 下一步优先级
1. **B 类 mock 问题**:子 Agent 修 smoke.yaml(mock change / 补节点 / 对齐值)。先诊断 UA-1-2/3 的 `rt_changed`:mock change 节点是否真在变?
2. **C 类 doc 判断**:用户定 `no_dup_bases` 520 是否 doc 错;静态节点 RT 预期是否现实。
3. **A 类产品 bug**:~23 条附现象+证据交产品团队。
4. **其他**:UA-1-4 双源(runner 扩展或保留 BLOCKED);overlay 集成 CLI。

---

## 6. 关键文件地图

| 类别 | 文件 |
|---|---|
| 项目概览 | **本文** (`docs/architecture/project-overview.md`) |
| 交接 | `docs/memory.md` |
| 任务派单 | `docs/talk-main.md` |
| 批次发现 | `docs/overnight-findings.md` |
| Bug 决策 | `bugs.md` |
| 架构手册 | `docs/compose/guidance/ua2-refactor-guide.md` |
| 路线图 | `.mimocode/plans/1783855834448-mighty-nebula.md` |
| Case 规格 | `ua_test_gui/doc/test_cases/UA-*.md`(不改) |
| 调度/缺口 | `scenario_policy.py` / `case_fidelity.py` / `known_blocked.py` |
| UA-2 runtime | `ua2_create/query/recycle/import/group_runtime.py` / `ua2_precise.py` / `ua2_ops.py` |
| UA-1 runtime | `ua1_runtime.py` / `ua1_precise.py` |
| UA-3 runtime | `ua3_runtime.py` / `ua3_precise.py` / `ua3_extra.py` |
| Provisioning | `provisioning/ua2_baseline.py` |
| Runner | `scripts/run_automation_ua2.py` / `cleanup_ua2_resources.py` / `teardown_ua2_baseline.py` / `diagnose_ua2_datasource.py` |
| tpt_api | `tpt_api/python/tpt_api/datahub.py`(真实签名) |
| Mock | `ua_mocker/ua2_types.yaml`(18965) / `ua2_empty.yaml`(18967) / `smoke.yaml`(18960) |
| 凭据 | `env.json`(gitignored) / `env.json.example` |
| 工程纪律 | `AGENTS.md` |

---

## 7. gotchas

- `list_tags` 含软删 -> 用 `query_tags_with_quality(groupId=0)`。
- 共享 DS 停过又起恢复 alive 慢/卡死 -> teardown+fresh provision。
- `test_e2e_smoke::test_run_cli_dry_run` Windows GBK 失败(非回归,不修)。
- 子 Agent 经 talk-main.md 派单,不用主 Agent actor 工具;commit 主 Agent 把控。
- UA-1 用 functional mock(18960),不走共享 baseline。
- inventory CLI 不显示 verified(overlay 在 docs/case-inventory.json)。
- `ua2_empty.yaml` 的 `nodes: []`(空 DS 用)。

---
**最后更新**:2026-07-13。**维护者**:主 Agent(MiMoCode)。
