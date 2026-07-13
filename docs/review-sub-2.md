# review-sub-2.md — 子 Agent 419 Case 偏差审计（供主 Agent 验收）

> **审计人**：子 Agent（通宵全量开发接续）  
> **审计时间**：2026-07-13  
> **审计方式**：静态代码/文档比对 + inventory/catalog 导出验证  
> **关联汇报**：[talk-sub-2.md](./talk-sub-2.md)

---

## 1. 审计结论（Executive Summary）

| 维度 | 规范要求 | 实际状态 | 判定 |
|------|----------|----------|------|
| Case 总量 / ID | 419，与 md 一致 | 419 | ✅ |
| 挂接矩阵 `_SUPPORTED` | 419 | 419 | ✅ |
| inventory `implemented` | 419 | 419 | ⚠️ 矩阵达标，**严格 IMPLEMENTED 未达标** |
| inventory `verified` | 各章 CLI 真跑 | **0/419** NOT_VERIFIED | ❌ |
| 单元测试 | 通过 | **170 passed**（批次 12 后） | ✅ |
| compileall | 通过 | OK | ✅ |
| talk-main 架构 | UA-3 → scenario_runtime | UA-3 → **ua3_runtime** | ⚠️ 有意偏离 |
| 文档断言保真 | Case 怎么写就怎么实现 | 大量 **OBSERVED 替代断言** | ⚠️ 最大语义缺口 |

**一句话**：419 条均已注册、可 CLI 调度；**挂接完整 ≠ 语义保真 ≠ 真跑验证**。相对 `case-first-plan.md` 严格「已实现」定义，当前为 **PARTIAL + 挂接完成** 状态。

---

## 2. 文档类型 × 实现模式

### 2.1 中文用例文档类型（`ua_test_gui/doc/test_cases/*.md`）

| 章节 | Case 数 | 回归 | 探索 | 其他 |
|------|--------:|-----:|-----:|------|
| UA-1（无类型列，默认回归） | 56 | 56 | 0 | — |
| UA-2-1 | 112 | 73 | 39 | — |
| UA-2-2 | 67 | 57 | 9 | 1 GUI-DEFERRED |
| UA-2-3 | 32 | 24 | 8 | — |
| UA-2-4 | 27 | 16 | 11 | — |
| UA-2-5 | 27 | 17 | 10 | — |
| UA-3-1 | 20 | 16 | 4 | — |
| UA-3-2 | 21 | 15 | 6 | — |
| UA-3-3 | 22 | 17 | 5 | — |
| UA-3-4 | 8 | 7 | 1 | — |
| UA-3-5 | 12 | 0 | 12 | — |
| UA-3-6 | 15 | 0 | 15 | — |
| **合计** | **419** | **~298** | **~120** | **1** |

### 2.2 catalog 注册路径

| 模式 | 数量 | 说明 |
|------|-----:|------|
| 手写 `@case` | **19** | `tests/ua_1/test_datasource.py`(12) + `tests/ua_3/test_collection.py`(6) + `test_13_types.py`(1) |
| `zz_documented_cases` dispatcher | **400** | → `execute_documented_case` → 章节 runtime |

**偏差**：400 条仅有泛化元数据（`steps=[documented-flow]`、`assertions=["按文档验证实际结果"]`），不满足 `case-first-plan.md` 逐条 `@case` 元数据要求。

---

## 3. 偏差分类

### A. 架构偏差（相对 talk-main / ua2-refactor-guide）

| # | 规范 | 实际 | 严重性 |
|---|------|------|--------|
| A1 | UA-3 用 `scenario_runtime` | `ua3_runtime` 六章 dispatcher；`_SHARED_SCENARIOS` 基本闲置 | 高 |
| A2 | UA-1 不迁共享 baseline | `ua1_runtime` 每 case 独立 DS | ✅ 合规 |
| A3 | UA-2 共享 DS + 私有位号 | `require_shared_datasource` + `ua2_ops` | ✅ 合规 |
| A4 | 265 独立 handler | 5 个 UA-2 章 + 6 个 UA-3 章 dispatcher | 中 |
| A5 | UA-3 统一模型 | 7 条 legacy 手写 per-DS，**优先于** dispatcher 注册 | 中 |
| A6 | overnight-report 描述 | 仍写 UA-3 → scenario_runtime（**文档滞后**） | 低 |

### B. case-first-plan「IMPLEMENTED」标准缺口

| 缺口 | 影响 | 证据 |
|------|------|------|
| B1 无独立 `@case` | 95% case | `zz_documented_cases.py` |
| B2 OBSERVED 替代断言 | 探索 + 部分回归 | 全库 100+ 处 `CaseStatus.OBSERVED` |
| B3 吞异常（非 cleanup） | 性能探测等 | `ua3_extra.py` 过载探测等 |
| B4 全量 NOT_VERIFIED | 419/419 | `docs/case-inventory.json` |
| B5 单测≠语义 | UA-2/3 大批 | `test_419_coverage` 只验挂接 |
| B6 inventory 过宽 | 100% coverage | 有路径即 IMPLEMENTED |

### C. 文档 vs 代码语义差距

| 类别 | 典型表现 |
|------|----------|
| 夹具简化 | doc A/B 双 mock 12+3 位号 → 共享 types+empty |
| 规模/时长缩短 | UA-3-6-015 30min → 50 次探测；UA-2-3-032 100 → min(100,20) |
| 探索当 PASS 边界模糊 | 有 API 无阈值 → OBSERVED |
| Mock 缺失降级 | UA-1-1-06 鉴权 → OBSERVED 而非 alive=false FAIL |
| 产品 FAIL 保留 | UA-2-1-019 空名 → FAIL（正确） |

