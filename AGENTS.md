# 工程纪律(执行 Agent 必读)

## 0. 当前开发顺序

- 冻结新的 GUI 功能开发和 GUI 联调。
- 先完成 `ua_test_gui/doc/test_cases/*.md` 定义的 419 条 Case。
- 实现顺序为 UA-1 → UA-2 → UA-3；详细规则见 `ua_test_gui/doc/case-first-plan.md`。
- 只有覆盖矩阵达到 `documented=419`、`implemented=419` 后，才恢复 GUI 工作。
- 已有 GUI / Go / SQLite 代码保留；只允许修复阻断 CLI Case 执行、报告或清理的底层问题。

## 1. 环境/工具问题不绕路

如果执行过程中发现环境问题或第三方工具(如 ua_mocker)bug:
- **说出来**,在 commit message 或报告里如实记录
- 不要绕其他路径强行修复(比如换底层、改协议、装新依赖等)
- 不要替换掉有问题的组件;让它暴露

## 2. Case 跑不过不改 Case

实现并运行 plan.md / doc/test_cases/*.md 中定义的 case 时:
- **Case 怎么写就怎么实现**,不删断言、不放宽阈值、不改步骤
- 不要为"跑通过"加 `try/except` 把错误吞掉
- 不要为"跑通过"修改用例的步骤顺序或断言条件
- 如果 case 跑不过 → 让它 fail,在 report.json / NDJSON 事件 / nightly-report.md 里如实记录真实结果

## 3. 唯一的例外:自己代码的实现 bug

- 用例代码本身有 typo / API 签名错 / 参数名错 → 修复 fixture 或 runner 框架
- 修复后必须保证 case 的步骤、断言、阈值不变
- 不许改 case 内容来"配合"框架 bug

## 4. 跑通不是目标,实现 + 真实记录才是

- 当前任务目标:把 case 需求实现一遍,产生**一轮时机测试的真实结果**
- 失败的 case 是有效产出(说明实现 + 环境的真实状态)
- 报告里要区分"代码 bug 导致 fail"vs"环境/工具限制导致 fail"vs"case 自身断言失败"