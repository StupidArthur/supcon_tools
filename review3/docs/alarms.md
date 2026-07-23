# 报警系统（Alarms）

项目报警分两部分：组态（alarms.yaml，阶段 7a）与运行评估（AlarmManager，阶段 7b）。

## 报警配置（alarms.yaml）

每个实时工程一个 `alarms.yaml`，不写入源 DSL：

```yaml
version: 1
rules:
  - id: <uuid>
    name: 水位高高
    tag: tank.level
    direction: high        # high | low
    limit: 1.1
    severity: critical     # info | warning | high | critical
    delay_seconds: 2
    deadband: 0.02
    enabled: true
    message: 二号罐液位超过高高限
```

校验：ID 唯一、tag 非空、limit 有限、deadband 有限非负、delay 有限非负、
direction/severity 合法、名称非空。写入使用临时文件 + 原子替换。
报警规则属于运行组态，纳入 `runtimeRevision`。

## 状态机

```
normal → pending → active_unacked → active_acked
                 ↘ returned_unacked ↗
```

高报警：

```
value >= limit            → pending
持续 delay_seconds        → active_unacked
value < limit - deadband  → returned_unacked（曾激活）或 normal
```

低报警方向相反。

确认规则：

- `active_unacked` 确认 → `active_acked`；
- `active_acked` 条件恢复 → `normal`；
- `active_unacked` 未确认但恢复 → `returned_unacked`；
- `returned_unacked` 确认 → `normal`。

## 运行语义

- 报警使用真实运行 snapshot，不使用 UA 强制输出；
- 计时使用 monotonic clock，事件时间同时记录 wall-clock ISO；
- 报警计算异常不阻塞 Engine 周期（单条异常被隔离）；
- 事件缓冲限制最近 5000 条。

## API

- `POST /api/alarms/config` 加载规则（启动工程时由 Go 推送）；
- `GET /api/alarms` 报警状态；
- `POST /api/alarms/{id}/ack` 确认；
- `POST /api/alarms/ack-all` 全部确认；
- `GET /api/alarm-events` 事件列表。

## 前端

运行页报警面板：活跃报警条、按严重程度排序、未确认数量、单条/全部确认、
最近事件、搜索与严重程度过滤、断线/过期状态。颜色与文字同时使用。
