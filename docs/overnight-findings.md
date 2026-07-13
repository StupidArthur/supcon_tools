# overnight-findings.md

通宵开发过程中的产品发现、缺口与环境阻塞记录。

## 批次 1 — UA-2-2 查询第二批 (2026-07-13 00:xx)

**范围**: UA-2-2-001 / 003 / 006 / 012 / 014 / 017 / 018 / 026 / 030 / 034

**实现选择(测试代码,非产品语义)**:
- UA-2-2-001 同时调用 `tag-info/page` 与 `queryWithQuality(groupId=0)` 核对分页与 ID 唯一性。
- UA-2-2-003 / 014 / 018 / 030 用共享 `types`(18965) 与 `empty`(18967) 双数据源代替文档中的 A/B 双 mock,语义等价(按 dsId 隔离)。
- UA-2-2-012 / 014 对 `tagBaseName` 在 QTQ 模糊匹配后做精确后过滤(与现有 015/016 模式一致)。

**产品 FAIL**: (本批仅单测,未真跑)

**BLOCKED 缺口**: 无(本批 10 条均仅需现有 `active_rows` + 共享 baseline)

---

## 批次 2~4 — 全量挂接 (2026-07-13)

**架构**:
- `ua2_runtime.py` 按章节 dispatcher 路由全部 265 条 UA-2
- `scenario_policy._SUPPORTED` 动态加载 UA-1/UA-2/UA-3 全部 419 ID
- UA-3 通过 `classify_case` 标题关键词映射 scenario_runtime 场景

**BLOCKED / OBSERVED 策略**:
- 缺夹具的回归 case → `BLOCKED` + `ctx.bag` 原因
- 探索 case → `OBSERVED` + 实测记录
- 不允许空函数 PASS

**待用户决策**:
- UA-2-1-004~007 是否允许 case 私有 DS 测数据源状态
- UA-1-4 双 mock 夹具方案

---

## 批次 5 — UA-2-1 精确实现 (2026-07-13)

**范围**: `ua2_precise.py` 公共读取/写入闭环 + UA-2-1 dispatcher 升级

**已完成**:
- `public_create_read_loop` / `public_create_read_no_collect` — tag-info/page + RT + QTQ + asyncua
- `public_write_closed_loop` / `write_value_closed_loop` — 写入 + RT + QTQ + asyncua + 恢复原值
- `precise_mock_offline_create` / `precise_mock_recovery` — UA-2-1-004/005
- `precise_ds_disabled_create` / `precise_ds_reenable_collect` — UA-2-1-006/007
- `CASE_WRITE_VALUES` 覆盖 UA-2-1-039~074 全部回归写入 case(22 条)
- `precise_write_explore` — 探索类写入记录 probe 到 `ctx.bag`
- 修复 `dispatch_ua2_1` 批量 case 路由死代码(105~112 不可达)

**实现选择(测试代码)**:
- 004~007 在共享 types DS 上用 mock 停启 / DS 禁用启用,单 case 隔离可接受
- 探索写入(041/043/…/075) 返回 OBSERVED,证据落 `ctx.bag[case_id].probe_writes`

**精确实现进度(UA-2-1)**:
- 读取闭环 026~038 + 001/002/008: **精确**
- 可用性 004~007/009/013: **精确**
- 写入回归 039~074(除 073 拒绝路径): **精确**
- 探索/批量/字段/频率等余量: 部分 OBSERVED 或简化断言

**BLOCKED 保持**:
- UA-2-1-010: 双 mock 同节点

---

## 批次 6 — UA-2-1 余量 + browse + UA-2-4 (2026-07-13)

**新增模块**:
- `ua2_browse.py` — getNotUsed 游标分页 + tagBaseName 二次过滤 + batchAdd 映射

**UA-2-1 精确化(076~112)**:
- 单位/描述 076~081 → `precise_field_unit_desc`
- onlyRead 082~085 → `precise_only_read`(083 完整写入闭环)
- 频率 086~090 → `precise_frequency`(086 回归,087~090 OBSERVED+采样)
- 量程/报警 091~097 → `precise_limits`
- needPush 098~101 → `precise_need_push`
- 可用性 102~104 → `precise_availability`(104 历史落库)
- 批量 105~112 → `precise_batch`(105 browse 10 节点,106/107 冲突策略)

