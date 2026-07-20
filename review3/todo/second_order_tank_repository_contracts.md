# 单阀门二阶水箱模板：仓库事实与实现契约

> 本文把产品设计中分散的约束整理成可直接编码和测试的契约，并记录当前仓库的真实基线。
>
> “现状”描述核对提交 `e6118bdecc1b8bfc061f3eed3a3ec13f9d45a133`；“规范”是本任务完成后必须满足的行为。

---

## 1. 术语和真源

| 术语 | 含义 | 真源 |
|---|---|---|
| 运行实例名 `runtimeName` | `standalone_main.py --name` 指定的单个 Engine/API 实例，默认 `default` | `/api/status.instance_name` |
| Program 实例名 | DSL `program[].name`，例如 `pid2`、`tank_2` | YAML 和 Engine `_instances` |
| 位号 `tag` | Variable 名或 `Program实例.属性`，例如 `source_flow`、`pid2.SV` | Engine snapshot/meta |
| 保存配置 `savedConfig` | 磁盘上最近成功保存并重新读回的 DSL | 磁盘文件及其 hash |
| 草稿配置 `draftConfig` | 当前界面编辑内容，可能尚未保存 | 模板 Zustand store |
| 运行配置标识 `runningConfigIdentity` | 当前子进程启动时采用的绝对路径、内容 hash 和启动时间 | Wails 启动记录 |
| 最新快照 `latestSnapshot` | Engine 最近一次真实 snapshot | REST/WS |
| 在线调参 | 只改变当前 Engine 实例，不自动改变磁盘 DSL | Engine 写队列 |

运行实例名和 Program 实例名不是同一个命名空间。路径 `/api/instances/{runtimeName}/...` 中的参数必须等于 `/api/status.instance_name`；写入 `pid2.PB` 时，再由请求体中的 tag 定位 Program 实例 `pid2`。

---

## 2. 当前仓库事实

### 2.1 入口和职责

| 层 | 当前入口 | 本任务职责 |
|---|---|---|
| Wails 桌面 | `config-tool/main.go` | 唯一用户入口、文件对话框、子进程生命周期 |
| React | `config-tool/frontend/src/App.tsx` | 默认进入固定模板工作区，保留现有高级视图 |
| 通用 DSL | `config-tool/internal/config`、React Flow 组件 | 继续可用，不承担固定 P&ID 主画面 |
| 运行入口 | `standalone_main.py` | 用 `--api` 启动 Engine、FastAPI、WebSocket 和 OPC UA |
| 内部实时 API | `datacenter/engine_api.py` | status/meta/snapshot/writes/export/WS |
| 唯一运行状态 | `controller/engine.py` | 周期计算、下一周期边界应用写值、构建 snapshot |
| 外部工业接口 | `datacenter/opcua_server.py` | 对外 OPC UA，GUI 不通过它轮询 |

### 2.2 已存在但不能直接假定可用的能力

- `SystemBinding.Start` 当前只传 `-c`、`--port`、`--mode`、`--cycle-time`，没有传 `--api`、`--api-port` 或 `--name`。
- `SystemBinding` 当前只查找 `DataFactory.exe`；不得复制 `debug_gui` 再形成第二套长期进程管理实现。
- `datacenter/engine_api.py` 已有 status、meta、snapshot、单参数更新、override、export 和 WebSocket。
- 当前 `/api/instances/{name}/params` 先用 `{name}` 校验运行实例，随后又把同一个 `{name}` 传给 `queue_param_update()`；这无法正确写入 `pid2`，必须由新的原子 writes 接口替代模板调用。
- Engine 在 `_step_once()` 开头调用 `_apply_pending_changes()`，适合实现“同一周期边界应用整批写值”。
- 当前 `config-tool/internal/config.CanvasState` 不表示 `display_args`，通用 `ImportYAML → ExportYAML` 会丢失该字段。模板保存不得直接复用这一有损路径。
- 当前 `config-tool/frontend/src` 引用了 `src/lib/api`，但 Git 中不存在该目录。阶段 0 必须恢复一个薄 API wrapper。
- `config-tool/internal/config/components.json` 是静态生成物，PID 内容已经落后于 Python 真实类。模板字段语义以 Python `stored_attributes/default_params/input_schema/param_descriptions` 和运行时 `/meta` 为准。

