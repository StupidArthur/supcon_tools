# 运行归档（Run History）

可选功能，默认关闭。开启后记录选定 tag 的真实运行值，供事后回放与导出。

## 目录格式

```
<UserCacheDir>/DataFactory/run_history/<session-id>/
  metadata.json    # 会话信息、project/runtime revision、记录 tag、采样时间
  values.sqlite    # 真实运行值（仅选定 tag）
  alarms.jsonl     # 报警事件与用户写入审计事件
```

## 记录范围

- 不记录全部位号；只记录用户选定或 `display=true` 的 tag；
- 记录：session 信息、project/runtime revision、选择的历史 tag、采样时间、真实运行值、报警事件、用户写入事件；
- 不持久化 force 状态；可记录"发生过强制操作"的审计事件，但重启后不恢复强制。

## 功能

- 历史运行列表（按时间倒序）；
- 打开历史趋势（读取 values.sqlite）；
- 导出 CSV；
- 删除历史运行（防路径穿越）；
- 磁盘空间统计；
- 归档失败不影响 Engine 实时运行（record 异常被隔离）。

## API

- `POST /api/archive/start` `{sessionId, tags, metadata}` 启动归档；
- `POST /api/archive/stop` 停止；
- `GET /api/history` 列表 + 磁盘占用；
- `GET /api/history/{id}/values` 读取值；
- `POST /api/history/{id}/export` 导出 CSV；
- `DELETE /api/history/{id}` 删除。

## 启用

启动工程时通过 `RealtimeStartOptions.archiveEnabled` + `archiveTags` 开启。