**UA-2-2 browse(041~047)**:
- 解除 BLOCKED,实现 browse 执行器 + 双 DS 隔离/断线/恢复

**UA-2-4 精确化**:
- 005~008 软删探索(真实 API + ctx.bag)
- 014~017 批量恢复/配置保持/RT 闭环/返回 false 判定

**单测**: 160 passed(+3 browse)

---

## 批次 7 — UA-2-2 余量 + UA-2-3/5 精确化 (2026-07-13)

**UA-2-2** (`ua2_query_extra.py`):
- 007/009/010/013 名称探索(真实 query API)
- 021~025 分组/收藏/回收站查询(解除 BLOCKED)
- 037/038/040 mock 断线/恢复/静态质量
- 048 browse→batchAdd→RT
- 049~052/054 分页与排序; 055 browse 游标完整性
- 056~064 结果更新(新增/重命名/软删/物理删/收藏)
- 065~067 稳定性与只读隔离
- 053 保持 GUI-DEFERRED BLOCKED

**UA-2-3** (`ua2_import_helpers.py` + 重写 `ua2_import_runtime.py`):
- 001~006 导出与 21 列表头
- 007~012/018/022~027 探索(OBSERVED + 证据)
- 013~021/028 导入/冲突/往返
- 029~032 browse+batchAdd(100 条受未注册节点数限制,不足时 OBSERVED)

**UA-2-5** (重写 `ua2_group_runtime.py`):
- 001~005/009~011/014~016/018/022 分组树 CRUD 回归
- 006~008/012/013/017/019~021/025 探索
- 023~027 收藏/取消收藏(含 false 返回判定)

**单测**: 161 passed

---

## 批次 8 — UA-2-4 余量 + UA-3 精确 dispatcher (2026-07-13)

**UA-2-4** (`ua2_recycle_runtime.py`):
- 002 批量软删改为 10 条(doc 对齐)
- 003 双 DS 回收断言(types + empty)
- 010 asyncua 软删前后源端不变
- 011/012 软删后历史探索(OBSERVED/BLOCKED setup_failed)
- 018/019 恢复幂等与混合 ID 探索
- 021 批量物理删除 10 条回归
- 022/023/025 物理删重复/混合/软删后重建探索

**UA-3** (新建 `ua3_precise.py` + `ua3_runtime.py`):
- 98 条全部挂接章节 dispatcher(不再走 scenario_runtime 场景代理)
- `scenario_policy.execute_documented_case` UA-3 改走 `execute_ua3_case`
- UA-3-1~2 采集/RT 回归 + 断线/双源/13 类型
- UA-3-3 写入单/批/只读/混合
- UA-3-4 历史方式 B 双接口
- UA-3-5/6 延迟与并发基线(OBSERVED)

**单测**: 163 passed (+2 ua3_runtime)

---

## 批次 9 — UA-3 探索补全 + UA-1 余量 (2026-07-13, 开发中未跑)

**UA-3** (`ua3_extra.py`):
- 补全 UA-3-1/2/3/4/5/6 原 `_observed` 占位 → 真实 API + ctx.bag
- 含多 frequency、queryTime、批量 100 RT/写、历史/混合负载等

**UA-1** (`ua1_precise.py`):
- UA-1-3-01~08 断线/重连时序
- UA-1-4-01~06 双共享 DS 隔离(types + empty)
- UA-1-6-01~13 ds-info/test 五类 testType
- UA-1-2-03~05 历史停增/恢复探索

**纪律**: 全部开发完成前不跑 pytest / 真环境 case

---

## 批次 10 — UA-1-1/5 补全 + UA-2-1 探索 + UA-3-6-008 (2026-07-13, 未跑)

**UA-1-1** (`ua1_precise.connection_case`):
- 03 URL 双格式（无 path / 有 path）双 DS 回归
- 05 不可达→可达 OBSERVED（18969 mock 未自动起）
- 06~11 鉴权/好值质量码：真实 `dsExtInfo` + RT 证据

**UA-1-5** (`ua1_precise.delete_matrix_case`):
- 02~06/08/09 删除矩阵、回收站、双源隔离、删后 RT

**UA-2-1**:
- 015/020/023/024/025 名称/类型探索（替代 deferred 占位）

**UA-3**:
- 6-008 同位号并发写竞争
- 5-012 冷/热请求延迟

---

## 批次 11 — UA-2-1-010 + UA-3 收尾 (2026-07-13, 未跑)

