# 运行会话（Realtime Run Session）

每次启动实时运行都创建一个独立的受管会话，编译产物与进程生命周期绑定。

## 会话目录

```
<UserCacheDir>/DataFactory/realtime_runs/<session-id>/
  compiled.yaml      # 编译后的单一 DSL
  session.json       # 会话元数据
```

`session.json`：

```json
{
  "sessionId": "...",
  "ownerPid": 1234,
  "childPid": 5678,
  "sourceKind": "project",
  "projectId": "...",
  "runtimeRevision": "...",
  "compiledConfigPath": "...",
  "createdAt": "...",
  "state": "running"
}
```

## 启动事务（StartProject）

后端原子完成：

```
检查无实时进程/批量任务
→ 加载工程
→ 计算 runtimeRevision
→ 创建唯一会话目录（UUID）
→ 编译到 compiled.yaml
→ 调用 SystemBinding.Start
→ 等待 API ready
→ 读取 SystemStatus（configHash / startedAt 取自此处）
→ 写 session.json
→ 推送 alarm 配置（若工程有报警规则）
→ 启动归档（若启用）
```

任一步骤失败：停止可能已启动的进程 → 删除本次会话目录 → 清除内存会话 → 返回原始错误。

## 会话状态

```
preparing → starting → running → stopping → exited
                    ↘ failed
```

`configHash` 与 `startedAt` 始终取自 `SystemBinding.Status()`，不另行推算。

## 临时文件清理

- 每次启动生成全新 UUID 目录，不覆盖上一轮产物；
- 编译失败 / 启动失败 / 正常停止 / 异常退出 → 删除目录；
- Wails 应用关闭：先停子进程，再删目录；
- 应用启动时清理无存活 owner/child 进程的遗留目录；
- 清理逻辑不删除当前活跃会话。

## 组态变更提示

运行中若 `currentProject.runtimeRevision != session.runtimeRevision`，
前端提示"当前工程组态已修改，停止并重新启动后生效"。不做热更新。

## 来源类型

- `project`：来自实时工程（编译多 YAML）；
- `single-yaml`：来自单个 DSL 文件（旧入口，保留）。
