# 历史方案归档

本目录下的方案文档已全部移至 [`_archive/`](./_archive/)。

历史方案基于 distributed 架构（Redis / StorageService / 前端架构），与当前 standalone 工具不匹配，仅作历史参考。

---

## 当前的 Todo 与设计决策

请回到**项目根目录**查看 [`../todo.md`](../todo.md)，那里记录了：

- 本次 code review 修复的所有 bug（B1-B7）
- SAFE STATE、namespace lag 分析等设计决策
- 端到端三层测试结论（pytest / batch / OPC UA e2e）
- distributed / Redis 依赖的清理过程
