# Data Factory Server 用户手册

> 统一的有状态周期执行引擎：批量仿真（GENERATOR）+ 实时仿真（REALTIME），数据走 Redis 总线，历史存 DuckDB，并通过 OPC UA Server 把全部位号暴露给工业客户端。
>
> **当前版本**：v2.0（基于 commit `de35f3c` 的 data_factory_next）
>
> designed by yzc

---

## 1. 这是什么

Data Factory Server 是一个工业数据生成 / 实时仿真平台。它解决三件事：

- **批量仿真**（GENERATOR 模式）：写一段 YAML DSL，给出要跑多少个周期，引擎在内存里一口气跑完，返回所有周期的快照。
- **实时仿真**（REALTIME 模式）：常驻后台线程，按 `cycle_time` sleep，每个周期的快照自动推到 Redis、写进 DuckDB、广播到 OPC UA 节点。
- **OPC UA 暴露**：仿真跑出的全部位号（PID 的 MV/PV/SV、水箱的 level、阀门的开度等）以位号名为 NodeId 挂在 `Objects/DataFactory` 下，工业客户端（UAExpert / KEPServer / SCADA）直接订阅即可，支持客户端写值回传。

整个系统走 FastAPI 后端 + Vite/React 前端 + Redis + DuckDB + asyncua OPC UA Server 的标准全栈形态，对应 `engines_manifest.yaml` 编排的多引擎实例。

---

## 2. 使用入门

### 2.1 环境要求

- **Python** 3.10+（Ubuntu 部署推荐 3.12）
- **Redis** 任意版本（默认 `localhost:6379`）
- **Node.js** 18+（仅前端 UI 需要）
- 第三方依赖：`pip install -r requirements.txt`（含 `fastapi / uvicorn / pyyaml / pandas / numpy / redis / duckdb / asyncua`）

> Redis 必须先启动；DuckDB 是 Python 库自带，不需要另外装服务。

### 2.2 一键启动（Windows）

项目根目录有 `start_system.bat`，双击或在 cmd 里运行：

```cmd
start_system.bat
```

它会开两个控制台窗口：

| 窗口 | 启动命令 | 端口 |
| ---- | ---- | ---- |
| DF-Backend | `python -m uvicorn web_backend.main:app --host 0.0.0.0 --port 8000` | FastAPI `:8000` |
| DF-Frontend | `cd web_frontend && npm run dev` | Vite `:5173` |

服务起来后浏览器访问：

- **Web UI**：`http://localhost:5173`
- **API 文档**：`http://localhost:8000/docs`
- **健康检查**：`http://localhost:8000/health`

> 弹出窗口不要关；关掉就停服务了。

### 2.3 手动分步启动

```bash
# 后端
python -m uvicorn web_backend.main:app --host 0.0.0.0 --port 8000

# 前端（新开一个终端）
cd web_frontend && npm install && npm run dev
```

### 2.4 Linux / Ubuntu 部署

Ubuntu 22.04 LTS 上需要先装系统级依赖（`python3.12-dev / build-essential / qt6-base-dev / redis-server`），再创建虚拟环境装 Python 依赖，最后用 systemd 管理。完整步骤见 `doc/ubuntu_deployment.md`。

> 后端启动会自动联动启动 `ServiceManager`，进而拉起 Engine + StorageService + OPC UA Server 三个子服务。

---

## 3. 功能介绍

### 3.1 总体架构

```
浏览器 (Vite+React+AntD :5173)
        │
        ▼
FastAPI 后端 (:8000)  ── engines_manifest.yaml
        │
        ▼
ServiceManager
   ├── Engine(s) (UnifiedEngine, REALTIME 模式)
   │       │ 每周期推送
   │       ▼
   │   Redis 总线 (data_factory:v2:current)
   │       │
   ├── StorageService  ←── 订阅组态事件 ──┘
   │       │ 批量写入 (每 500 行)
   │       ▼
   │   DuckDB (storage/storage_service.duckdb)
   │
   └── OPCUA Server (:18951)
           ├── 读 Redis 更新节点
           └── 客户端写值 → 消息总线 → Engine override
```

