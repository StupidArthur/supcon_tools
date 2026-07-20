# Acceptance Blocked 登记

本文件记录 reviewer acceptance 套件暴露的**业务契约阻塞**。验收基础设施 Agent 只登记、不修业务。

| 字段 | 说明 |
|------|------|
| 阶段 | manifest stage |
| 测试 | 完整 pytest/vitest/go test 名称 |
| 期望 | 契约要求 |
| 当前行为 | 实测结果 |
| 业务文件 | 需由业务 Agent 修改的路径 |
| 代码位置 | 相关行号（登记时快照） |
| 阻塞 baseline | 是否阻止 `--record-baseline` / finalize |

---

## STAGE-2-001：Space 键无法选择 P&ID 对象

| 字段 | 内容 |
|------|------|
| 阶段 | 2 |
| 测试 | `stage 2 pid diagram acceptance > documents Space keyboard selection contract` |
| 套件文件 | `config-tool/frontend/acceptance/stage_2/pid_diagram.acceptance.test.tsx` |
| 期望 | `todo/7.md` §九：Enter **与 Space** 均可选择流程图对象（可访问性契约） |
| 当前行为 | 仅 `Enter` 触发 `onClick()`；`Space` 的 `keyDown` 不调用 `onSelect` |
| 业务文件 | `config-tool/frontend/src/features/templates/secondOrderTank/SecondOrderTankDiagram.tsx` |
| 代码位置 | 约 392、456、534、644、684 行：`onKeyDown={(e) => e.key === 'Enter' && onClick()}` |
| 最小失败输出 | `AssertionError: expected "spy" to be called with arguments: [ 'valve_1' ]` / `Number of calls: 0` |
| 建议修复范围 | 所有可聚焦 P&ID 符号（`source-flow`、`valve-1`、Tank、LT、PID 等）的键盘处理：`Enter` 与 `Space` 均调用 `onClick()`，并 `e.preventDefault()` 避免页面滚动；保持 `tabIndex={0}` 与选中态 ARIA 不变 |
| 阻塞 baseline | **是** — 阶段 2 不得 record retrospective baseline / attest / finalize，直至修复后 reviewer suite 全绿 |

### 复现命令

```powershell
Set-Location config-tool\frontend
npm run test:acceptance -- acceptance/stage_2/pid_diagram.acceptance.test.tsx -t "Space keyboard"
```

---

## STAGE-5 / STAGE-6：Prospective 业务能力缺失（批次 5 / 5.1）

阶段 5～6 acceptance 锁定**公共行为**（见 `CONTRACT_SURFACES.md`），不锁定内部 helper/文件名。  
当前失败为预期契约断言（路由/组件/Binding 方法尚未实现），不是验收基础设施错误。

| 类别 | 契约编号 | 当前行为 | 预期行为 |
|------|----------|----------|----------|
| HTTP `/writes` | STAGE5-ATOMIC-001…015 | 无 `/writes`；仅有 `/params` | 整批验证、同周期确认、pending→applied/failed |
| PidFaceplate UI | STAGE5-MODE-002…006 | 组件不存在 | AUTO/MAN/CAS 可编辑性与状态展示 |
| `submitAtomicWrites` | STAGE5-ATOMIC-*（前端） | 模块不存在 | mock fetch 行为契约 |
| `ApplyRuntimeOverrides` | STAGE5-WRITEBACK-001…005 | Binding 方法不存在 | 白名单写回、拒 PV/实时位 |
| `computeControlQuality` | STAGE6-QUALITY-* | 模块不存在 | 数值 fixture 指标正确 |
| `RuntimeTrendPanel` | STAGE6-TREND/EVENT-* | 组件不存在 | 双轴、事件、stale 冻结 |

阻塞 baseline：**是**（prospective baseline 须等业务实现后全绿）。

---

## STAGE-7 / STAGE-8：Prospective 业务能力缺失（批次 6）

| 类别 | 契约编号 | 当前行为 | 预期行为 |
|------|----------|----------|----------|
| Batch 唯一临时目录 | STAGE7-BATCH-003/004/008 | 无 `AllocateBatchWorkDir` | 每任务唯一路径、并发不覆盖、清理 |
| 实时/Batch 互斥 | STAGE7-STATE-001…005 | 无 `CanRunBatch` / `batchState` | dirty/校验/运行态互斥 |
| Batch UI | STAGE7-BATCH / CSV | 无 BatchPanel / dialog 模块 | 同页入口、CSV 导出、失败不空成功 |
| E2E 闭环 | STAGE8-E2E-001…029 | 多数步骤能力未就绪 | 场景 JSON 全步骤可自动执行并清理 |

阻塞 baseline：**是**

---

## 登记规则

1. 新增阻塞时追加一节，ID 格式 `STAGE-N-NNN` 或契约编号 `STAGE5-*/STAGE6-*`。
2. 不得为跑通而删除、放宽或 skip 失败用例。
3. 业务修复后由 reviewer 复跑 acceptance 并删除或标记已解决。
