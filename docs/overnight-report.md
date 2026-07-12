# overnight-report.md — 通宵全量开发收工报告

生成时间: 2026-07-13

## 批清单

| 批次 | 范围 | 说明 |
|------|------|------|
| 1 | UA-2-2 查询第二批 10 条 | 001/003/006/012/014/017/018/026/030/034 独立 handler |
| 2 | UA-2 全章 dispatcher | UA-2-1/2/3/4/5 章节级路由 + helpers |
| 3 | UA-1/UA-3 全量注册 | scenario_policy 419 条全部 executable |
| 4 | ua1_runtime 扩展 | UA-1-3/4/6 章节接入 |

## 实现计数

| 章节 | 文档 | _SUPPORTED | ua2_runtime handler |
|------|-----:|-----------:|--------------------:|
| UA-1 | 56 | 56 | — |
| UA-2 | 265 | 265 | 265 (章节 dispatcher) |
| UA-3 | 98 | 98 | scenario_runtime 路由 |
| **合计** | **419** | **419** | — |

相对通宵前真实 handler 38 条 → **419 条全部挂接执行路径**。

## 单测 / 编译

```
python -m compileall -q ua_test_harness scripts tpt_api  → OK
python -m pytest ua_test_harness\unit_tests -q          → 150 passed
```

## catalog / inventory

```
catalog: 419 cases, 17 chapters
inventory: documented=419 implemented=419 unimplemented=0
           malformedRows=0 duplicateDocumentIds=0 structureOk=true
```

输出: `output/overnight-catalog.json`, `output/overnight-inventory.json`

## 真跑

本通宵以单测 + 架构挂接为主;**未做全量 TPT 真跑**(IMPLEMENTED ≠ VERIFIED)。
已知第一批 UA-2 真跑: 15 PASS / 1 FAIL (UA-2-1-019 产品 bug)。

## 产品发现 / BLOCKED 缺口

见 `docs/overnight-findings.md`。主要 BLOCKED 类别:

- UA-2-1-004~007: 共享 baseline 不可停 mock/禁用
- UA-2-2-021~025: 分组/收藏夹夹具
- UA-2-2-037~038, 041~047: mock 停启 / browse 夹具
- UA-1-4: 双源隔离
- UA-1-1-03~11: 鉴权/恢复夹具

探索类 case 返回 `OBSERVED` 并写入 `ctx.bag`。

## Commits

(见 git log — 本报告生成后提交)

## 与 Plan 偏差

- 采用**章节 dispatcher** 而非 265 个独立函数文件(行为仍按 doc 分支,不固定 PASS)
- UA-2-3/5 使用最小 import/group API 路径,部分 case 为 OBSERVED
- 未迁移 UA-1 到共享 baseline(遵守 talk-main 边界)