---

## 3. 固定 DSL 身份和拓扑

规范基础文件：

```text
config/单阀门二阶水箱.yaml
```

必须识别以下固定项，名称和类型区分大小写后的比较应兼容当前 YAML：

| name | type | 固定输入 |
|---|---|---|
| `source_flow` | `Variable` | 无；值位于顶层字段 `value` |
| `valve_1` | `VALVE` | `target_opening: pid2.MV`；`inlet_flow: source_flow` |
| `tank_1` | `CYLINDRICAL_TANK` | `inlet_flow: valve_1.outlet_flow` |
| `tank_2` | `CYLINDRICAL_TANK` | `inlet_flow: tank_1.outlet_flow` |
| `pid2` | `PID` | `PV: tank_2.level`；`execute_first: true` |

模板可编辑参数不得改变 name、type、program 数量、program 顺序、inputs 或 `execute_first`。这些字段可以显示为只读。

导入不符合上述身份的 YAML 时，不得“尽量画一个相似模板”；返回结构化错误并建议打开高级 DSL 视图。

---

## 4. 无损 DSL 读写契约

### 4.1 规范策略

固定模板使用单独的无损模板服务，不能通过 `CanvasState` 重建 YAML。推荐在 `config-tool/internal/config` 中使用 `yaml.v3.Node`：

1. 加载原始 YAML 节点树；
2. 校验固定身份和字段类型；
3. 提取前端需要的规范化值；
4. 保存时只修改白名单 YAML 路径；
5. 保留未修改的 `display_args`、`inputs`、`execute_first`、未知键和注释；
6. 写入同目录临时文件，成功后原子替换目标文件；
7. 用 Python `DSLParser.parse_file()` 等价校验保存结果能够运行；若 Go 无法直接调用 Python，则至少由 Go 做结构校验，并在“保存并启动”前用子进程解析失败阻止启动；
8. 保存成功后从磁盘重新加载，新的结果才成为 `savedConfig`。

不得把前端私有 JSON 当作唯一配置文件。

### 4.2 建议 Wails DTO

```text
TemplateDocument
  path: string                 绝对路径
  contentHash: string          UTF-8 原始内容 SHA-256
  config: TemplateConfig       规范化字段
  topology: TemplateTopology   只读身份和 inputs
  warnings: string[]

TemplatePatch
  path: string                 只允许第 5 节白名单路径
  value: number

SaveTemplateRequest
  sourcePath: string
  targetPath: string
  expectedHash: string         防止覆盖磁盘上的外部修改
  patches: TemplatePatch[]
  allowOverwrite: boolean
```

如果 `expectedHash` 与磁盘不一致，返回冲突错误，不得覆盖。内置模板第一次保存必须走“另存为”；只有用户方案且用户明确确认时 `allowOverwrite=true`。

---

## 5. UI 字段、YAML 路径和运行位号

### 5.1 时钟与水源

| UI | YAML 路径 | 运行位号 | 单位 | 编辑 | 生效 |
|---|---|---|---|---|---|
| 控制周期 | `clock.cycle_time` | 无 | s | `> 0` | 重启 |
| 水源流量 | `program.source_flow.value` | `source_flow` | UI 为 L/min，DSL 为 m³/s | `>= 0` | 重启 |

换算：`L/min = m³/s × 60000`；`m³/s = L/min ÷ 60000`。默认 `0.0012 m³/s = 72 L/min`。

### 5.2 阀门

| UI | YAML 路径 | 快照位号 | 单位 | 编辑 | 生效 |
|---|---|---|---|---|---|
| 满行程时间 | `program.valve_1.params.full_travel_time` | `valve_1.full_travel_time` | s | `>= 0` | 重启 |
| 初始开度 | `program.valve_1.params.initial_opening` | `valve_1.initial_opening` | % | `[min,max]` | 重启 |
| 流量系数 | `program.valve_1.params.flow_coefficient` | `valve_1.flow_coefficient` | 1 | `>= 0` | 重启 |
| 最小/最大开度 | 可缺省，分别取 `0/100` | `valve_1.min_opening/max_opening` | % | `min < max` | 重启 |
| 当前/目标开度 | 不保存为结构参数 | `valve_1.current_opening/target_opening` | % | 只读 | snapshot |
| 入口/出口流量 | 不保存为结构参数 | `valve_1.inlet_flow/outlet_flow` | m³/s | 只读 | snapshot |

