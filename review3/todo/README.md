# Todo 与实施文档索引

## 单阀门二阶水箱可视化 DSL 模板

交给 Coding Agent 时按以下顺序阅读：

1. [`second_order_tank_agent_start_here.md`](./second_order_tank_agent_start_here.md)：Agent 入口、执行纪律、基线和单阶段提示词。
2. [`second_order_tank_visual_dsl_template_design.md`](./second_order_tank_visual_dsl_template_design.md)：产品设计、交互、视觉、非目标和总体验收标准。
3. [`second_order_tank_repository_contracts.md`](./second_order_tank_repository_contracts.md)：基于当前代码核对后的 DSL、字段、状态机、Wails、API、WebSocket 和测试契约。
4. [`second_order_tank_implementation_playbook.md`](./second_order_tank_implementation_playbook.md)：阶段 0～8 的施工卡、允许修改范围、测试和退出门禁。

不要让能力一般的 Agent 一次执行全部阶段。每次只指定一张阶段任务卡，门禁通过后再开始下一阶段。

---

## 历史方案归档

本目录下不再适用的旧版方案文档已移至 [`_archive/`](./_archive/)。

历史方案基于 distributed 架构（Redis / StorageService / 前端架构），与当前 standalone 工具不匹配，仅作历史参考。

---

## 当前的 Todo 与设计决策

请回到**项目根目录**查看 [`../todo.md`](../todo.md)，那里记录了：

- 本次 code review 修复的所有 bug（B1-B7）
- SAFE STATE、namespace lag 分析等设计决策
- 端到端三层测试结论（pytest / batch / OPC UA e2e）
- distributed / Redis 依赖的清理过程