**UA-2-1-010**: `precise_cross_ds_same_node` — types + empty 同底层节点不串值（解除 BLOCKED）

**UA-3-3-021**: 断线/禁用时写入探索

**UA-3-5-009/010**: 历史分页延迟基线

**UA-3-6-015**: 短时过载恢复冒烟（doc 30min 缩短为探测基线）

**清理**: 删除 `ua2_create_runtime._dispatch_ua2_1_batch` 死代码（已走 `precise_batch`）

**剩余 BLOCKED**: UA-2-2-053 GUI-DEFERRED；UA-1-1-06 依赖鉴权 mock

---

## 批次 12 — 419 挂接收尾 + 开发完成声明 (2026-07-13, 未跑)

**新增**:
- `known_blocked.py` — 文档明确 BLOCKED 登记（当前仅 UA-2-2-053）
- `unit_tests/test_419_coverage.py` — 419 矩阵 / UA-2(265) / UA-3(98) handler 全覆盖单测
- `scenario_policy.classify_case` — UA-1/2/3 统一路由到 chapter runtime

**修复**:
- UA-1-1-05 — reconnect mock 停启闭环（停 mock → 启用 DS → 起 mock → 轮询 alive + RT）
- `test_ua1_policy` — 对齐新 classify 语义

**开发完成判定** (仍不跑真环境):

| 维度 | 数量 |
|------|------|
| 文档 Case | 419 |
| `_SUPPORTED` 登记 | 419 |
| UA-2 runtime handler | 265 |
| UA-3 runtime handler | 98 |
| UA-1 runtime handler | 56 |
| 预期 BLOCKED | 1 (UA-2-2-053 GUI-DEFERRED) |

**下一步**（需用户允许后）: `pytest ua_test_harness/unit_tests` → `case_inventory` → 分章 CLI 真环境采样

---

## 批次 13 — talk-main 任务 A 第一批 (2026-07-13)

**范围**: UA-2-2 余量回归 `003/006/012/014/017/018/020~032`(除 `053`) + UA-2-1-014

**OBSERVED → 真实断言 (晋升 STRICT_IMPLEMENTED)**:
- `UA-2-1-014`: 空 `tagBaseName` 拒绝路径 `no_residual_on_reject`；接受路径断言 `tag_name_saved` + 清理后无残留
- `UA-2-2-003`: 双 DS(types+empty) 各建 tag；`active_rows` + `query_tags_with_quality` 断言归属、无重复 ID、不限定范围查询
- `UA-2-2-058`: `update_tag` 改 `tagBaseName`；旧映射消失、新映射可查、`config_page_row` + `rt_row`
- `UA-2-2-059`: `add_tag_group` + `batch_update_tags` 分组移动；G1 空 / G2 有 / ID 不变
- 同批已在 `case_fidelity.STRICT` 登记的 UA-2-2 `020~032/037~040/048~052/054~067` 等回归 handler 保持 `check_*` 闭环

**保留 OBSERVED_ONLY (探索类, 未改 doc)**:
- `UA-2-2-007/009/010/013/021/043/044/046/047/053/063/064`

**inventory 变化** (相对任务 G 基线 `246/173`):
- `IMPLEMENTED` 246 → **270** (+24)
- `PARTIAL` 173 → **149** (-24)
- `coveragePercent` 58.71% → **64.44%**
- `structureOk=true`

**单测**: `compileall` OK；`pytest ua_test_harness/unit_tests` **179 passed**

**产品 FAIL**: 本批仅 mock 单测, 未真跑

**修复**: `result_update_cases` 中 `058/059` 提前于通用 `create_case_tag`, 避免重复建 tag

---

## 批次 14 — talk-main 任务 A 第二批 + 任务 F (2026-07-13)

**任务 A 范围**: UA-2-3/UA-1/UA-3-1/2/3/4 回归类 OBSERVED→断言

**OBSERVED → 真实断言 (晋升 STRICT)**:
- `UA-2-3-005/007/008/009/010`: 导出字段与配置/限值/13 类型逐行 `check_*`
- `UA-1-1-05/06/07/08`: 连接恢复与鉴权路径已有 `check_*`(06 补 `alive_false_without_creds`)
- `UA-1-2-03`: `history_frozen_on_disable`; 修复历史分支先于误 re-enable
- `UA-3-1-008`: 同源独立频率 — 各位号 RT 可读 + 计数断言
- `UA-3-3-012/013`: 类型不匹配/越界 — handler 已有 `check_*` 晋升 STRICT
- `UA-3-4-007`: 空/未来历史窗口 `empty_past_window` / `empty_future_window`