### 5.3 水箱

对 `tank_1`、`tank_2` 同样适用：

| UI | YAML 路径后缀 | 快照后缀 | 单位 | 编辑 | 生效 |
|---|---|---|---|---|---|
| 高度 | `params.height` | `.height` | m | `> 0` | 重启 |
| 半径 | `params.radius` | `.radius` | m | `> 0` | 重启 |
| 出口面积 | `params.outlet_area` | `.outlet_area` | m²；UI 可辅显 mm | `> 0` | 重启 |
| 初始液位 | `params.initial_level` | `.initial_level` | m | `[0,height]` | 重启 |
| 当前液位 | 不写回 | `.level` | m | 只读 | snapshot |
| 入口/出口流量 | 不写回 | `.inlet_flow/.outlet_flow` | m³/s | 只读 | snapshot |

换算：`diameter_mm = 2 × sqrt(outlet_area / π) × 1000`；容量 `volume_L = π × radius² × height × 1000`。

### 5.4 PID

YAML 基址：`program.pid2.params`；运行位号基址：`pid2`。

| 参数 | 类型/范围 | UI 在线写 | DSL 写回 | 备注 |
|---|---|---:|---:|---|
| `PV` | finite | 否 | 否 | 来自 `tank_2.level` |
| `SV` | finite 且 `[SVL,SVH]` | 是 | 是 | AUTO 有效；CAS 时只更新返回 AUTO 后的本地 SV |
| `CSV` | finite 且量程合法 | 可显示，首版不开放 | 否 | CAS/RCAS 有效 |
| `MV` | finite 且 `[MVL,MVH]` | 仅手动类 MODE | 仅用户显式勾选 | AUTO 下禁用输入 |
| `PB` | finite 且 `> 0` | 是 | 是 | 比例度，`Kp=100/PB` |
| `TI` | finite 且 `>= 0` | 是 | 是 | 秒，0 关闭积分 |
| `TD` | finite 且 `>= 0` | 是 | 是 | 秒，0 关闭微分 |
| `KD` | finite 且 `> 0` | 是 | 是 | 微分滤波系数 |
| `MODE` | 整数 `1..8` | 是 | 是 | 4=MAN，5=AUTO，6=CAS |
| `SWPN` | `0` 或 `1` | 是 | 是 | 1=反作用 |
| `SVSCL/SVSCH` | finite，低值 < 高值 | 是 | 是 | 工程量程 |
| `SVL/SVH` | 位于工程量程且低值 <= 高值 | 是 | 是 | SV 操作限幅 |
| `MVSCL/MVSCH` | finite，低值 < 高值 | 是 | 是 | MV 工程量程 |
| `MVL/MVH` | 位于工程量程且低值 <= 高值 | 是 | 是 | MV 输出限幅 |
| `AUTO/CAS` | 派生 | 否 | 否 | 禁止编辑和写回 |

手动类 MODE：`2,3,4,8`；自动类 MODE：`5,6,7`。UI 首版重点支持 4、5、6，但不得把其他合法值改写成非法值。

---

## 6. 配置校验契约

### 6.1 阻止保存和启动的错误

- 固定 program 缺失、重复、类型不符或 inputs 被修改；
- 任意数值为 NaN/Inf 或不能解析为目标类型；
- `cycle_time <= 0`；
- 水箱 `height/radius/outlet_area <= 0`；
- `initial_level < 0` 或 `initial_level > height`；
- 阀门 `min_opening >= max_opening` 或初始开度越界；
- PID 参数违反第 5.4 节范围；
- `pid2.SVH > tank_2.height`、`pid2.SV > tank_2.height`，或 SV 相关限值无法随高度安全联动；
- 目标稳态流量超过水源最大供给；
- 预计 Tank 1 稳态液位超过 Tank 1 高度。