`ServiceManager` 是入口（`services/service_manager.py`），它通过 `ConfigServer` 解析 `engines_manifest.yaml`，按 `instances` 列表逐个启动 `UnifiedEngine`，并把它们的数据汇总到同一个 OPC UA Server 暴露。

### 3.2 双模式运行

| 维度 | GENERATOR 模式 | REALTIME 模式 |
| ---- | ---- | ---- |
| 触发 | `run_generator(n)` / `run_export(steps=N)` | `run_realtime()` 在 `RealtimeRunner` 后台线程常驻 |
| 速度 | 跑完即止，不 sleep | 按 `cycle_time` sleep，模拟 PLC 节拍 |
| 数据流 | 调用方拿到 `List[Snapshot]` | 推 Redis → Storage 进 DuckDB → OPC UA 节点刷新 |
| 写值回传 | 不接收 | 支持（OPC UA 写 → MessageBus → Engine） |
| 用途 | 批量生成、离线分析、模型训练数据 | 联调、SCADA 对接、PLC 仿真 |

> Clock 的执行节奏由 `cycle_time`（周期秒数）与可选 `sample_interval`（采样间隔秒数）共同决定；后者必须 ≥ 前者，`None` 表示每个周期都采样。

### 3.3 多引擎编排

`engines_manifest.yaml` 是入口编排：

```yaml
instances:
  - id: mpc_1
    type: simulation
    source: controller/running_config/mpc_1.yaml
  - id: page_tank_1
    type: simulation
    source: controller/running_config/page_tank_1.yaml
  # ... 共 15 个 demo case

storage:
  sample_interval: 1.0

opcua:
  publish_interval: 0.5
```

每个 `id` 在 Redis 中作为命名空间前缀（`engine.<id>` 服务名、`<id>.<instance>.<attr>` 位号名），不同引擎的位号自然隔离，全局位号注册表在 `data_factory:registry:tags`。`POST /services/reload` 可以热重载这份 manifest，对比 `instances` 差量启停。

### 3.4 支持的程序类型

所有类型都在 `components/programs/` 下注册，使用同一个 `program: [{name, type, init_args, display_args, expression}]` 入口。

| 类型 | 类 | stored_attributes（默认进存储/导出的属性） |
| ---- | ---- | ---- |
| `PID` | `PID` | `MV, PV, SV, PB, TI, TD, H, L, MODE` |
| `SINE_WAVE` | `SINE_WAVE` | `out, amplitude, offset` |
| `TRIANGLE_WAVE` | `TRIANGLE_WAVE` | （见 `components/programs/triangle_wave.py`） |
| `SQUARE_WAVE` | `SQUARE_WAVE` | 同上 |
| `LIST_WAVE` | `LIST_WAVE` | 列表型波形 |
| `RANDOM` | `RANDOM` | 随机波形 |
| `VALVE` | `VALVE` | `current_opening, target_opening, inlet_flow, outlet_flow, flow_coefficient, min_opening, max_opening, full_travel_time, initial_opening` |
| `CYLINDRICAL_TANK` | `CYLINDRICAL_TANK` | `level, inlet_flow, outlet_flow, height, radius, outlet_area, initial_level` |
| `TAG` | `TAG` | 用于扩展其它位号读写 |
| `Variable` | （无状态） | `name` 自身 |

每种类型都自带 `param_descriptions` 和 `params_table` 自描述（通过 `GET /docs/program/{name}` 暴露）。

### 3.5 支持的操作系统

- **Windows** 10 / 11（64 位，主验证平台）
- **Linux / Ubuntu** 20.04 / 22.04 LTS（Python 3.12，详见 `doc/ubuntu_deployment.md`）

---

## 4. 准备输入：YAML DSL