**保留 OBSERVED_ONLY (探索)**:
- UA-2-3: `012/018/022~024/027/032`; UA-2-5 全章探索; UA-1-1 `09~11`; UA-3-1 `007/009/012/017/020` 等

**任务 F — 清 UA-3 死代码**:
- 删除 `scenario_runtime.py`
- `scenario_policy.py` 移除 `_SHARED_SCENARIOS` / `_ua3_scenario_for` / `_execute_shared` 回退
- 未知章节统一 `BLOCKED`

**inventory 变化** (相对批次 13 `270/149`):
- `IMPLEMENTED` 270 → **281** (+11)
- `PARTIAL` 149 → **138** (-11)
- `coveragePercent` 64.44% → **67.06%**

**单测**: `compileall` OK；`pytest ua_test_harness/unit_tests` **181 passed**

---

## 批次 15 — talk-main 任务 A 第三批 + 任务 C (2026-07-13)

**任务 A 范围**: UA-2-1 探索余量中带 doc 硬断言的 case

**OBSERVED → 真实断言 (晋升 STRICT)**:
- `UA-2-1-099/102/104`: needPush 关闭 / 可用性读取 / 历史落库
- `UA-2-1-011/012`: 重复映射拒绝后原位号仍在 / 非法 base 拒绝无残留
- `UA-2-1-041/043/045/047/049/051/053/056/059/062/065`: 探索写入拒绝路径 `rt/src unchanged`
- `UA-2-1-085`: 源只读+配置可写 — 写入失败或源端不变

**任务 C — legacy 双轨合并**:
- 下线 `tests/ua_3/test_collection.py` + `test_13_types.py` 的 7 条 `@case` 手写实现
- 统一由 `zz_documented_cases` → `execute_documented_case` → `ua3_runtime`
- `UA-3-5-001` `measure_rt_samples` 补 `samples_recorded` 断言 → PASS
- 晋升 STRICT: `UA-3-1-001~004`, `UA-3-2-001`, `UA-3-3-001`, `UA-3-4-001`, `UA-3-5-001`

**inventory 变化** (相对批次 14 `281/138`):
- `IMPLEMENTED` 281 → **304** (+23)
- `PARTIAL` 138 → **115** (-23)
- `coveragePercent` 67.06% → **72.55%**

**单测**: `pytest ua_test_harness/unit_tests` **185 passed**

---

## 规模/时长缩减审计（任务 B）

> 原则：能还原 doc 规模的还原；不能的**必须登记**，禁止静默缩减。  
> 审计方式：静态代码 grep + doc 对照（`ua_test_gui/doc/test_cases/*.md`）。