### 6.2 警告但允许保存

- 当前目标流量需要阀位接近上下限，例如 `< 5%` 或 `> 95%`；
- 稳态 Tank 1 液位接近高度上限，例如超过高度的 `90%`；
- 初始液位与目标液位差异很大；
- `TD/TI` 或 PB 等参数虽合法但明显偏离默认工况。

保存允许警告；“保存并仿真/实时运行”遇到警告必须由用户确认。错误不可绕过。

### 6.3 稳态预检查公式

使用当前模型的托里拆利关系：

```text
q2_target = outlet_area_2 × sqrt(2 × g × SV)
required_valve_percent = q2_target / (source_flow × flow_coefficient) × 100
tank1_steady_level = (q2_target / outlet_area_1)² / (2 × g)
g = 9.81 m/s²
```

默认工况允许小的显示四舍五入，自动测试建议容差：阀位 ±1%，Tank 1 稳态液位 ±0.01 m。

---

## 7. 模板状态机

### 7.1 状态

```text
STOPPED_EDITING
STARTING
SIMULATION_RUNNING
REALTIME_RUNNING
BATCH_RUNNING
STOPPING
ERROR
```

### 7.2 转换表

| 当前状态 | 事件 | 守卫 | 原子动作 | 成功状态 | 失败状态 |
|---|---|---|---|---|---|
| 任意非运行 | LOAD | 文件可读且模板身份合法 | 读取磁盘；同时设置 saved/draft；清 dirty | STOPPED_EDITING | ERROR，保留旧文档 |
| STOPPED_EDITING | EDIT | 字段可编辑 | 只改 draft；更新 dirtyPaths 和校验 | STOPPED_EDITING | 不转换 |
| STOPPED_EDITING | SAVE | 无校验错误；覆盖策略允许 | 原子写盘；重新加载；更新 saved/hash | STOPPED_EDITING | ERROR，draft 不丢失 |
| STOPPED_EDITING | SAVE_AND_SIMULATE | SAVE 成功 | 设置 STARTING；启动 `--api`；等待 status ready；记录 running identity；连 WS | SIMULATION_RUNNING | ERROR，并清理子进程 |
| SIMULATION_RUNNING | SAVE | 无校验错误 | 只更新磁盘 saved；不改 running identity | SIMULATION_RUNNING | 保持运行并显示错误 |
| SIMULATION_RUNNING | RESTART | SAVE 成功 | STOPPING；归档趋势；停旧进程；启动新进程；ready；连 WS | SIMULATION_RUNNING | ERROR |
| STOPPED_EDITING | START_REALTIME | saved 与 draft 一致且合法 | STARTING；启动 REALTIME + API + OPC UA；ready；连 WS | REALTIME_RUNNING | ERROR |
| 运行中 | ONLINE_WRITES | WS 新鲜且写值合法 | 一次 REST 批量入队；记录 pending 事件；等 snapshot 确认 | 原状态 | 原状态并显示错误 |
| 运行中 | STOP | 有受管进程 | STOPPING；断 WS；停止进程；冻结快照 | STOPPED_EDITING | ERROR |
| STOPPED_EDITING | RUN_BATCH | saved 与 draft 一致且合法 | BATCH_RUNNING；独立 batch 子进程；读取结果 | STOPPED_EDITING | ERROR |
| ERROR | RECOVER | 无残留受管进程 | 清运行错误，保留 draft | STOPPED_EDITING | ERROR |

`STARTING` 期间不得显示“运行中”。`latestSnapshot` 与 `draftConfig` 永不互相覆盖。WS 断开后冻结最后值并标记 stale。

### 7.3 一致性标记

- `draftEqualsSaved = dirtyPaths.length === 0`；
- `savedEqualsRunning = saved.contentHash === runningConfigIdentity.contentHash`；
- 在线调参另存为 `runtimeOverrides`，不能伪装成 draft；
- 页面必须能同时显示这三种差异。

---

## 8. Wails 进程契约

### 8.1 启动参数规范

`SystemBinding.Start` 的模板启动至少需要以下 DTO 字段：

