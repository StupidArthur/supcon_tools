# 入口文档 — UA-2 资源模型重构(执行 Agent 必读)

你是一个**执行 Agent**。你的职责:按主 Agent(技术负责人)写好的指导,逐个实现任务、跑测试、commit、回报。主 Agent 负责架构、验收准则和最终验收。**你不派子 agent,不自行改架构,不放宽产品断言。**

---

## 1. 先做什么

1. **读本文件**(你正在读)。
2. **读主指导手册**: `docs/compose/guidance/ua2-refactor-guide.md` — 这是核心。里面有:架构概要(§1)、全局禁令(§2)、任务分解表(§3)、验收框架(§4)、回报格式(§5)、每个任务的详单(§6)。
3. **当前进度**: 任务 A(Empty Mock)已由主 Agent 完成并验证。**你的第一个任务是 B(Baseline provisioning)。**
4. 做 B 时,额外读 `docs/compose/plans/2026-07-12-ua2-resource-refactor.md` 的 **Task 2** 节(参考实现代码)。
5. 实现前,先读 B 详单里"先读"列出的**真实代码**,核实 API 签名。**真实代码为准;参考代码只是骨架。**

## 2. 工作循环(每个任务)

```
读指导手册 §6/<任务> + 总 Plan 对应 Task 节 + 真实代码
  -> 实现(只改"允许修改/新增"的文件)
  -> 跑该任务的"验收命令"(compileall + pytest)
  -> git add <仅本任务文件>  (绝不 git add .)
  -> git commit -m "<给定 message>"
  -> git status --short
  -> 按指导手册 §5 格式回报
  -> 停下,等主 Agent 验收。验收通过后,主 Agent 告诉你下一个任务。
```

**一次只做一个任务。做完回报后停下,不要自动开始下一个。**

## 3. 仓库导航

- **工作目录**: `F:\github\supcon_tools`(Windows PowerShell)。
- **`tpt_api` 怎么 import**: `ua_test_harness/_paths.py` 自动把 `tpt_api/python` 加进 `sys.path`。你的测试文件放 `ua_test_harness/unit_tests/` 下,`import tpt_api.datahub` 即可(现有单测已验证可用)。`tpt_api` 真实代码在 `tpt_api/python/tpt_api/datahub.py`、`tpt_api/python/tpt_api/types.py`。
- **跑单测**: `python -m pytest ua_test_harness\unit_tests\<测试文件> -q`
- **编译检查**: `python -m compileall -q <文件或目录>`
- **catalog/inventory**(仅 J 阶段用): `python -m ua_test_harness.cli catalog --output <path>` / `python -m ua_test_harness.case_inventory --repo-root . --expected-total 419 --strict-structure --output <path>`
- **关键目录**:
  - `ua_test_harness/` — 测试框架、runtime、fixtures、ops、provisioning、unit_tests
  - `scripts/` — runner、cleanup、teardown、diagnose
  - `ua_mocker/` — mock 配置(yaml)
  - `tpt_api/python/tpt_api/` — TPT API 客户端(真实签名来源)
  - `ua_test_gui/doc/test_cases/` — 16 条 case 的产品预期(markdown,**不许改**)

## 4. 铁律(违反即返工)

- **只改本任务"允许修改/新增"的文件**;"禁止修改"的文件一行都不动。
- **不放宽产品断言、不改 case 步骤、不改阈值**。case 跑不过就让它 FAIL,如实记录。
- **不吞 cleanup 异常**(唯一例外: `ua2_ops.cleanup_case_tag` 明确允许吞,防止清理掩盖 case 原始状态)。
- **不用 `inspect.getsource()` 做字符串检查伪造覆盖**(个别旧测试有源码断言,按详单要求保留即可)。
- **测试用 fake/monkeypatch**,不连真实 TPT。
- **git**: 绝不 `git add .`;绝不 `git reset --hard` / `git clean -fd` / `git checkout .` / `git restore .` / `git stash`;不碰子模块 `review3`、`data_factory_server`;不提交 `output/`、密码、token、真实内网 IP、运行日志。
- **发现参考代码与真实代码不一致**: 停止扩大修改,在回报里精确报告差异(哪个函数签名/字段不同),**不要猜、不要擅自偏离**。
- **不开发 UA-2 第二批,不改 GUI。**

## 5. 架构一句话(详见指导手册 §1)

16 条 UA-2 case 现在每条自建自删数据源,导致 endpoint 冲突和"currently in use"删除失败。改为:**两个共享数据源(`ua_shared_ua2_types_ds` 端口18965 / `ua_shared_ua2_empty_ds` 端口18967)在 TPT 服务器上 provision 一次,所有 case 按固定名查回复用,不创建不删除;case 自己显式创建/删除 `ua_case_ua2_` 前缀的私有位号;registry 只作异常兜底。** 每个 case 跑独立子进程,所以共享 DS 必须活在服务器上,不能靠 Python registry 跨进程。

## 6. 回报格式(完成后按此回报,主 Agent 据此验收)

```
**任务**: <字母. 名称>
**状态**: success | partial | failed | blocked
**摘要**: 一行
**修改/新增文件**: 列表
**测试结果**: compileall 结果 + pytest 摘要(N passed)
**commit SHA**: 完整 sha
**git status --short**: 输出
**与 Plan/真实代码的差异**: 精确列出;无则写"无"
**已知风险**: 无则写"无"
```

## 7. 任务顺序(主 Agent 验收通过后才进下一个)

```
A. Empty Mock            — 已完成(主 Agent)
B. Baseline provisioning — 你的第一个任务
C. Thin ops              — B 验收后
G. Cleanup 工具          — C 验收后(或与 C 间)
(主 Agent 做 BaselineError->BLOCKED 接线)
D. UA-2-1 重构           — B+C+接线后
E. UA-2-2 重构           — D 后
F. UA-2-4 重构           — E 后
H. Teardown+Diagnose     — F 后
I. Runner                — H 后
J. 跨模块回归            — 主 Agent 做
K. 真实环境              — 主 Agent 做
```

具体每个任务的文件、行为要求、单测、验收命令、commit message、验收准则,**全部在 `docs/compose/guidance/ua2-refactor-guide.md` 的 §6**。本文件只负责把你导向那里。

---

**现在开始**: 打开 `docs/compose/guidance/ua2-refactor-guide.md`,读 §1(架构)、§2(禁令)、§5(回报格式),然后读 §6 的 **B. Baseline provisioning 层**,并参考总 Plan 的 Task 2。实现、自测、commit、回报。然后停下等我验收。
