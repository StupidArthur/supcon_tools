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

## STAGE-5 / STAGE-6：Prospective 业务能力缺失（批次 5）

阶段 5～6 acceptance 在业务实现前锁定。下列失败为**预期契约断言失败**，不是验收基础设施错误。在业务落地前不得记录 prospective baseline。

| 类别 | 契约编号（代表） | 当前行为 | 预期行为 |
|------|------------------|----------|----------|
| 原子写 `/writes` | STAGE5-ATOMIC-001…015 | 仅有 legacy `/params` / `/override` | 整批验证、同周期应用、pending→applied/failed |
| Faceplate 模式矩阵 | STAGE5-MODE-001…006 | `PidFaceplate` 模块不存在 | AUTO/MAN/CAS 可编辑性与有效给定规则 |
| DSL 写回 | STAGE5-WRITEBACK-001…005 | 无 writeback / runtimeOverrides 表面 | 白名单写回、与 draft 隔离、禁止 PV/实时位 |
| 趋势策略 | STAGE6-TREND-006…013 | 缺 `trendPolicy` / `RuntimeTrendPanel` | heartbeat/stale 不追加、双轴、PV 绑定、stale 冻结 |
| 事件时间线 | STAGE6-EVENT-001…003 | 缺 `trendEvents` | pending/applied/failed + snapshot 确认时间 |
| 控制品质 | STAGE6-QUALITY-001…006 | 缺 `controlQuality.ts` | 误差带/超调/稳态/60s 窗/分段重置等 |

阻塞 baseline：**是**（阶段 5～6 prospective baseline 须等业务实现后全绿再记录）。

---

## 登记规则

1. 新增阻塞时追加一节，ID 格式 `STAGE-N-NNN` 或契约编号 `STAGE5-*/STAGE6-*`。
2. 不得为跑通而删除、放宽或 skip 失败用例。
3. 业务修复后由 reviewer 复跑 acceptance 并删除或标记已解决。
