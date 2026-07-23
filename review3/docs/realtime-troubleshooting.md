# 实时运行故障排查（Troubleshooting）

## 启动失败

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 编译工程失败 | DSL 解析错误 / 实例重名 | 查看返回的 duplicates，修改 DSL 实例名 |
| API ready 超时 | 端口占用 / Python 依赖缺失 | 检查 OPC UA / REST 端口，查看日志 |
| instance_name 不匹配 | runtimeName 配置错误 | 确认启动参数 runtimeName |
| 进程提前退出 | 配置非法 / 组件注册失败 | 查看最近日志（stderr） |

## 连接与数据

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 连接断开 | DataFactory 停止 / 网络 | 确认进程运行，检查 REST 可达 |
| 数据已过期（stale） | 长时间未收到 snapshot | 检查 Engine 是否卡死，stale 阈值 = max(3×cycle_time, 2s) |
| 位号表为空 | 未运行 / tag catalog 未加载 | 先启动运行，确认 `/api/.../tags` 返回 |
| 401 未授权 | session token 缺失/失效 | 重启运行以生成新 token |

## 强制

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 设置强制返回 400 | 位号不存在/非数值 | 只对真实数值位号强制 |
| 强制到期未恢复 | duration 非法 | duration 必须是有限正数 |
| UA 输出与运行值不同 | 存在强制 | 查看位号表"强制"列，恢复跟随 |

## 报警

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 报警不触发 | 规则 disabled / tag 缺失 / 未达 delay | 检查 enabled、tag、delay_seconds |
| 报警值异常 | 非有限值被忽略 | 确认 tag 输出有限数值 |

## 临时文件

- 会话目录在 `<UserCacheDir>/DataFactory/realtime_runs/`；
- 应用启动时自动清理无存活进程的遗留目录；
- 若磁盘占用高，检查 `run_history/` 归档并清理。

## 兼容性

- 单 YAML 旧运行入口保留；
- 旧 WS 客户端不发 subscribe 时保持全量快照；
- 二阶水箱专用页面通过 legacy selector 继续工作，通用实时工程不依赖固定字段。

## 常见错误代码

```
REALTIME_PROJECT_NOT_FOUND   工程不存在
REALTIME_COMPILE_FAILED      编译失败
REALTIME_START_FAILED        启动失败
REALTIME_SESSION_CONFLICT    会话冲突（已有进程/批量任务）
REALTIME_SESSION_NOT_RUNNING 无运行会话
REALTIME_TAG_NOT_FOUND       位号不存在
REALTIME_FORCE_INVALID       强制参数非法
REALTIME_ALARM_INVALID       报警规则非法
REALTIME_DASHBOARD_INVALID   画面配置非法
REALTIME_API_UNAVAILABLE     运行时 API 不可用
```
