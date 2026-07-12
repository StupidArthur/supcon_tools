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
