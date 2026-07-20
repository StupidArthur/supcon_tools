# 单阀门二阶水箱模板：Coding Agent 从这里开始

> 用途：这是实施任务的入口文件。它不重复产品设计，而是规定 Agent 的阅读顺序、执行纪律、冲突处理和阶段汇报方式。
>
> 适用仓库：`supcon_tools/review3`
>
> 核对基线：提交 `e6118bdecc1b8bfc061f3eed3a3ec13f9d45a133`，2026-07-19。若当前提交不同，必须先重新执行第 4 节的基线检查，不能照抄基线结论。

---

## 1. 你要完成什么

在现有 `config-tool` 中实现“单阀门二阶水箱”固定可视化 DSL 模板。普通用户应能在同一页面完成组态、保存、启动仿真、查看实时数据、在线调 PID、观察趋势、批量生成和导出。

这不是新建通用 HMI，也不是重写 DataFactory。不得用假数据替代 Engine 快照，不得修改水箱、阀门或 PID 核心算法。

---

## 2. 必读文档与优先级

首次做总体评审或上下文容量充足时，严格按以下顺序完整阅读：

1. `todo/second_order_tank_agent_start_here.md`：执行纪律和阅读入口。
2. `todo/second_order_tank_visual_dsl_template_design.md`：产品目标、交互、非目标、视觉要求和总体验收标准。
3. `todo/second_order_tank_repository_contracts.md`：已经结合当前代码核对过的字段、接口、状态机、保存和测试契约。
4. `todo/second_order_tank_implementation_playbook.md`：分阶段施工卡和阶段门禁。

然后只阅读当前阶段任务卡列出的源码。不要一开始把仓库所有文件塞进上下文。

如果 Agent 上下文较小，不要强行一次装入约 2500 行规范。每个阶段至少完整阅读本入口文件，再按下表读取指定章节；实施手册只读“总体文件边界”和当前阶段任务卡：

| 阶段 | 产品设计章节 | 仓库契约章节 |
|---|---|---|
| 0 基线 | 1、2、4、17、19 | 1、2、12 |
| 1 DSL/状态 | 3～6.4、9、10、11、15、18.1、18.3 | 1～7、11、12 |
| 2 SVG/检查器 | 6.1～6.3、7～10、18.1、18.2 | 3、5、6、7、11 |
| 3 Wails 进程 | 6.4、6.6、11～14.1、18.3 | 1、2、7、8、12 |
| 4 REST/WS | 6.4、6.6、7.4、11～14.3、18.2、18.4 | 1、2、7、8、9、11 |
| 5 在线写值 | 6.5、9.4、11、14.2、15.3、18.4 | 1、5.4、7、9、11 |
| 6 趋势/品质 | 6.5、7.4、13.3、16、18.1、18.2 | 7、9.3、10、11 |
| 7 批量 | 6.7、7.4、14.1、15、18.1、18.5 | 7、8、10～12 |
| 8 验收 | 18～21，并复查所有非目标 | 全文 |

若使用不同 Agent 接力，每个 Agent 还必须先阅读上一阶段的最终回报和当前 `git diff`；不得仅凭文档假设上一阶段已经完成。

发生冲突时，按以下优先级处理：

1. 当前可运行代码中的水箱、阀门、PID 和 DSL 真实语义；
2. `second_order_tank_repository_contracts.md` 中标为“规范”的接口与状态契约；
3. `second_order_tank_visual_dsl_template_design.md` 的产品和验收要求；
4. `second_order_tank_implementation_playbook.md` 的推荐文件划分；
5. Agent 自己的偏好。

若第 1 项与第 2 或第 3 项冲突，不得静默选边：记录证据、影响和最小修复方案，停止当前阶段并汇报。

---

## 3. 执行纪律

### 3.1 一次只执行一个阶段

不得用一句“请完成整个文档”从阶段 0 一直做到阶段 8。每次只执行施工手册中的一个阶段，阶段门禁全部通过后再进入下一阶段。

阶段顺序不可跳跃：

```text
0 基线与可构建性
  → 1 无损 DSL 与模板状态
  → 2 固定 SVG 和对象检查器
  → 3 Wails 进程与 API ready
  → 4 REST/WebSocket 实时快照
  → 5 原子在线写值与写回 DSL
  → 6 趋势、事件和控制品质
  → 7 批量生成与导出
  → 8 全量回归与端到端验收
```

### 3.2 开始阶段前

每个阶段开始前必须：

1. 执行 `git status --short`；
2. 识别并保留用户已有修改；
3. 阅读该阶段列出的源码；
4. 运行该阶段的前置测试；
5. 列出计划修改的文件；
6. 确认没有修改核心算法或位号命名的计划。

### 3.3 实施过程中