### 4.1 顶层结构

```yaml
# 可选：时钟配置；不写就走默认 cycle_time=0.5, sample_interval=None
clock:
  mode: REALTIME          # GENERATOR | REALTIME
  cycle_time: 0.5         # 周期（秒）
  start_time: 0.0         # 起始时间（秒或 ISO 字符串）
  sample_interval: null   # 采样间隔；null = 每个周期都采样

# 必填：program 列表（每条一个实例）
program:
  - name: <实例名>
    type: <类型，见上表>
    init_args:             # 可选
      ...
    display_args:          # 可选，默认展示/导出列
      - "MV[100]"
      - "PV[2]"
    expression: "<表达式>"
```

> `display_args` 单项语法：`attr` 或 `attr[ref]`（`ref` 是绘图缩放参考值，只影响曲线纵坐标，不影响 CSV 原始值；`ref` 默认 100）。`Variable` 类型要求属性名等于 `name` 本身。
>
> **未写 `display_args` 或 `display_args: []` 等价于"该实例不参与默认曲线和默认导出列"**，需要显式给非空列表才会显示。

### 4.2 表达式语法

**算法/模型实例**（每个周期调用 `execute()` 更新内部状态，属性通过 `instance.attr` 访问）：

```yaml
- name: v_name
  type: PID
  init_args:
    PB: 12
    TI: 30
    TD: 0.15
  display_args: ["MV[100]", "PV[2]", "SV[2]", "MODE"]
  expression: v_name.execute(PV=tank_1.level, SV=sin1.out)
```

```yaml
- name: valve_1
  type: VALVE
  expression: valve_1.execute(target_opening=v_name.MV, inlet_flow=source_flow)

- name: tank_1
  type: CYLINDRICAL_TANK
  expression: tank_1.execute(inlet_flow=valve_1.outlet_flow)
```

**Variable 类型**（无状态，赋值语句 + 数学函数 + lag 历史）：

```yaml
- name: source_flow
  type: VARIABLE
  expression: source_flow = 0.18

- name: lagged
  type: VARIABLE
  expression: lagged = source_flow[-30] + sqrt(tank_1.level)
```

支持的数学函数（注册在 `components/functions/`）：`abs / sqrt / sin / cos / tan / log / exp / max / min` 等。lag 语法 `var_name[-N]` 访问 N 个周期前的值，系统会自动按 lag 需求预留历史缓冲区。

### 4.3 一个完整可用的 demo：水箱液位 PID 控制

对应 `classical_config/典型水箱液位控制.yaml`，可直接复制：

```yaml
program:
  # 设定值（正弦波，振幅 1、周期 2000s、纵向偏移 1，输出在 [0,2] 区间）
  - name: sin1
    type: SINE_WAVE
    init_args:
      amplitude: 1.0
      period: 2000
      phase: 0.0
      offset: 1.0
    display_args: []
    expression: sin1.execute()

  # 恒定入口流量
  - name: source_flow
    type: VARIABLE
    expression: source_flow = 0.18
    display_args: []

  # 阀门：开度跟随 PID 的 MV，入口流量为 source_flow
  - name: valve_1
    type: VALVE
    init_args:
      full_travel_time: 10
    display_args: []
    expression: valve_1.execute(target_opening=v_name.MV, inlet_flow=source_flow)

  # 圆柱水箱：液位跟随阀门出口流量
  - name: tank_1
    type: CYLINDRICAL_TANK
    init_args: {}
    display_args: []
    expression: tank_1.execute(inlet_flow=valve_1.outlet_flow)

  # PID 控制器：测量 tank_1.level，SV 跟随 sin1.out
  - name: v_name
    type: PID
    init_args:
      PB: 12
      TI: 30
      TD: 0.15
    display_args: ["MV[100]", "PV[2]", "SV[2]", "MODE"]
    expression: v_name.execute(PV=tank_1.level, SV=sin1.out)
```

