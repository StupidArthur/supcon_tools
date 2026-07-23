# 输出强制（Output Force）

输出强制层位于运行值与 UA 发布之间，只影响 UA 输出读取，不影响引擎计算与外部写入。

## 数据流

```
Engine.step() → shared_data（运行值，不受强制影响）
                    ↓
OPC UA _poll_memory_data()
    → ForceManager.apply()（在锁内读取强制快照）
    → UA 输出值 = 强制值 ?? 运行值
                    ↓
OPC UA 节点发布
```

## 强制模式

| 模式 | 语义 |
|---|---|
| follow | 默认，UA 输出 = 运行值 |
| hold | 冻结设置时刻的运行值（后端原子捕获） |
| zero | UA 输出 = 0 |
| fixed | UA 输出 = 指定固定值 |

## 关键规则

- 强制只影响读取（UA 输出），不影响运行、写入、计算；
- 外部写 `PID.SV=1.2` 仍成功，运行值更新，但 UA 输出可仍为强制值；
- 解除强制后 UA 恢复输出当前运行值；
- 强制状态属于运行会话，停止即清除，不持久化，重启不恢复；
- `hold` 由后端在锁内读取当前运行值冻结，不使用前端旧快照；
- 可设置持续时间 `duration`（有限正数），到期自动恢复 follow。

## 合法位号

只能对实际发布到 UA 的数值位号强制（`shared_data` 数值键）。
对不存在或非数值位号设置强制返回 400。
前端位号表使用后端返回的同一份 tag 集合，不自行推断元数据键。

## 并发安全

`ForceManager` 使用锁保护强制状态。FastAPI 线程写（set/clear/clear_all），
OPC UA 轮询线程通过 `apply()` 在锁内读取快照，不直接遍历共享字典，
避免 `dictionary changed size during iteration`。

## API

- `POST /api/force` `{tag, mode, value?, duration?}`
- `DELETE /api/force/{tag}`
- `DELETE /api/force`
- `GET /api/force` → `{forces, tags}`