- 优先修改已有入口，避免再建一套平行 GUI 或进程管理器。
- 新增代码按职责拆分，不把模板页面、运行状态、网络请求和趋势缓存放进一个巨型组件。
- 所有现场数值必须来自 `draftConfig` 或最新 Engine snapshot；禁止使用定时器制造假液位和假阀位。
- 所有 REST 写入成功只表示“已排队”；界面显示的新值必须由下一次 snapshot 确认。
- 不得为了让测试通过而改变 PID、VALVE、CYLINDRICAL_TANK 的工业语义。
- 不得删除或替换现有 React Flow 高级 DSL 视图。
- 不得静默覆盖内置模板。

### 3.4 阶段结束时

必须按第 6 节模板汇报，并明确给出：

- 实际修改文件；
- 真实完成项；
- 测试命令和结果；
- 尚未完成项；
- 与设计或契约的偏差；
- 是否满足本阶段门禁。

没有通过门禁时，不得宣称阶段完成，也不得自行进入下一阶段。

---

## 4. 开始前的基线检查

在 PowerShell 中从仓库根目录执行：

```powershell
git status --short
git rev-parse HEAD
python -m pytest tests\test_tank_pid_configs.py tests\test_pid_industrial.py tests\test_structured_dsl.py -q
```

安装前端依赖后执行：

```powershell
Set-Location config-tool\frontend
npm.cmd ci
npm.cmd run build
```

前端生成 `config-tool/frontend/dist` 后执行 Go 测试：

```powershell
Set-Location ..
$env:GOCACHE = Join-Path ([System.IO.Path]::GetTempPath()) 'review3-go-cache'
go test ./...
```

最后从仓库根目录执行全量 Python 测试；在较慢机器上给足至少 5 分钟：

```powershell
python -m pytest tests -q
```

### 4.1 2026-07-19 已核对的基线事实

- 目标相关 Python 测试：`75 passed`。
- 全量 Python 测试收集到 `197` 项；在 120 秒工具时限内未跑完，不是已确认的测试失败。
- 当前工作区没有安装 `config-tool/frontend/node_modules`，因此 `npm.cmd run build` 报 `tsc` 不存在。
- 当前前端源码引用 `src/lib/api`，但该目录没有被 Git 跟踪；安装依赖后仍必须先补齐 API wrapper 才可能通过 TypeScript 构建。
- `go test ./...` 在没有 `frontend/dist` 时会因 `//go:embed all:frontend/dist` 失败；应先构建前端，再跑完整 Go 测试。
- `go test ./internal/...` 可用于前端尚未构建时检查 Go 内部包。

基线问题必须在阶段 0 处理或明确记录，不能在最终回报中归因于后续功能代码。

---

## 5. 绝对停止条件

出现以下任一情况时，停止当前阶段并向用户汇报，不得自行扩大范围：

- 需要修改 `components/programs/pid.py`、`valve.py`、`cylindrical_tank.py` 的核心计算行为；
- 需要改变 `PV/SV/CSV/MV/PB/TI/TD/MODE` 等外部位号后缀；
- 需要删除现有 React Flow 组态入口；
- 只能靠假 snapshot 或前端自增动画才能继续；
- 当前工作区存在与本阶段重叠、来源不明的用户修改；
- 真实 API/Engine 行为与契约矛盾，且最小修复会影响已有外部客户端；
- 必须新增第三个独立桌面 GUI；
- 必须联网安装依赖但当前环境不允许；
- 阶段前置测试出现无法解释的新失败。

---

## 6. 每阶段统一回报模板

```text
阶段：<编号和名称>
结论：完成 / 未完成 / 被阻塞

修改文件：
- <文件>：<修改目的>

完成内容：
- <可验证行为>

测试：
- <完整命令> → <通过数/失败数/退出码>

阶段门禁：
- [x] <门禁项>
- [ ] <未通过项及原因>

遗留与偏差：
- <无则写“无”>

下一阶段建议：
- <只写下一阶段，不直接执行>
```

---

## 7. 建议交给 Agent 的单阶段提示词

```text
请先完整阅读以下文档：
1. todo/second_order_tank_agent_start_here.md
2. todo/second_order_tank_visual_dsl_template_design.md
3. todo/second_order_tank_repository_contracts.md
4. todo/second_order_tank_implementation_playbook.md

然后只执行 implementation_playbook 中的“阶段 N：<名称>”。
开始前检查 git status，保留已有修改；只读取该阶段列出的源码；不得进入下一阶段。
必须运行该阶段规定的测试，并按 start_here 第 6 节格式回报。
如果契约与当前代码冲突，停止并提供文件、行号、真实行为和最小修复建议，不要自行改需求。
```

阶段 1 之后，可以让同一 Agent 只重读本入口、契约手册相关章节和当前阶段任务卡；若更换 Agent，则仍需完整阅读四份文档。