控制链路：`sin1 → v_name → valve_1 → tank_1 → v_name`。SV 在 0~2 之间慢摆，PV（液位）应被 PID 拉到 SV 附近。

> 写入 PID 的 `v_name.SV` 可以从外部调整设定值；PID 的 MODE=1 时正常运算，非 1 时本周期跳过运算（MV 不更新）。

### 4.4 依赖关系与执行顺序

引擎解析表达式自动建依赖图，拓扑排序确定执行顺序；遇到 PID→阀门→水箱→PID 这种闭环，第一次执行使用 `init_args` 初始值，后续按拓扑顺序逐步推进。`Variable` 默认存储；算法/模型的存储属性由类的 `stored_attributes` 决定。

### 4.5 历史与 lag 自动配置

`parser` 会扫所有表达式里的 `[-N]`，自动算出 `lag_requirements`，再按 `LAG_SAFETY_MARGIN=1.5` 预留 `record_length`，不需要手填。`MIN_RECORD_LENGTH=10`，没有 lag 需求时也至少保留 10。

---

## 5. Web UI

启动后端 + 前端后访问 `http://localhost:5173`。前端主要由以下模块组成：

- **首页**：服务状态、活跃引擎列表、诊断概览
- **实时组态**：三级树结构浏览当前 manifest 下所有位号（来自 Redis `data_factory:registry:tags`），可点开看变量/实例属性
- **实时数据**：每个周期刷新所有位号当前值，ECharts 折线（单/双 Y 轴）
- **数据模拟**：CodeMirror YAML 编辑器，编辑后 `POST /simulate/preview` 在前端预览曲线（不写 Redis、不起 OPC UA，纯前端离线预览）
- **数据生成 / 导出**：选 YAML 模板、周期数、输出列，`POST /export/run` 一次性跑 + 导出
- **历史查询**：选位号 + 时间窗口，调 `/history/query` 拉 DuckDB 历史回放
- **设置 / 引擎管理**：CodeMirror 编辑 `engines_manifest.yaml`，保存后 `POST /services/reload` 热重载

默认账号 `admin / admin`（如前端启用了登录）。

---

## 6. REST API 列表

所有接口前缀 `http://localhost:8000`。完整文档看 `http://localhost:8000/docs`（FastAPI 自动生成）。

### 6.1 健康 / 状态 / 诊断

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/health` | 健康检查 |
| GET | `/services/status` | 各服务状态（注册/健康/元数据） |
| GET | `/services/diagnostic` | 精简诊断信息 |
| GET | `/services/diagnostic/detail` | 详细诊断（从 Redis `data_factory:diagnostic:*` 读） |
| GET | `/services/engines` | 当前活跃 Engine 列表 |
| GET | `/readme` | README 内容 |

### 6.2 配置 / 编排

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/config/manifest` | 读 `engines_manifest.yaml` |
| POST | `/config/manifest` | 写 `engines_manifest.yaml`（请求体 `{"content": "..."}`） |
| POST | `/services/reload` | 热重载 manifest（差量启停） |
| GET | `/config/list` | 列出 `classical_config/` 下所有 YAML |
| GET | `/config/default` | 读 `classical_config/display_demo.yaml` |
| POST | `/config/save` | 保存 DSL 到 `classical_config/` |
| GET | `/templates/list` | 列出全部导出模板 |