| Case ID | doc 要求 | 实现实际 | 代码位置 | 缩减理由 | 可否还原 |
|---------|----------|----------|----------|----------|----------|
| **UA-2-3-014** | Excel 导入 **10 行** | 造数 `min(10,3)=3` 条 tag 后导入 | `ua2_import_runtime.py` L54 | 导入夹具按最小行数建 tag，未按 10 行 Excel 全量造数 | 可：扩 `_make_tags` 到 10 |
| **UA-2-3-032** | browse+batchAdd **100 条**完整性 | `min(100,20)=20` 条 | `ua2_import_runtime.py` L261 | mock 未注册节点池上限约 20，不足 100 时 OBSERVED | 受限：需扩 mock 节点或分批 |
| **UA-2-5-015** | 批量移动 **10 个**位号 | `min(3,10)=3` 个 | `ua2_group_runtime.py` L205 | 分组移动回归用最小批量验证逻辑 | 可：改为 `range(10)` |
| **UA-2-5-016** | 移动到 Root（单/少量位号） | 同路径 **3 个**位号（非 014 分支） | `ua2_group_runtime.py` L205 | 与 015 共用批量造数分支，非 doc 要求的单点移动 | 可：016 单独 `range(1)` |
| **UA-1-3-03** | **5 轮**断开-重连时延统计 | `range(3)` 三轮 + `note: reduced_3_rounds_for_impl` | `ua1_precise.py` L167-178 | 每轮含 mock 停启+轮询，5 轮真跑耗时过长 | 可：env 窗口允许时改 5 |
| **UA-1-3-07** | 停止 mock 等待 **120s** 后恢复 | `sleep(30)` + `long_disconnect_sec: 30` | `ua1_precise.py` L113-121 | 长断线探索，120s 阻塞 overnight CLI | 可：参数化 `disconnect_sec` |
| **UA-2-1-087** | frequency=1，运行 **30s** 采样 | duration=**30s**（对齐） | `ua2_precise.py` L687-703 | — | **已对齐** |
| **UA-2-1-088** | frequency=5 效果探索 | duration=**60s**（doc 未写死秒数） | `ua2_precise.py` L690 | 探索采样窗口取 60s | 可酌情延长 |
| **UA-2-1-089** | frequency=30 效果探索 | duration=**120s** | `ua2_precise.py` L690 | 低频需更长窗口才有历史 | 可酌情延长 |
| **UA-2-1-100** | needPush 关闭后历史/RT 行为 | RT 采样 **5 次×2s**（非 30s 历史窗） | `ua2_precise.py` L874-879 | 与 099 分支区分，缩短 RT 轮询 | 探索类，可保留 |
| **UA-2-1-112** | 批量 1/10/100/**上限/上限+1** | 仅测 `[1,10,100]` 三档 | `ua2_precise.py` L1097-1113 | 上限探测需 mock 节点池+接口上限摸底 | 受限：需节点池与 API 上限 |
| **UA-3-5-001** | 单点位号延迟分布 | `measure_rt_samples` **30 次**采样 | `ua3_precise.py` L222 | doc 未规定采样次数；30 为基线 | 可增采样 |
| **UA-3-5-002/004/006** | 单请求 **100** 位号 RT | `measure_rt_batch count=100` | `ua3_runtime.py` L233-237 | — | **已对齐** |
| **UA-3-6-001** | 并发**逐级递增**读 | 固定 `workers=5, requests=20` | `ua3_runtime.py` L256 + `ua3_precise.py` L251 | 探索基线：固定并发档而非递增阶梯 | 可：实现 workers 阶梯 |
| **UA-3-6-002** | DB 并发递增 | 固定 `workers=10, requests=30` | `ua3_runtime.py` L258 | 同上 | 可：实现递增 |
| **UA-3-6-003** | 批大小**递增** | 单次 `batch=10` 固定批 | `ua3_runtime.py` L260 + `ua3_extra.py` L544 | 未做多档 batch 递增探测 | 可：循环 batch 列表 |
| **UA-3-6-015** | 持续负载+短时过载后 **30min** 恢复 | **50 并发读 + sleep(5)** 冒烟；`shortened_overload_probe_not_30min` | `ua3_extra.py` L727-744 | 30min 长稳不适合单次 CLI case 超时 | **不可**在默认 case 超时内还原 |
| **UA-3-6-007** | 批量写探索 | `write_batch count=10` | `ua3_runtime.py` L268 | doc 未写死条数 | 可扩 |
| **UA-2-4-002/021** | 批量软删/物理删 **10 条** | `range(10)` | `ua2_recycle_runtime.py` | — | **已对齐**（批次 8 修正） |
| **UA-2-1-105** | browse **10 节点** batchAdd | `pick_unused_nodes(..., 10)` | `ua2_precise.py` batch | — | **已对齐** |

**登记结论**：上表 15 项存在明确缩减或简化；其中 4 项已与 doc 对齐；其余保留实现并在此登记，后续 env 窗口允许时优先还原「可」项。

---

## 批次 16 — talk-main 任务 B + D + E (2026-07-13)

**任务 B**：新增 §规模/时长缩减审计（上表），不静默缩减。

**任务 D**：`docs/overnight-report.md` UA-3 路由改为 `ua3_runtime`；inventory 改为 304/115/72.55%。

**任务 E**：env 可用时 `scripts/run_automation_ua2.py` 真跑 UA-2 高保真首批 16 条 → 更新 `docs/case-inventory.json` 的 `verificationStatus`（PASS→`VERIFIED`，产品 FAIL→`VERIFIED_FAIL` 保留）。

**任务 E 真跑结果**（`output/automation_ua2_20260713_100136/`，耗时 ~153s）:
- env: `env.json` 可达；types mock 18965 + empty mock 18967；共享 baseline provision OK
- **15 PASS → VERIFIED**；**1 FAIL → VERIFIED_FAIL**（`UA-2-1-019`，产品 bug 保留）
- `docs/case-inventory.json` summary: `verified=15 verifiedFail=1 notVerified=403`
- runner exit 1（因 1 条 FAIL，符合纪律：不吞 FAIL）

**代码支撑**:
- `case_inventory.py` 新增 `--verification-overlay` + `verification_overlay_from_run`
- `run_automation_ua2.py` 批次结束写 `verification-overlay.json` 并刷新 `docs/case-inventory.json`
- 单测 `test_verification_overlay.py` +2


---

## 真跑批次 — 任务E UA-2-1余量首批 (2026-07-13 10:31)

**产物**: `output/automation_ua2_ua21_20260713_102916`
**选择**: UA-2-1 章 STRICT 余量 10 条（001~010），跳过已 VERIFIED 的 017/019/021/022
**环境 BLOCKED**: `ua_shared_ua2_types_ds` enable 后 120s 内未 alive（mock 18965/18967 已启动）
**case 执行**: **0 条** — baseline provision 失败，未更新 VERIFIED
**triage（主 Agent）**: 共享 DS 复用路径；需排查 TPT→mock 连通或 DS 卡死（非 case 断言 FAIL）

---

## 批次 17 — 任务 E 扩展：UA-2 批量真跑参数化 (2026-07-13)

**脚本扩展** (`scripts/run_automation_ua2.py` + `.ps1`):
- `--chapter UA-2-1` / `--cases id1,id2` / `--limit N` / `--chapter-timeout-sec`
- `--skip-prereqs` 续跑批次；`--rerun-verified` 可选
- 仅选 `STRICT_IMPLEMENTED`，**跳过 PARTIAL 探索类**；默认跳过已 VERIFIED
- 自动按超时估算 batch（`PREREQ_BUDGET` + per-case 200s）
- 共享 baseline 18965/18967 复用；`PYTHONPATH` 固化；inventory 刷新防 implemented=0
- 真跑结束追加 `overnight-findings.md` + FAIL triage

**单测**: `test_run_automation_ua2.py` +2

**UA-2-1 余量首批真跑**: 环境 BLOCKED（见上），**待 baseline 恢复后重跑** `--chapter UA-2-1 --limit 10 --skip-prereqs`

---

## baseline alive 失败诊断（只读，2026-07-13 10:42）

**① DS 状态** (`diagnose_ua2_datasource.py --ds-name ua_shared_ua2_types_ds`):
| 字段 | 值 |
|------|-----|
| id | **80** |
| enabled | **true** |
| alive | **false** |
| endpoint | `opc.tcp://10.30.70.77:18965/ua_mocker/` |
| active/recycle tags | **0 / 0** |

`ua_shared_ua2_empty_ds` id=**81** 同样 enabled=true alive=false，endpoint `...18967...`，无残留 tag。

**② mock / 端口**:
- 失败批次时 automation 日志：mock 18965/18967 **started=true**（非 mock 未起）
- 诊断时刻（无 mock）：`10.30.70.77:18965` TCP **不通**
- 手动起 `ua2_types.yaml` 后：本机 TCP **通**（`18965_connect=OK`）

**③ enable + 180s 轮询**（mock 已起，`change_ds_state(enable)` 后每 1s 查 alive）:
- `firstAliveAtSec`: **null**
- `finalAlive`: **false**（enabled 仍为 true）
- 产物：`output/diag_poll_ds80_result.json`

**④ 归类（供主 Agent 决策）**:
- **(a) 慢恢复 >120s** → **排除**（mock 在跑，180s 仍不 alive；非单纯 120→180 可解）
- **(b) DS 卡死** → **可疑**（id=80 长期 enabled+not-alive、无 tag；约 10:04 同 DS 曾 baseline OK，mock 停后可能 TPT 侧连接状态未恢复；需 disable→wait→enable 或 teardown+重建验证）
- **(c) TPT↔mock 网络** → **首要怀疑**（TPT `10.10.58.153` 须 OPC 连 `10.30.70.77:18965`；本机 TCP 通 ≠ TPT 可达；180s 不 alive 符合 TPT 连不上 mock）

**未做**：teardown、改 case、拉长 baseline 超时、绕路换 endpoint。