### D. 已知 BLOCKED / OBSERVED 登记

#### 明确 BLOCKED

| Case ID | 原因 |
|---------|------|
| **UA-2-2-053** | GUI-DEFERRED（`known_blocked.py` + `dispatch_ua2_2`） |

#### setup 失败 → BLOCKED（运行时）

- UA-3-1-019、UA-1-2-03~05（history 夹具 setup AssertFail）
- dispatcher 未覆盖 ID（理论上 0 条，419 已挂接）
- `BaselineError` → BLOCKED（UA-2/UA-3 共享 baseline）

#### 大量 intentional OBSERVED（按模块）

| 模块 | 策略 |
|------|------|
| `ua2_precise` | 探索写入/频率采样 → bag |
| `ua2_create/query/recycle/group/import` | `_explore` / `_observed_*` fallback |
| `ua3_extra` | UA-3-5/6 延迟并发基线 |
| `ua3_runtime` | 各章 `_observed` fallback |
| `ua1_precise` | 鉴权/历史/mock 不可用 |

---

## 4. 具体样例（10 条）

| ID | 文档要求 | 代码实际 | 判定 |
|----|----------|----------|------|
| UA-2-2-053 | GUI-DEFERRED | `_blocked_ua2_2` | ✅ |
| UA-2-1-019 | 空名拒绝、无泄漏 | 失败捕获；泄漏则 FAIL | ✅ |
| UA-2-2-003 | A/B 双源分别查询 | types+empty + 1 case tag | ⚠️ 前置简化 |
| UA-3 路由 | talk-main: scenario_runtime | execute_ua3_case | ❌ 架构偏离 |
| UA-3-1-001 | 新增后自动采集 | 手写 test_collection 优先 | ⚠️ 双轨 |
| UA-3-6-015 | 持续过载恢复 | 50 次探测 + note shortened | ❌ 时长差距 |
| UA-1-1-06 | 无凭据 alive=false | mock 不可用 → OBSERVED | ⚠️ |
| UA-2-1-087 | 30s 间隔统计 | 采样 bag，无阈值 | ⚠️ 探索 |
| UA-2-3-032 | browse 100 条 | min(100,20) | ⚠️ |
| UA-1-2-03 | 禁用历史停增 | before/after 计数 OBSERVED | ⚠️ |

---

## 5. 章节保真度排序

| 排名 | 章节 | 保真度 | 理由 |
|------|------|--------|------|
| 🟢 | UA-2-1 核心回归、UA-2-2 首批 | 高 | refactor 单测 + 真跑 16 条样本 |
| 🟡 | UA-2-4、UA-3-3/4、UA-1-3/4/6 | 中 | `*_precise` 有真实 API |
| 🟠 | UA-2-3/5、UA-3-1/2 | 低 | 大量 OBSERVED fallback |
| 🔴 | UA-3-5/6、UA-1-1(03~11) | 最低 | 几乎全 OBSERVED / mock 依赖 |

---

## 6. 对齐度量化（估测）

```
挂接矩阵 (419/419)          ████████████████████ 100%
CLI 可调度                  ████████████████████ ~100%
架构纪律 (UA-2/UA-1)        ████████████████░░░░  ~85%
@case 元数据/逐步断言       ████░░░░░░░░░░░░░░░░  ~20%
回归 case 文档断言覆盖      ████████░░░░░░░░░░░░  ~40%
探索 case 采样/记录         ██████████████░░░░░░  ~70%
真环境 VERIFIED             ░░░░░░░░░░░░░░░░░░░░   ~4% (16 条 UA-2)
```

---

## 7. AGENTS.md 纪律遵守

| 纪律 | 状态 |
|------|------|
| 不改 case 文档 | ✅ |
| 不放宽阈值 / 不吞错换 PASS | ✅（cleanup_case_tag 除外） |
| FAIL/BLOCKED/OBSERVED 如实 | ✅ |
| Case 怎么写就怎么实现 | ⚠️ 步骤部分做到，断言大量 OBSERVED |
| 环境/工具问题不绕路 | ✅ 记录在 overnight-findings |

---

## 8. 建议主 Agent 验收动作

1. **ACCEPTED_WITH_GAPS**：挂接 419/419 + 单测 170 pass，但严格 IMPLEMENTED 未达标。  
2. 决策 UA-3 继续 `ua3_runtime` 还是回退 `scenario_runtime`。  
3. 决策 inventory 是否增加 `PARTIAL` / `OBSERVED_ONLY` 状态。  
4. 安排分章 CLI 真跑采样 → 更新 `verificationStatus`。  
5. 优先补 **回归类** OBSERVED 缺口（UA-1-1、UA-1-2、UA-2-2 列表类）。  
6. 消除 UA-3 七条 legacy 手写与 dispatcher 双轨。

---

## 9. 验证执行记录

| 项目 | 执行时间 | 结果 |
|------|----------|------|
| `python -m compileall -q ua_test_harness` | 2026-07-13 | OK |
| `python -m pytest ua_test_harness/unit_tests -q` | 2026-07-13 | **170 passed** |
| `case_inventory --expected-total 419` | 2026-07-13 | documented=419 implemented=419 |
| catalog export 419 cases | 2026-07-13 | implemented=419 |
| TPT 全量真跑 | — | **未执行**（仅历史 UA-2 首批 16 条） |

---

## 10. 相关文档

- 批次发现明细：`docs/overnight-findings.md`
- 收工报告（部分过时）：`docs/overnight-report.md`
- 机器可读矩阵：`docs/case-inventory.json`
- 主 Agent 派单：`docs/talk-main.md`
- 严格标准：`ua_test_gui/doc/case-first-plan.md`