### 6.3 实时模式（常驻 Engine）

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/realtime/configs` | 加载 DSL 配置到实时 Engine（请求体 `ConfigRequest`） |
| PATCH | `/realtime/instances/{name}/params` | 改实例参数（PB/TI/SV 等） |
| PATCH | `/realtime/variables/{name}` | 改 Variable 表达式或当前值 |
| POST | `/realtime/programs` | 动态新增 program |
| DELETE | `/realtime/programs/{name}` | 删除 program（实例/模型） |
| DELETE | `/realtime/variables/{name}` | 删除 Variable |
| GET | `/realtime/snapshot` | 读最新位号快照（合并 Redis V2 Hash + runner 内存） |
| GET | `/realtime/config` | 读实时组态（实例/变量/属性清单） |
| GET | `/realtime/config/redis` | 从 Redis `data_factory:registry:tags` 重建位号树 |
| POST | `/realtime/export` | 导出现行快照（占位，可扩展为窗口导出） |

所有 `realtime/*` 接口都支持 `?engine_id=` 参数指向多引擎场景中的某个 Engine；不传则默认 `default`。

### 6.4 一次性导出

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/export/run` | `ExportRequest`，返回 `{output_path, steps, template, file_format, file_content[_base64], mime_type, filename}` |
| GET | `/export/format-defaults/{template_name}` | 模板的默认导出配置 |
| POST | `/simulate/preview` | 离线预览（不启动 Engine），返回 `data, variable_names, display_variables, variable_meta, plot_scales, generation_time, estimated_export_time` |

### 6.5 历史查询

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/history/query` | 按 `param_name + 时间窗口 + 采样点数` 返回固定点数的采样数据 |

### 6.6 自描述文档 API

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/docs/programs/list` | 所有程序（PID/VALVE/...）清单 |
| GET | `/docs/functions/list` | 所有数学函数清单 |
| GET | `/docs/program/{name}` | 单个程序的 `name / chinese_name / doc / params_table` |
| GET | `/docs/function/{name}` | 单个函数的文档 |

### 6.7 调用示例

加载实时配置：

```bash
curl -X POST http://localhost:8000/realtime/configs \
  -H "Content-Type: application/json" \
  -d "{\"dsl_content\": $(python -c "import json,sys; print(json.dumps(open('classical_config/典型水箱液位控制.yaml',encoding='utf-8').read()))")}"
```

读最新快照：

```bash
curl http://localhost:8000/realtime/snapshot
```

改 PID 设定值：

```bash
curl -X PATCH http://localhost:8000/realtime/instances/v_name/params \
  -H "Content-Type: application/json" \
  -d "{\"params\": {\"SV\": 1.5}}"
```

---

## 7. 导出模板

模板位于 `components/export_templates/templates/`，由 `TemplateManager` 加载；调用 `/export/run` 时 `template_name` 选一个：

| 模板名 | file_format | header_rows | title_names | time_format | 用途 |
| ---- | ---- | ---- | ---- | ---- | ---- |
| `prediction` | csv | 2 | `timeStamp,时间戳` | `%Y-%m-%d %H:%M:%S` | 通用预测数据导出（默认） |
| `ai` | xlsx | 2 | `Timestamp,时间戳` | `%Y/%m/%d %H:%M:%S` | AI 训练样本，xlsx |
| `ai_loop_tuning` | csv | 1 | `Timestamp` | `%Y-%m-%d %H:%M:%S` | AI 回路整定数据（单行表头） |
| `mpc` | xlsx | 2 | `时间,1` | `%Y/%m/%d %H:%M:%S` | MPC 控制器数据 |
| `pid_loop_tuning` | csv | 1 | `时间` | `%Y-%m-%d %H:%M:%S` | PID 整定数据（单行表头） |

如果不想用 YAML 模板，可改用 `ExportRequest.export_format` 直接传：

```json
{
  "header_rows": 1,
  "title_names": "时间",
  "time_format": "%Y-%m-%d %H:%M:%S",
  "file_format": "xlsx",
  "sheet_name": "控制器"
}
```

> `file_format` 只支持 `csv` / `xlsx` / `xls`；xlsx/xls 需要额外装 `openpyxl` / `xlwt`。

默认导出列按 DSL 中**非空** `display_args` 决定；不传 `selected_variables` 时与 `get_display_variables()` 一致；传了就只导这些列。

---

## 8. OPC UA 暴露

### 8.1 端点与地址空间

- **默认端点**：`opc.tcp://0.0.0.0:18951`（可在环境变量 `OPCUA_SERVER_URL` 修改）
- **命名空间**：`http://data_factory.opcua`（通常落在 `ns=2`）
- **服务器名**：`Data Factory OPCUA Server`
- **安全**：默认 NoSecurity（匿名连接），生产环境请在 `datacenter/opcua_server.py` 自行加证书
- **根容器**：`Objects/DataFactory`

### 8.2 NodeId 规则

所有变量节点扁平挂在 `Objects/DataFactory` 下：

```
Objects/
  └── DataFactory/
       ├── sin1.out
       ├── source_flow
       ├── valve_1.current_opening
       ├── valve_1.outlet_flow
       ├── tank_1.level
       ├── v_name.MV
       ├── v_name.PV
       └── v_name.SV
```

- NodeId 标识符 = 位号全名（如 `tank_1.level`、`v_name.MV`）
- 命名空间索引 = `namespace_idx`（常为 2，asyncua 自动分配）
- 类型默认 `Double`（浮点）
- 写值默认开启（环境变量 `OPCUA_ENABLE_WRITE=false` 可关）

多引擎场景下，ConfigServer 会把所有引擎的位号汇总到同一张注册表，所以即使 `engines_manifest.yaml` 里挂了 15 个引擎，OPC UA 客户端只连 18951 就能看到全部位号（位号名带 engine_id 前缀防止重名冲突）。

### 8.3 客户端写值回传

客户端往可写节点写入一个值后：

1. OPC UA Server 捕获写事件
2. 通过 MessageBus 找到目标 `engine.<namespace>` 服务（位号名前缀决定 engine）
3. 调 `opcua_write_value` handler，把 `(param_name, value)` 推给对应 Engine
4. Engine 用 `queue_param_update` / `queue_variable_update` 在下一个周期空闲时落地

> **坑**：PID 的 `PV / SV / MV` 在每个周期会被 `execute(PV=..., SV=...)` 重新覆盖；外部写只对 `init_args` 类参数（`PB / TI / TD / MODE` 等）能持久。想让外部写值真的影响 PID 的 SV，更稳的写法是把 SV 放在 `Variable` 里，再让 PID 表达式 `SV=<var>.out`，这样外部写 `var.value` 不会被 `execute()` 覆盖。

---

## 9. 历史存储

- **后端**：`storage/storage_service.duckdb`（项目根目录的上一级的 `storage/` 目录，可通过 `STORAGE_DB_PATH` 改）
- **采样粒度**：由 Engine Clock 的 `sample_interval` 决定；写入只在 `need_sample=True` 时发生
- **批量写入**：每 500 行一次 INSERT VALUES（`BATCH_INSERT_SIZE=500`），性能提升 20+ 倍
- **表结构**：`data_records(id, timestamp, param_name, param_value, instance_name, param_type, cycle_count, sim_time, engine_id, source_logic)`
- **查询**：`POST /history/query` 或 `datacenter/history_query.py` 的 `HistoryQuery`（只读连接，独立进程也安全）

> DuckDB 是单写多读模型；`HistoryQuery` 与 `StorageService` 在同一进程内复用连接，跨进程会报"different configuration than existing connections"。

---

## 10. 多实例 / 多 Engine

通过 `engines_manifest.yaml` 编排：

```yaml
instances:
  - id: tank_01
    type: simulation
    source: classical_config/典型水箱液位控制.yaml
  - id: tank_02
    type: playback           # 从 xlsx/csv 回放历史
    source: data/history.xlsx
    time_col: "Timestamp"
    sheet_name: "Sheet1"
```

- `type: simulation` → DSL YAML 仿真
- `type: playback` → `PlaybackEngine` 按 `time_col` 时间戳回放 xlsx/csv
- 不同 `id` 各自一个 Engine 线程 + 一个 `engine.<id>` MessageBus 服务名，位号名加 `id` 前缀隔离
- `POST /services/reload` 触发 `ServiceManager.reload_infrastructure()`，差量启停

项目自带 15 个 demo case（`controller/running_config/` 下 `mpc_1 / assess_c_1 / ns_lag / page_tank_1..10`），启动后所有位号都汇到同一个 OPC UA Server。

---

## 11. 已知限制

- **实时模式部分功能待完善**：详细清单见 `doc/实时模式功能状态分析.md`，核心功能（Engine + RealtimePublisher + OPC UA + Storage）已就绪，但 `web_backend/main.py` 的启动集成、`start_realtime.py` 入口、配置校验、监控工具仍有缺口。
- **多 Engine 运行改进**：规划见 `todo/` 目录（项目结构说明）。
- **架构优化说明**：见 `doc/架构优化说明.md`（如存在）。
- **OPC UA 写值对周期覆写属性的局限**：见上文 8.3。
- **DuckDB 单写锁**：StorageService 与 HistoryQuery 必须同进程；跨进程打开会冲突。

---

## 12. 完整可用的运行示例（从零启动 → 改 SV → 看 PV 跟随）

1. 启动 Redis：

```bash
redis-server
```

2. 一键启动：

```cmd
start_system.bat
```

3. 浏览器打开 `http://localhost:5173`，在「设置/引擎管理」里看 manifest 是否加载了 15 个 demo Engine。

4. 确认 OPC UA Server 已起：

```bash
# 用任意 OPC UA 客户端（UAExpert、asyncua、Prosys OPC UA Browser...）
# 连 opc.tcp://127.0.0.1:18951
# 浏览 Objects/DataFactory，应该看到类似 tank_1.level、v_name.MV、sin1.out 等节点
```

5. 加载 demo（如果还没自动加载）：

```bash
curl -X POST http://localhost:8000/realtime/configs \
  -H "Content-Type: application-Type: application/json" \
  -d "{\"dsl_content\": \"$(cat classical_config/典型水箱液位控制.yaml)\", \"namespace\": \"default\"}"
```

6. 用 OPC UA 客户端订阅 `tank_1.level`（PV）和 `v_name.SV`，每秒刷新一次。

7. 改 SV（通过 OPC UA 客户端或 API）：

```bash
curl -X PATCH http://localhost:8000/realtime/variables/sin1 \
  -H "Content-Type: application/json" \
  -d "{\"expression\": \"sin1 = 1.5\"}"
```

8. 观察曲线：PV 应在 1~2 个周期后向新的 SV 收敛。

9. 触发导出：

```bash
curl -X POST http://localhost:8000/export/run \
  -H "Content-Type: application/json" \
  -d "{\"config_path\": \"classical_config/典型水箱液位控制.yaml\", \"steps\": 1000, \"template_name\": \"prediction\", \"output_path\": \"tank_export.csv\"}"
```

输出会带 `file_content`（CSV 时直接是文本，xlsx 时是 base64），前端可直接下载。

10. 查历史（前提是 Engine 已经跑了一段时间，StorageService 已把快照落库）：

```bash
curl -X POST http://localhost:8000/history/query \
  -H "Content-Type: application/json" \
  -d "{\"param_name\": \"tank_1.level\", \"time_length\": 600, \"sample_points\": 600}"
```

---

## 13. 验证脚本

仓库自带两个验证用脚本（在 `tests/` 下或根目录）：

- `tests/run_all.bat`：一键起后端 + 前端的等价脚本
- `tests/test_*.py`：单元 / 集成测试，按 `pytest tests/` 跑
- `debug/`（如存在）：交互式调试入口，新代码通常用不上

跑测试时**不要**同时跑 `start_system.bat`，否则 OPC UA 18951 端口冲突。

---

**版本说明**：本手册对应 `data_factory_next` v2.0（FastAPI + Vite/React 全栈形态）。若使用更早的 `pyqt5 + tkinter` 单 exe 形态，请改看 review3 的对应手册。