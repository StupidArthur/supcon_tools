# bugs.md — UA-2 真实环境执行发现的 bug(Part 2 K 跑产物)

本文件记录 Part 2 真实环境跑(`output\automation_ua2_20260712_222308\`)中暴露的 bug,以及后续讨论/修复的进展。
非"测试代码 bug"(测试代码 ERROR 修复)不属于此处;此处只记录**产品语义/平台 API bug** 或**测试代码导致产品语义未达预期**的设计缺陷。

---

## 决策(2026-07-12,用户确认)

- **Bug #1 = A**:接受 QTQ 切换。`list_tags` 是"主表全量"端点(含软删记录),不是 active 视图;`query_tags_with_quality(groupId="0")` 是平台自己的 active 视图。测试原本用错端点,切换合理。commit `9e826e6` **已接受**。注:尚未在干净真实跑验证(第三/四轮 baseline 因 TPT-mock 网络不通 BLOCKED,环境问题不绕路),待网络恢复后复跑 UA-2-4-001 确认转 PASS。
- **Bug #2 = A**:产品 bug。平台 `add_tag(tag_name="")` 接受空名并生成 `tagName="2_"` 位号,与 doc "空名必拒" 不符。**保留 UA-2-1-019 为 FAIL**,不改断言,作为产品缺陷上报。
- **019 handler 泄漏(测试代码缺陷,已修)**:`empty_name_rejected` 原 `check_true` 抛 AssertFail 后清理跑不到 -> 泄漏平台偷偷创建的位号。已加 `try/finally` 兜底清理(不改 FAIL 结局,仅止泄漏)。

---

## Bug #1: `tpt_api.datahub.list_tags` 不区分 active/recycle group,会把软删记录也返回

**发现时间**: Part 2 K 跑第二轮(2026-07-12 22:23, 输出 `automation_ua2_20260712_222308`)
**症状**: UA-2-4-001 `soft_delete_one` FAIL(`soft_delete:removed_from_active timeout after 15.0s; last=False`)
**影响**: UA-2-4-001(软删后 active 查询应立即消失)及其类似软删-查-active 模式的所有 case 都会触发

### 平台行为(实测,probe 脚本 `output\diag_qtq.py` 验证)
对共享 DS(`ua_shared_ua2_types_ds`, id=80)创建一条 tag 后,调 `delete_tags (POST /api/tag-info/batchDeleteLogic)`:

| 端点 | URL | t=0.1s | t=29.8s | 软删后能否看到 |
|---|---|---|---|---|
| `list_tags` | `POST /api/tag-info/page` | 1 | 1 | **能(混了软删记录)** |
| `query_tags_with_quality (groupId="0")` | `POST /api/tag-group/queryWithQuality` | 0 | 0 | **不能(只返回 active 视图)** |
| `query_tags_with_quality (groupId="1")` | `POST /api/tag-group/queryWithQuality` | 1 | 1 | 能(回收站视图) |
| `list_recycle_tags` | `POST /api/tag-group/get` (groupId="1") | 1 | 1 | 能(回收站) |

实测表明:`delete_tags (batchDeleteLogic)` 返回 200,但 `list_tags` 端点 30 秒+ 仍能查到这条已软删的记录。`query_tags_with_quality` 才是"按 group 过滤"的正确视图(go group 0 = active, group 1 = recycle)。

### 设计含义
- `list_tags` 是"主表全量"语义,不区分 active/recycle,软删记录仍混在里面。
- 这跟 doc 预期"正常查询消失"不符 — 实际产品行为跟 doc 不一致。
- 这是平台 API 的设计选择/或 bug,不是 ua2 framework 的问题。

### 已落盘
- **修复策略**:用 `query_tags_with_quality(groupId="0")` 取代 `list_tags` 作为"active 视图"查询入口。
- 新 helper 落在 `ua_test_harness/ua2_ops.py`(覆盖 `active_rows` / `all_active_rows` / `find_tag_by_name`)。
- 同步替换 `ua_test_harness/provisioning/ua2_baseline.py` / `scripts/cleanup_ua2_resources.py` / `scripts/diagnose_ua2_datasource.py` 里的直接 `list_tags` 调用。
- 测试同步更新 mock。
- 重跑 UA-2-4-001 验证 PASS。

### 范围
本次替换**仅限 UA-2 自动化路径本次可改的文件**:
- `ua_test_harness/ua2_ops.py`
- `ua_test_harness/ua2_recycle_runtime.py`(通过 `active_rows` 自动修复)
- `ua_test_harness/provisioning/ua2_baseline.py`
- `scripts/cleanup_ua2_resources.py`
- `scripts/diagnose_ua2_datasource.py`
- 对应测试文件

**不在本次范围**(主 Agent 之前划为"禁止改"或 UA-1 legacy):
- `ua_test_harness/ua2_common.py`(UA-1 legacy)
- `ua_test_harness/fixtures/tag.py`(UA-1 legacy)
- `ua_test_harness/scenario_runtime.py`(UA-1 + UA-2 非 precise 共用)
- `ua_test_harness/dataflow_probe.py`(probe 工具)
- `tpt_api/python/test_ds_tag_filter.py`、`tests/test_datahub.py`(tpt_api 内部测试)
- `alg_update/...`、`qt5-version/...`、`data-hub-tool/...`、`ua_tpt_manager/...`(其他项目)

---

## Bug #2: TPT 平台 `add_tag(tag_name="")` 不抛异常,反而创建 `tagName="2_"` 的位号

**发现时间**: Part 2 K 跑第二轮
**症状**: UA-2-1-019 `empty_name_rejected` FAIL(`[empty_name_rejected] not true.`)
**影响**: UA-2-1-019 一条 + 可能影响 doc 预期"空名必拒"的语义理解

### 实测
- handler 调 `_add_tag_by_name(ctx, ds_id, "")`(传 `tag_name=""`)
- 平台返回 id=14154 + `tagName="2_"` `tagBaseName="2_"` 的位号(`tpt_api.datahub.add_tag` docstring 没明确空名校验行为)
- handler 期望 platform 抛异常(把 `failed` 设为 True),实际 `failed=False` → `check_true` 抛 AssertFail → FAIL
- handler 没有 `finally` 块,泄漏的 id=14154 没被清掉(已手工 `delete_tags_physical([14154])` 清理;现在 shared types DS 下 active=0)

### 设计含义
- 平台对空名 `add_tag` 的处理:**接受,生成 `tagName="2_"` 的位号**(可能因为 `tagBaseName="2_"` 默认规则 + 空名 fallback?)
- doc `UA-2-1.md` 期望"空名必拒" — 跟实测不符。
- 这是**产品语义问题**,不是测试代码 bug:
  - 不属于"import 错、NameError、签名错、报告解析错"类框架问题。
  - 不属于"测试代码问题可修范围"(改 handler 加 `finally` 不会让 case 从 FAIL 变 PASS — AssertFail 仍会触发)。
- 后续需主 Agent / 用户决策:
  - 平台是否真的允许空名?若是允许,doc 需更新。
  - 若是平台 bug,需平台修复。
- 顺手记一个 handler 设计缺陷(非阻塞):`empty_name_rejected` 缺 `finally` 块导致 FAIL 路径泄漏位号;017/021/022 都有 `finally cleanup_case_tag(...)` 兜底。019 也可加 `finally: if err_id is not None: physical_delete_tag(ctx, err_id)` 兜底(但只能止泄漏,不会改 FAIL 结局)。

### 状态
**决策 A(产品 bug)**:保留 UA-2-1-019 为 FAIL,不改断言,作为产品缺陷上报。019 handler 泄漏已修(见上方"决策")。

---

## 修订历史
- 2026-07-12 22:40 — Part 2 第二轮跑完,Bug #1 + #2 入册
- 2026-07-12 22:50 — Bug #1 落盘(替换 `list_tags` 为 `query_tags_with_quality`); Bug #2 仅记录