# 运行时 API（Runtime API）

DataFactory 运行时暴露 HTTP + WebSocket 接口，默认绑定 loopback，启用会话令牌鉴权。

## 鉴权（阶段 9c）

每次运行生成随机 session token，通过 `--api-token` 传给 DataFactory：

- REST：`Authorization: Bearer <token>`；
- WS：`ws://host:port/ws/snapshot?token=<token>`；
- token 仅存于运行内存，不写 project，不入日志，运行结束失效；
- 开发测试开关 `DATAFACTORY_NO_AUTH=1` 可关闭鉴权；
- 绑定非 loopback 地址时打印安全警告。

## REST 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 实例名、mode、cycle_count、sim_time、cycle_time |
| GET | `/api/instances/{name}/meta` | 位号元信息 |
| GET | `/api/instances/{name}/tags` | 通用 tag catalog |
| GET | `/api/instances/{name}/snapshot` | 最新 snapshot |
| POST | `/api/instances/{name}/params` | 改算法参数 |
| POST | `/api/instances/{name}/override` | 覆写变量 |
| POST | `/api/instances/{name}/writes` | 原子写 |
| POST | `/api/force` | 设置强制 |
| DELETE | `/api/force/{tag}` | 清除单个强制 |
| DELETE | `/api/force` | 清除全部强制 |
| GET | `/api/force` | 强制状态 + 可强制 tag |
| POST | `/api/alarms/config` | 加载报警规则 |
| GET | `/api/alarms` | 报警状态 |
| POST | `/api/alarms/{id}/ack` | 确认报警 |
| POST | `/api/alarms/ack-all` | 全部确认 |
| GET | `/api/alarm-events` | 报警事件 |
| POST | `/api/archive/start` | 启动归档 |
| POST | `/api/archive/stop` | 停止归档 |
| GET | `/api/history` | 历史运行列表 |

## tag catalog（`/api/instances/{name}/tags`）

```json
{
  "ok": true,
  "tags": [
    {
      "name": "pid.PV",
      "dataType": "number",
      "description": "...",
      "instance": "pid",
      "attribute": "PV",
      "writable": true,
      "forceable": true,
      "display": true,
      "plotScaleRef": 1.2
    }
  ]
}
```

- 名称来自真实运行 meta；
- `forceable` 来自 `shared_data` 数值键；
- 不含 cycle_count / sim_time 等运行元数据；
- 排序稳定；不从名称后缀推断类型或权限。

## WebSocket（`/ws/snapshot`）

- 每周期推送一帧 snapshot（完整 dict，不包 data 层）；
- 心跳：`{"_heartbeat": true, "ts": ...}`；
- 订阅协议：`{"type": "subscribe", "tags": ["pid.PV"], "includeMeta": true}`；
- 旧客户端不发 subscribe 时保持全量；
- 订阅 tag 上限 5000，超限返回结构化错误；
- 慢消费者每客户端只保留最新帧，不阻塞 Engine。
