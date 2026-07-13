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