```text
configPath: string
runtimeName: string       默认 second_order_tank
mode: REALTIME            调试仿真和实时运行都逐周期运行
cycleTime: number
port: number              OPC UA 端口，保留现字段兼容性
apiHost: 127.0.0.1
apiPort: number           默认 8000，与 OPC UA 端口不同
enableOpcUa: boolean      若 standalone 暂不支持关闭，可先记录但不得伪报关闭
```

实际命令必须包含：

```text
DataFactory.exe -c <absolute-yaml> --name second_order_tank --mode REALTIME
  --cycle-time <seconds> --port <opc-port>
  --api --api-host 127.0.0.1 --api-port <api-port>
```

如果开发模式使用 Python，等价命令为：

```text
python standalone_main.py -c <absolute-yaml> --name second_order_tank --mode REALTIME
  --cycle-time <seconds> --port <opc-port>
  --api --api-host 127.0.0.1 --api-port <api-port>
```

### 8.2 ready 和停止

- 子进程启动后轮询 `GET /api/status`，建议每 100 ms 一次，最长 10 s；
- 只有 HTTP 200 且 `instance_name` 等于请求的 runtimeName 才 ready；
- 超时、进程提前退出或名称不一致时，终止受管子进程并返回 stderr、退出码和最近日志；
- 同一 `SystemBinding` 同时最多一个实时受管进程；
- `Stop` 必须等待进程退出，超时后才强制 Kill；
- Wails `OnShutdown` 必须调用进程清理，而不只是 cancel context；
- 状态至少返回 `running/apiReady/pid/configPath/runtimeName/mode/cycleTime/port/apiPort/startedAt/configHash/lastError`。

---

## 9. FastAPI 和 WebSocket 规范

### 9.1 读取接口

沿用：

```text
GET /api/status
GET /api/instances/{runtimeName}/meta
GET /api/instances/{runtimeName}/snapshot
POST /api/instances/{runtimeName}/export
WS /ws/snapshot
```

前端先调用 status 获取真实 `runtimeName`，后续不得假定它等于 `pid2`。

### 9.2 原子批量写接口

新增：

```text
POST /api/instances/{runtimeName}/writes
```

请求：

```json
{
  "writes": [
    {"tag": "pid2.PB", "value": 40.0},
    {"tag": "pid2.TI", "value": 100.0},
    {"tag": "pid2.TD", "value": 10.0}
  ]
}
```

成功响应：

```json
{
  "ok": true,
  "queued": 3,
  "apply_semantics": "next_cycle_boundary"
}
```

规范要求：

1. 整批先验证 runtimeName、writes 非空、tag 存在、值有限、字段在运行写白名单且范围合法；
2. 任一条失败则 HTTP 422，整批零入队；
3. 成功时在一次 Engine 锁内加入同一批队列；
4. Engine 在下一次 `_step_once()` 开头一次应用整批；
5. API 成功不代表最终值已生效；前端等待后续 snapshot 确认；
6. 非法 tag 不得静默成功；
7. `MV` 在非手动类 MODE 下拒绝或由 UI 禁用，后端仍需校验，不能只依赖前端。

失败示例：

```json
{
  "detail": {
    "code": "INVALID_WRITES",
    "errors": [
      {"index": 1, "tag": "pid2.UNKNOWN", "message": "tag 不存在或不可写"}
    ]
  }
}
```

### 9.3 快照

WS 正常消息就是完整 snapshot 对象，不再额外包一层 `data`。至少依赖：

```text
cycle_count, sim_time, source_flow
valve_1.target_opening, valve_1.current_opening
valve_1.inlet_flow, valve_1.outlet_flow
tank_1.level, tank_1.inlet_flow, tank_1.outlet_flow
tank_2.level, tank_2.inlet_flow, tank_2.outlet_flow
pid2.PV, pid2.SV, pid2.CSV, pid2.MV
pid2.PB, pid2.TI, pid2.TD, pid2.KD, pid2.MODE, pid2.SWPN
```

心跳消息沿用：

```json
{"_heartbeat": true, "ts": 1784460000.0}
```

心跳只更新连接活性，不写入趋势，不覆盖 latestSnapshot。若连续 `max(3 × cycle_time, 2s)` 没有真实 snapshot，则标记数据 stale；断线指数退避重连，重连成功后先 GET snapshot 再接续 WS。

当前 broadcaster 队列满时注释称“丢最旧”，实现实际上会跳过新帧。允许在实时接入阶段修正为每客户端只保留最新值或真正丢最旧值，但不得阻塞 Engine。

---

## 10. 趋势、事件和批量结果

- 实时趋势使用固定容量环形缓冲，默认最近 1200 个真实 snapshot；
- 心跳不进入缓冲；
- 新运行开始时，上一轮缓冲移动到 `previousRunSeries`，只保留一轮灰色对照；
- 参数提交先记录 pending 事件，snapshot 确认后标记 applied，失败或超时标记 failed；
- 液位和百分比分到不同 Y 轴；
- 默认曲线为 `tank_2.level`、`pid2.SV`、`pid2.MV`、`valve_1.current_opening`，图例注明 `pid2.PV ← tank_2.level`；
- 批量 CSV 可以包含大量行，但交给 Recharts 前必须下采样到不超过 3000 点；
- 下采样必须保留第一点、最后一点，以及每个桶的局部最小值和最大值，不能只取固定步长导致尖峰消失。

控制品质首版定义：误差带 `max(0.01m, abs(SVSCH-SVSCL)×2%)`；连续 60 s 位于误差带内为稳定。在线参数变化后重新开始当前统计并保留上一段结果。

---

## 11. 测试夹具和容差

### 11.1 默认配置断言

```text
cycle_time = 0.5 s
source_flow = 0.0012 m³/s = 72 L/min
tank_1/tank_2 volume ≈ 84.823 L
tank_1 initial_level = 0.15 m
tank_2 initial_level = 0.10 m
pid2.SV = 0.8 m
expected valve ≈ 66%
expected tank_1 steady level ≈ 0.512 m
```

浮点测试建议：通用换算绝对误差 `1e-9`；显示值按 UI 精度断言；稳态预测使用第 6.3 节容差。

### 11.2 最小 snapshot fixture

```json
{
  "cycle_count": 1,
  "sim_time": 0.5,
  "source_flow": 0.0012,
  "valve_1.target_opening": 66.0,
  "valve_1.current_opening": 4.1666667,
  "valve_1.inlet_flow": 0.0012,
  "valve_1.outlet_flow": 0.00005,
  "tank_1.level": 0.149,
  "tank_1.inlet_flow": 0.00005,
  "tank_1.outlet_flow": 0.000429,
  "tank_2.level": 0.102,
  "tank_2.inlet_flow": 0.000429,
  "tank_2.outlet_flow": 0.00028,
  "pid2.PV": 0.102,
  "pid2.SV": 0.8,
  "pid2.CSV": 0.0,
  "pid2.MV": 66.0,
  "pid2.PB": 30.0,
  "pid2.TI": 90.0,
  "pid2.TD": 20.0,
  "pid2.KD": 10.0,
  "pid2.MODE": 5,
  "pid2.SWPN": 1
}
```

fixture 用于前端组件绑定测试，不代表第一周期真实物理结果；端到端测试必须使用 Engine 真实结果。

---

## 12. 验证命令

目标相关 Python：

```powershell
python -m pytest tests\test_tank_pid_configs.py tests\test_pid_industrial.py tests\test_structured_dsl.py -q
```

新增 API/Engine 测试后追加其文件，例如：

```powershell
python -m pytest tests\test_engine_api.py tests\test_engine_atomic_writes.py -q
```

前端应在 `package.json` 新增 `test` 和 `test:run`，推荐 Vitest + Testing Library。标准命令：

```powershell
Set-Location config-tool\frontend
npm.cmd run test:run
npm.cmd run build
```

Go 内部包和完整应用：

```powershell
Set-Location config-tool
$env:GOCACHE = Join-Path ([System.IO.Path]::GetTempPath()) 'review3-go-cache'
go test ./internal/...
wails build
go test ./...
```

`wails build` 负责按 Go bindings 重新生成 `frontend/wailsjs`；不得长期手写维护生成文件。若依赖安装或 Wails 生成在环境中不可用，必须报告阻塞，不能跳过构建后宣称完成。
