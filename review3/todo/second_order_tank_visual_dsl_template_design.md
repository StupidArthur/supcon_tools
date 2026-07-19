# 单阀门二阶水箱可视化 DSL 模板设计与实施规范

> 文档用途：交给一个没有本次对话上下文的新 Agent，指导其基于 `supcon_tools/review3` 当前代码实现第一个固定工艺可视化 DSL 模板。
>
> 文档版本：1.0  
> 编写日期：2026-07-19  
> 目标模板：`config/单阀门二阶水箱.yaml`

---

## 1. 项目背景与产品定位

`supcon_tools/review3` 是一个面向工业 AI 算法测试、演示和数据生成的工具级项目，不以建设完整 DCS、流程模拟器或通用可视化组态平台为目标。

它需要同时支持：

1. 根据 DSL 快速生成 CSV、Excel 等历史训练数据；
2. 以实时周期运行，通过 OPC UA 向上游工业 AI 提供数据；
3. 接收 OPC UA 或内部界面对 SV、MODE、MV 等位号的写入；
4. 为少数固定工艺模板提供可视化组态、调试仿真和实时监控。

本任务不是实现任意设备拖拽、自由连线的通用 HMI/SCADA 编辑器，而是实现第一个“固定流程图 + 模板参数修改 + 仿真验证 + 实时监控”的可视化模板。

第一批预计只有 2～3 个固定模板：

1. 单阀门二阶水箱；
2. 单阀门串级 PID 水箱；
3. 乙醇—水精馏塔。

因此，第一份实现需要具备适度复用能力，但不得为尚不存在的通用组态需求过度设计。

---

## 2. 开始实施前必须阅读的仓库文件

新 Agent 开始编码前，应先确认本地仓库已同步到最新 `main`，检查 `git status`，保留用户已有修改，并依次阅读以下文件。

### 2.1 项目运行与 DSL 语义

```text
README.md
user_guide.md
config/单阀门二阶水箱.yaml
config/单阀门二阶水箱开环辨识.yaml
```

重点理解：

- `REALTIME` 与 `GENERATOR` 时钟模式；
- DSL 的 `clock`、`program`、`params`、`inputs`、`execute_first`；
- Variable、算法实例及 `instance.attribute` 位号；
- OPC UA 的读取和写入语义；
- 批量生成和 CSV 导出方式。

### 2.2 模型和控制算法

```text
components/programs/cylindrical_tank.py
components/programs/valve.py
components/programs/pid.py
components/programs/base.py
```

不得根据旧版文档猜测 PID 语义。当前 PID 已对齐 ECS-700 的核心参数行为：

- `PB` 是比例度，`Kp = 100 / PB`；
- `TI`、`TD` 单位为秒；
- `MODE=5` 为 AUTO；
- `MODE=4` 为 MAN；
- `MODE=6` 为 CAS；
- `SWPN=1` 为反作用；
- 位号后缀 `PV/SV/CSV/MV/PB/TI/TD/MODE` 必须保持不变，上游 AI 会依赖这些后缀判断回路语义。

### 2.3 现有组态工具

```text
config-tool/frontend/package.json
config-tool/frontend/src/App.tsx
config-tool/frontend/src/store/useCanvasStore.ts
config-tool/frontend/src/components/Canvas.tsx
config-tool/frontend/src/components/PropertyPanel.tsx
config-tool/frontend/src/components/SimulationPanel.tsx
config-tool/internal/config/
config-tool/internal/bindings/
```

`config-tool` 是本任务的主工程。它已经具备：

- Wails v2 桌面壳；
- React 18 + TypeScript + Vite；
- Tailwind CSS；
- Zustand；
- React Flow 通用节点画布；
- YAML 导入、导出和基础校验；
- DataFactory 子进程启动和批量仿真能力。

现有 React Flow 画布继续保留为高级/通用 DSL 视图，但本任务的固定二阶水箱流程图不得画成普通方框节点。

### 2.4 现有调试 GUI 和实时接口

```text
debug_gui/frontend/src/components/ChartPanel.tsx
debug_gui/frontend/src/components/ParamPanel.tsx
debug_gui/frontend/src/store/useStore.ts
debug_gui/internal/bindings/debug.go
debug_gui/internal/engine/proc.go
datacenter/engine_api.py
standalone_main.py
controller/engine.py
```

注意：

- `debug_gui` 只作为趋势图、参数调试和进程管理的实现参考；
- 不要继续把 `debug_gui` 建设成另一个独立用户入口；
- `debug_gui/internal/api/yaml.go` 仍偏向旧版 `init_args/expression` 结构，不能作为本任务的结构化 DSL 解析基础；
- `datacenter/engine_api.py` 已有 FastAPI 状态、快照、写值、导出和 WebSocket 基础；
- `standalone_main.py` 已支持 `--api`，但现有 Wails 启动路径需要检查是否真的传入了该参数；
- 当前前端尚未完整接入 `/ws/snapshot`，本任务需要完成该链路。

---

## 3. 本次任务的最终目标

在 `config-tool` 中增加一个默认面向普通用户的“二阶水箱模板”页面，使同一张工艺画面能够完成：

1. 加载 `单阀门二阶水箱.yaml`；
2. 以现场流程图方式展示水源、阀门、两个水箱、液位测量和 PID 回路；
3. 点击对象，在右侧查看实例名、组态参数、运行位号和连接关系；
4. 修改允许开放的参数并保存 DSL；
5. 保存后启动调试仿真；
6. 实时显示液位、阀位、流量、PV、SV、MV；
7. 在线修改 SV、MODE、MV、PB、TI、TD 等运行参数；
8. 观察趋势和基础控制品质指标；
9. 把满意的在线调参结果写回 DSL；
10. 使用同一张画面启动实时运行和 OPC UA；
11. 运行批量仿真并查看、导出结果。

本任务完成后，普通用户不需要接触 React Flow 节点画布或原始 YAML，就能完成一次完整的二阶水箱组态与调试流程。

---

## 4. 明确的非目标

本次禁止扩展为以下功能：

- 任意设备拖拽；
- 自由添加或删除设备；
- 自由修改拓扑连接；
- 通用工业图元库；
- 任意 DSL 自动生成现场流程图；
- 多窗口同步编辑；
- 历史数据库和回放系统；
- 修改水箱、阀门或 PID 核心算法；
- 修改现有 AI 位号命名；
- 把内部 GUI 数据链路改成 OPC UA 轮询；
- 新建第三个独立桌面 GUI 工程。

若为了本任务必须补充后端接口，只允许对运行控制、批量写值、快照订阅和进程管理做最小修改。

---

## 5. 目标 DSL 的固定拓扑和默认工况

目标文件：

```text
config/单阀门二阶水箱.yaml
```

固定拓扑：

```text
水源 source_flow
    ↓
调节阀 valve_1
    ↓
上游水箱 tank_1
    ↓
下游水箱 tank_2
    ↓
排水
```

控制回路：

```text
tank_2.level → pid2.PV
pid2.MV      → valve_1.target_opening
```

当前默认工况：

| 项目 | 默认值 |
|---|---:|
| 控制周期 | 0.5 s |
| 水源流量 | 0.0012 m³/s = 72 L/min |
| 阀门满行程时间 | 12 s |
| Tank 1 高度/半径 | 1.2 m / 0.15 m |
| Tank 1 出口面积 | 0.00025 m²，对应直径约 17.84 mm |
| Tank 1 初始液位 | 0.15 m |
| Tank 2 高度/半径 | 1.2 m / 0.15 m |
| Tank 2 出口面积 | 0.00020 m²，对应直径约 15.96 mm |
| Tank 2 初始液位 | 0.10 m |
| PID SV | 0.8 m |
| PID PB/TI/TD/KD | 30 / 90 s / 20 s / 10 |
| PID MODE/SWPN | 5（AUTO）/ 1（反作用） |

每个水箱容量约为：

```text
π × 0.15² × 1.2 = 0.08482 m³ ≈ 84.8 L
```

默认目标工况下，预计稳态约为：

```text
Tank 2 液位 ≈ 0.800 m
Tank 1 液位 ≈ 0.512 m
阀门开度    ≈ 66%
```

这些数值应成为 UI 首次加载和自动化测试的基准。

---

## 6. 用户操作流程

### 6.1 打开模板

用户在模板列表中选择“单阀门二阶水箱”。系统加载对应 DSL，并进入停止/组态状态。

首次打开时：

- 中央流程图显示 DSL 的配置初值；
- Tank 1 显示 0.15 m 初始液位；
- Tank 2 显示 0.10 m 初始液位；
- Tank 2 显示 0.8 m 的 SV 标线；
- 阀门显示 `initial_opening`；
- 页面明确标记“当前为初始组态预览，不是实时值”。

### 6.2 点击对象并修改配置

用户点击水源、阀门、水箱、液位测量或 PID，右侧检查器切换到相应对象。

右侧至少分为三个页签：

1. **组态**：DSL 中可编辑的持久化参数；
2. **运行**：最新快照中的实时值和允许在线写入的操作参数；
3. **趋势**：把该对象的推荐位号加入或移出底部趋势图。

右侧标题必须显示：

```text
中文对象名
实例名
组件类型
```

例如：

```text
下游水箱
tank_2
CYLINDRICAL_TANK
```

### 6.3 保存配置

用户修改组态值后进入 dirty 状态，顶部显示未保存数量。

“保存”只修改磁盘 DSL，不得让用户误以为当前运行实例已经改变。

若引擎正在运行，保存成功后提示：

```text
DSL 已保存；当前运行实例仍使用启动时配置。
点击“保存并重新仿真”后，新配置才会进入运行实例。
```

内置模板默认不能被无提示覆盖。第一次保存应优先使用“另存为方案”；用户显式确认后才允许覆盖已有用户方案。

### 6.4 保存并重新仿真

这是最主要的操作：

1. 校验草稿；
2. 保存 DSL；
3. 停止现有调试实例；
4. 归档上一轮趋势，保留为灰色对照曲线；
5. 用新 DSL 启动 DataFactory；
6. 等待 FastAPI 状态接口就绪；
7. 连接 WebSocket；
8. 页面切换到调试仿真状态；
9. 中央流程图开始显示实时值。

不得在进程尚未就绪时把界面标记为“运行中”。

### 6.5 在线调 PID

仿真或实时运行中允许在线修改：

```text
pid2.SV
pid2.MODE
pid2.MV
pid2.PB
pid2.TI
pid2.TD
pid2.KD
pid2.SWPN
pid2.SVH / SVL
pid2.MVH / MVL
```

PB、TI、TD、KD 等一组参数必须支持一次提交，并在同一个计算周期边界生效，避免多次 HTTP 请求跨越多个周期造成不必要的瞬态。

每次在线写入都必须在趋势图上记录事件，例如：

```text
12:35:10  pid2.PB  30 → 40  来源：界面在线调参
```

在线调参默认只影响当前实例。用户确认效果满意后，点击“将当前调参保存到 DSL”，系统只写回允许持久化的白名单参数，不得把实时 PV、当前液位或当前动态 MV 自动写成初始条件。

### 6.6 实时运行

用户保存满意的方案后，可以停止调试仿真并点击“实时运行”。

实时运行和调试仿真使用同一张流程画面和同一组位号绑定。页面顶部必须显示：

```text
实时运行
OPC UA：已启动/未启动
FastAPI：已连接/断开
当前 DSL 文件
当前运行配置哈希或启动时间
```

外部 OPC UA 客户端写入 SV、MODE 或 MV 后，WebSocket 的下一次快照应反映新值，界面不得维护一份脱离引擎的假状态。

### 6.7 批量生成

批量生成使用 `GENERATOR`/`--batch` 路径，不逐周期驱动现场动画。

用户输入：

- 周期数或模拟时长；
- 生成周期；
- 导出路径；
- 需要导出的位号。

运行中显示任务进度。完成后把结果加载到底部趋势面板，并支持 CSV 导出。

图表最多绘制约 2,000～5,000 个下采样点，不能把几十万行数据全部送进 Recharts。

---

## 7. 页面信息架构

### 7.1 总体布局

第一版使用单窗口，不以弹窗作为主交互。

```text
┌──────────────────────────────────────────────────────────────┐
│ 模板/方案 │ 组态/仿真/实时 │ 保存 │ 保存并仿真 │ 停止 │ 导出 │
├───────────────────────────────────┬──────────────────────────┤
│                                   │ 当前选中对象              │
│       二阶水箱现场流程图           │ 实例名 / 类型              │
│                                   │ 组态 / 运行 / 趋势         │
│                                   │ 参数表单或 PID 面板         │
├───────────────────────────────────┴──────────────────────────┤
│ PV / SV / MV / 液位 / 流量趋势 + 参数变更事件                │
└──────────────────────────────────────────────────────────────┘
```

推荐最低可用窗口尺寸为 1024×700；在更大窗口下流程图和趋势区域自适应扩展，右侧检查器保持合理固定宽度。

### 7.2 顶部工具栏

至少包括：

- 返回模板列表；
- 当前方案名称；
- dirty 标记；
- 状态：停止、启动中、调试仿真、实时运行、批量生成、错误；
- 保存；
- 另存为；
- 保存并重新仿真；
- 实时运行；
- 停止；
- 批量生成；
- 导出；
- 高级 DSL 视图入口。

### 7.3 右侧对象检查器

右侧检查器根据选中对象变化。未选择对象时显示本模板说明、当前方案和运行状态，不显示空白页面。

表单字段必须显示：

- 中文名称；
- 原始 DSL 参数名；
- 当前值；
- 单位；
- 可编辑状态；
- 生效方式：立即生效或重启生效；
- 合法范围；
- 必要的帮助文本。

高级参数默认折叠。

### 7.4 底部趋势

默认曲线：

```text
tank_2.level
pid2.PV
pid2.SV
pid2.MV
valve_1.current_opening
```

由于 `pid2.PV` 与 `tank_2.level` 理论上重合，可默认只绘制一条液位曲线，但图例中必须能明确二者绑定关系。

趋势功能至少支持：

- 曲线开关；
- 双 Y 轴或量纲分组，避免液位和百分比共用一个轴；
- 最近 N 点环形缓冲；
- 参数变更事件标记；
- 上一轮仿真灰色对照；
- 清空；
- 批量结果加载；
- CSV 导出。

第一版继续使用仓库已有 Recharts，不引入新的图表依赖。

---

## 8. 现场流程图视觉规范

### 8.1 技术实现

使用 React 自定义 SVG 组件绘制固定 P&ID，不使用 React Flow 绘制普通用户的模板画面。

原因：

- SVG 适合水箱液位裁剪和填充；
- 阀门和管线可以画成工业流程图样式；
- 点击区域、信号箭头、颜色和动画完全可控；
- 固定模板不需要节点布局、拖拽和自由连线；
- 可以避免界面呈现成“几个算法方框”。

React Flow 现有通用画布必须继续可用，但它属于高级 DSL 视图。

### 8.2 必须绘制的对象

1. 水源 `source_flow`；
2. 入口工艺管线；
3. 调节阀 `valve_1`；
4. Tank 1 `tank_1`；
5. Tank 1 至 Tank 2 管线；
6. Tank 2 `tank_2`；
7. 排水管线；
8. Tank 2 液位测量 `LT-201`；
9. 液位控制器 `LIC-201 / pid2`；
10. PV 信号线；
11. MV 信号线。

### 8.3 过程和控制信号

- 过程管线：蓝色或青色实线；
- 无流量：灰色；
- 流量存在：使用移动虚线、粒子或方向箭头表示方向；
- 控制信号：橙色虚线；
- PV 信号：`tank_2.level → pid2.PV`；
- MV 信号：`pid2.MV → valve_1.target_opening`；
- 当前选中对象：明显但不刺眼的高亮描边；
- 警告：黄色；
- 越界或错误：红色。

动画只用于表达状态，精确值必须以文本显示。

### 8.4 水箱液位显示

停止/组态状态：

```text
液位填充比例 = initial_level / height
```

运行状态：

```text
液位填充比例 = level / height
```

Tank 2 额外绘制：

```text
SV 标线比例 = pid2.SV / tank_2.height
```

所有比例限制在绘图区域内，但若原始值越界，必须在对象旁显示越界告警，不能用视觉裁剪掩盖错误。

### 8.5 阀门显示

阀门主图形按 `current_opening` 表示真实位置，旁边同时显示：

```text
目标：target_opening
实际：current_opening
入口：inlet_flow
出口：outlet_flow
```

禁止使用 `pid2.MV` 直接冒充实际阀位。

### 8.6 液位测量对象

`LT-201` 是模板画面的虚拟仪表，不要求新增 DSL Program。它绑定：

```text
source tag = tank_2.level
target tag = pid2.PV
```

点击 LT 时，右侧显示信号来源和目标，不显示不存在的设备参数。

---

## 9. 对象、位号和界面绑定

### 9.1 水源

| UI 字段 | DSL/运行位号 | 显示单位 | 编辑语义 |
|---|---|---:|---|
| 配置流量 | `source_flow.value` | L/min | 保存后重启生效 |
| 当前流量 | `source_flow` | L/min | 运行只读，允许作为扰动在线写入 |

单位转换：

```text
L/min = m³/s × 60000
m³/s = L/min ÷ 60000
```

### 9.2 阀门

| UI 字段 | DSL/运行位号 | 单位 | 编辑语义 |
|---|---|---:|---|
| 满行程时间 | `valve_1.params.full_travel_time` | s | 重启生效 |
| 初始开度 | `valve_1.params.initial_opening` | % | 重启生效 |
| 流量系数 | `valve_1.params.flow_coefficient` | — | 重启生效 |
| 最小/最大开度 | `min_opening/max_opening` | % | 高级，重启生效 |
| 目标开度 | `valve_1.target_opening` | % | 运行只读，由 PID 驱动 |
| 实际开度 | `valve_1.current_opening` | % | 运行只读 |
| 入口/出口流量 | `inlet_flow/outlet_flow` | L/min | 运行只读 |

当前 DSL 未显式写出的默认参数，应使用组件 `default_params` 形成“有效配置”；只有用户修改或保存方案时才需要决定是否显式写入 YAML。

### 9.3 两个水箱

Tank 1 和 Tank 2 使用同一字段定义：

| UI 字段 | DSL/运行位号 | 显示单位 | 编辑语义 |
|---|---|---:|---|
| 高度 | `params.height` | m | 重启生效 |
| 半径 | `params.radius` | m | 重启生效 |
| 出口直径 | 转换到 `params.outlet_area` | mm | 重启生效 |
| 初始液位 | `params.initial_level` | m | 重启生效 |
| 当前液位 | `level` | m / % | 运行只读 |
| 入口/出口流量 | `inlet_flow/outlet_flow` | L/min | 运行只读 |
| 计算容量 | `πr²h` | L | 只读派生值 |

出口直径与面积转换：

```text
d_m = d_mm / 1000
outlet_area = π × d_m² / 4
d_mm = sqrt(4 × outlet_area / π) × 1000
```

### 9.4 PID

| 分组 | 位号 | 编辑语义 |
|---|---|---|
| 实时值 | `PV/SV/CSV/MV/MODE/AUTO/CAS` | 根据模式部分可写 |
| 调参 | `PB/TI/TD/KD` | 允许运行中批量写入，也可持久化 |
| 作用方向 | `SWPN` | 高级，允许运行中写入，修改前警告 |
| PV/SV 量程 | `SVSCL/SVSCH` | 高级，通常重启或批量写入 |
| MV 量程 | `MVSCL/MVSCH` | 高级 |
| 操作限幅 | `SVL/SVH/MVL/MVH` | 高级 |

基础模式只突出：

```text
AUTO（MODE=5）
MAN（MODE=4）
```

MAN 模式下允许写 `MV`；AUTO 模式下允许写 `SV`，`MV` 只读。

完整 MODE 1～8 放入高级菜单，标签必须使用 `components/programs/pid.py` 当前定义。

### 9.5 时钟

| UI 字段 | DSL 字段 | 编辑语义 |
|---|---|---|
| 运行模式 | `clock.mode` | 启动参数/重启生效 |
| 控制周期 | `clock.cycle_time` | 重启生效 |

模板默认周期保持 0.5 s。

---

## 10. 参数范围、联动与可行性校验

### 10.1 基础合法性

保存和启动前必须阻止：

- `cycle_time <= 0`；
- 水源流量为负或非有限；
- 水箱高度、半径、出口面积不大于零；
- 初始液位小于 0 或大于水箱高度；
- PID `PB <= 0`；
- `TI/TD < 0`；
- `KD <= 0`；
- SV 不在操作限幅或水箱物理高度内；
- MV 上下限次序错误；
- MODE 不是 1～8 的整数；
- 任意参数为 NaN 或 Inf。

### 10.2 Tank 2 高度与 PID 量程联动

基础模式下，修改 Tank 2 高度时自动同步：

```text
pid2.SVSCH = tank_2.height
pid2.SVH   = tank_2.height
```

并保证：

```text
pid2.SVSCL = 0
pid2.SVL   = 0
```

若后续开放“自定义量程”，必须提供显式开关，不能静默覆盖用户自定义值。第一版可以不开放该开关。

### 10.3 稳态可达性预检查

UI 在用户编辑时实时计算目标工况可达性。

Tank 2 目标液位为 `h2`，Tank 2 出口面积为 `a2`：

```text
q_required = a2 × sqrt(2 × g × h2)
```

预计阀位：

```text
opening_required = q_required / (source_flow × flow_coefficient) × 100%
```

Tank 1 预计稳态液位：

```text
h1_steady = (q_required / a1)² / (2 × g)
```

其中：

```text
g = 9.81 m/s²
```

硬错误：

- `source_flow × flow_coefficient < q_required`；
- `h1_steady > tank_1.height`；
- `h2 > tank_2.height`。

警告但允许保存：

- 预计阀位低于 10%；
- 预计阀位高于 90%；
- 初始液位距离 0 或满量程不足 5%；
- 用户设置的控制周期相对于阀门行程时间过大；
- PID 参数可能造成明显激进或迟缓响应。

组态面板显示类似：

```text
预计稳态：可达
Tank 1 ≈ 0.512 m
Tank 2 ≈ 0.800 m
阀门开度 ≈ 66%
```

该预检查只用于可行性提示，不替代真实仿真结果。

---

## 11. 配置、运行实例和在线调参的状态模型

前端必须同时维护三个明确对象：

```text
savedConfig   磁盘上最近保存的 DSL
draftConfig   用户当前正在编辑、可能未保存的草稿
runningConfig 当前 DataFactory 进程启动时采用的配置标识
```

不得只维护一个 `config` 对象并在保存、运行和编辑之间复用。

建议状态：

```text
STOPPED_EDITING
STARTING
SIMULATION_RUNNING
REALTIME_RUNNING
BATCH_RUNNING
STOPPING
ERROR
```

关键规则：

1. 设备结构参数修改只影响 `draftConfig`；
2. 保存把 draft 写入磁盘，但不改变 running；
3. 保存并仿真会重建运行实例；
4. 在线写值只改变 running；
5. “保存当前调参”才把白名单运行参数同步回 draft 并保存；
6. 页面始终显示 draft 是否与 saved、running 一致；
7. WebSocket 断开时冻结最后值并显示“数据已过期”，不得继续播放伪动画。

---

## 12. 推荐技术栈与架构

### 12.1 技术选型

沿用当前项目技术，不新增另一个框架：

| 层级 | 技术 |
|---|---|
| 桌面容器 | Wails v2 |
| 前端 | React 18 + TypeScript + Vite |
| 样式 | Tailwind CSS |
| 状态 | Zustand |
| P&ID | React 自定义 SVG |
| 趋势 | Recharts |
| 文件/对话框/子进程 | Wails Go |
| DSL 执行 | 当前 Python DataFactory |
| 内部控制 | FastAPI REST |
| 内部实时数据 | FastAPI WebSocket |
| 外部工业协议 | OPC UA |

### 12.2 统一入口

以 `config-tool` 为唯一主入口，吸收必要的调试能力。`debug_gui` 暂时保留代码，但不并行开发同一功能。

### 12.3 数据链路

```text
React UI
  ├─ Wails Go：打开/保存 YAML、启动/停止 DataFactory、选择导出路径
  ├─ FastAPI REST：状态、元数据、在线写值、最近快照、导出
  └─ FastAPI WebSocket：每周期实时快照

Python DataFactory
  ├─ Engine：唯一实时状态真源
  ├─ FastAPI：内部 GUI 接口
  └─ OPC UA：外部 AI 和标准客户端接口
```

内部 GUI 不通过 OPC UA 轮询。这样可以避免地址空间浏览、命名空间和高频轮询的额外复杂度；OPC UA 保留为外部接口。

### 12.4 元数据真源

Python `BaseProgram` 的 `stored_attributes`、`input_schema`、`default_params` 和 `param_descriptions` 是组件语义真源。

现有 `config-tool` 内嵌的 `components.json` 可能与 Python 新版 PID 发生漂移。实施时必须：

- 核对并更新生成流程；或
- 在运行状态通过 FastAPI `/meta` 获取最新元数据；
- 模板定义文件只保存视觉布局、中文分组、单位转换和允许暴露字段，不复制 PID 算法语义。

不得再创建第三份手工维护的完整组件元数据。

---

## 13. 前端模块建议

可以按以下结构实现，文件名允许根据当前项目习惯调整，但职责不能混在一个巨大组件中：

```text
config-tool/frontend/src/features/templates/
  types.ts
  TemplateWorkspace.tsx
  ObjectInspector.tsx
  RuntimeToolbar.tsx
  RuntimeTrendPanel.tsx
  PidFaceplate.tsx

config-tool/frontend/src/features/templates/secondOrderTank/
  definition.ts
  SecondOrderTankPage.tsx
  SecondOrderTankDiagram.tsx
  SecondOrderTankInspector.tsx
  bindings.ts
  conversions.ts
  validation.ts

config-tool/frontend/src/features/runtime/
  runtimeApi.ts
  useRuntimeStore.ts
  websocket.ts
  trendBuffer.ts
```

### 13.1 模板定义

为将来另外两个模板建立最小 `TemplateDefinition`，内容只包括：

- 模板 ID 和中文名称；
- 基础 DSL 文件名；
- 固定对象列表；
- SVG 角色和实例名绑定；
- 对象允许显示/编辑的字段；
- 单位转换；
- 推荐趋势位号；
- 可行性校验函数。

不要把任意 DSL 拖拽、图自动布局或通用表达式编辑塞进 `TemplateDefinition`。

### 13.2 Zustand 状态拆分

至少包含：

```text
templateId
savedConfig
draftConfig
runningConfigIdentity
selectedObjectId
runtimeState
latestSnapshot
snapshotReceivedAt
trendSeries
trendEvents
previousRunSeries
validationErrors
validationWarnings
dirtyPaths
```

`latestSnapshot` 与 `draftConfig` 必须分开，运行快照不能覆盖组态草稿。

### 13.3 WebSocket 更新

- 只保留最新 snapshot 作为现场图数据；
- 趋势使用固定容量环形缓冲；
- WebSocket 心跳不写入趋势；
- 断线后指数退避重连；
- 重连后先调用 snapshot REST 获取一次完整状态；
- 对 0.5 s 周期无需制造 60 FPS 插值；
- 流量动画可以平滑，但显示数值必须来自最后快照。

---

## 14. 后端与 Wails 需要补充的能力

### 14.1 Wails Go

优先扩展 `config-tool/internal/bindings/SystemBinding`，不要复制 `debug_gui` 的进程管理形成两套实现。

需要保证：

1. 启动调试/实时实例时传入 `--api` 和独立 `--api-port`；
2. 启动后轮询 `/api/status`，确认 API 和 Engine 均就绪；
3. 保存、另存为和覆盖确认由 Wails 文件对话框完成；
4. 同一时刻只允许一个受当前页面管理的实时实例；
5. 停止后回收 DataFactory 子进程和端口；
6. 批量任务结束后返回 CSV 路径和退出状态；
7. 子进程失败时把 stderr 和退出码传给前端；
8. 应用退出时清理受管理子进程。

### 14.2 FastAPI

保留现有：

```text
GET  /api/status
GET  /api/instances/{runtime}/meta
GET  /api/instances/{runtime}/snapshot
POST /api/instances/{runtime}/export
WS   /ws/snapshot
```

新增或修正原子批量写值接口，建议：

```text
POST /api/instances/{runtime}/writes
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

响应至少包括：

```json
{
  "ok": true,
  "queued": 3,
  "apply_semantics": "next_cycle_boundary"
}
```

Engine 应在同一周期边界应用整批写值。可在 `controller/engine.py` 增加最小批量队列方法；不得因此改写计算主循环。

现有 `/api/instances/{name}/params` 需要检查路径中的 `name` 到底代表运行实例还是 Program 实例。不得把运行实例名错误地传给 `queue_param_update()` 后假装写入了 `pid2`。

在线写值完成后，最终值以 WebSocket 下一次快照为准，REST 成功只代表已入队。

### 14.3 快照契约

前端至少依赖：

```text
cycle_count
sim_time
source_flow
valve_1.target_opening
valve_1.current_opening
valve_1.inlet_flow
valve_1.outlet_flow
tank_1.level
tank_1.inlet_flow
tank_1.outlet_flow
tank_2.level
tank_2.inlet_flow
tank_2.outlet_flow
pid2.PV
pid2.SV
pid2.CSV
pid2.MV
pid2.PB
pid2.TI
pid2.TD
pid2.KD
pid2.MODE
pid2.SWPN
```

若快照键名实际不同，应以当前 Engine 输出为准修正绑定，但禁止改变 DSL 和上游位号来迁就前端。

---

## 15. 保存策略

### 15.1 基础模板与用户方案

内置基础模板是：

```text
config/单阀门二阶水箱.yaml
```

用户第一次修改后默认“另存为”，例如：

```text
config/user/二阶水箱_液位08_方案1.yaml
```

若当前项目不希望创建子目录，可保存到现有 `config/`，但必须避免静默覆盖基础模板。

### 15.2 保存完整 DSL

本任务继续保存可直接运行的完整 DSL，而不是只保存前端私有 JSON。

为了将来升级模板，可以额外保存轻量模板标识或 sidecar 元数据，但第一版不得让 DataFactory 依赖前端专有文件才能运行。

最终保存的 YAML 必须能被：

```text
python standalone_main.py -c <saved-yaml>
```

直接运行。

### 15.3 在线调参写回白名单

允许写回：

```text
SV
MODE
PB
TI
TD
KD
SWPN
SVSCL/SVSCH
SVL/SVH
MVSCL/MVSCH
MVL/MVH
```

`MV` 只有在用户明确选择“把当前手动输出作为初始 MV”时才写回。

禁止自动写回：

```text
PV
AUTO
CAS
当前 tank level
当前 valve current_opening
运行时累计状态
```

---

## 16. 控制品质展示

为了让用户判断调参好坏，除了趋势图，当前运行可计算并显示：

- 最大超调；
- 稳态误差；
- 进入误差带的稳定时间；
- MV 饱和累计时间；
- 液位触及 0 或高度上限的次数；
- 当前运行是否已经进入稳定窗口。

第一版可采用简单定义：

```text
误差带 = max(0.01 m, SV 量程的 2%)
稳定 = 连续 60 s 位于误差带内
```

这些指标是界面辅助判断，不写入 DSL，也不改变 PID 算法。

参数变化后重新开始当前指标统计，并保留上一轮完整结果作为对照。

---

## 17. 实施顺序

Agent 应按以下顺序实现，但最终可以一次提交，不需要每个小步骤等待确认。

### 步骤 1：保护现有能力

- 运行现有 Python 测试；
- 运行 `config-tool` Go 测试；
- 运行前端 TypeScript/Vite build；
- 记录现有失败，不得把用户已有问题归因于本任务；
- 不删除现有 React Flow 组态和仿真页面。

### 步骤 2：建立模板入口和状态模型

- 在 `config-tool` 增加模板工作区；
- 默认能识别 `单阀门二阶水箱.yaml`；
- 建立 saved/draft/running 三份状态；
- 完成 dirty、校验和保存状态。

### 步骤 3：实现固定 SVG 流程图

- 绘制水源、阀门、两只水箱、管线、LT 和 PID；
- 完成选中、高亮和右侧对象切换；
- 停止状态绑定配置初值；
- 完成单位转换和稳态可行性预检查。

### 步骤 4：实现右侧组态检查器

- 按对象展示参数；
- 区分基础/高级；
- 区分重启生效/在线生效；
- 实现保存、另存为和重新加载；
- 保存结果必须通过 DSL Parser。

### 步骤 5：接入实时运行

- 扩展 Wails 启动命令传入 FastAPI 参数；
- 等待 API ready；
- 接入 status、meta、snapshot 和 WebSocket；
- SVG 绑定实时快照；
- 实现断线、重连和停止清理。

### 步骤 6：实现在线写值

- 增加原子批量写接口；
- 支持 AUTO/MAN、SV/MV、PB/TI/TD/KD；
- 记录趋势事件；
- 实现“保存当前调参到 DSL”。

### 步骤 7：趋势和批量仿真

- 复用/整理现有 Recharts；
- 使用环形缓冲；
- 保留上一轮对照；
- 运行批量生成并加载结果；
- 大数据下采样；
- CSV 导出。

### 步骤 8：回归和验收

- 完成前端组件测试；
- 完成 Go YAML/进程测试；
- 完成 FastAPI 写值测试；
- 完成至少一条端到端调试运行测试；
- 运行现有全量测试和 build。

---

## 18. 必须增加的测试

### 18.1 前端纯函数测试

至少覆盖：

```text
m³/s ↔ L/min
outlet_area ↔ diameter_mm
水箱容量
目标流量和预计阀位
Tank 1 预计稳态液位
SV 超高
目标流量不可达
Tank 1 预计溢流
draft/saved/running dirty 判断
在线调参写回白名单
批量结果下采样
```

### 18.2 SVG/组件测试

至少覆盖：

- 停止状态使用 `initial_level`；
- 运行状态使用 snapshot `level`；
- 阀门使用 `current_opening`；
- Tank 2 显示 SV 标线；
- 点击每个对象切换检查器；
- WebSocket 断开显示过期状态；
- AUTO/MAN 正确启用或禁用 SV/MV 输入。

### 18.3 Go/YAML 测试

至少覆盖：

- 导入当前结构化二阶水箱 YAML；
- 修改后导出并再次导入；
- `params`、`inputs`、`execute_first` 不丢失；
- Variable 的值不被错误转换成 `source_flow.out`；
- Unicode 文件名和中文路径；
- 另存为不覆盖原模板；
- 启动参数包含 `--api`；
- 停止能释放子进程和端口。

### 18.4 FastAPI/Engine 测试

至少覆盖：

- status ready；
- snapshot 包含目标位号；
- 批量写入 PB/TI/TD 在同一周期应用；
- 写 `pid2.SV` 后下一快照反映新值；
- MAN 下写 MV 生效；
- 非法 tag 返回明确错误，不得静默成功；
- WebSocket 心跳和断开清理；
- 多客户端不会让 Engine 重复计算。

### 18.5 端到端场景

至少完成以下场景：

1. 打开默认模板；
2. 页面显示 72 L/min、两只 84.8 L 水箱、0.15/0.10 m 初始液位和 0.8 m SV；
3. 点击水源、阀门、Tank 1、Tank 2、LT 和 PID，检查器内容正确；
4. 把 Tank 2 半径改为 0.18 m，另存为新 DSL；
5. 重新加载新 DSL，参数保持；
6. 设置 SV 超过 Tank 2 高度，保存和启动被阻止；
7. 恢复合法值并“保存并重新仿真”；
8. 水箱液位、阀位和流量随快照变化；
9. 在线把 SV 从 0.8 改为 0.6，下一周期生效并产生事件标记；
10. 在线批量修改 PB/TI/TD；
11. 停止并把当前调参保存到 DSL；
12. 重新启动后 PID 参数来自保存值；
13. 运行 2,000 周期批量仿真，显示趋势并导出 CSV；
14. 启动实时运行，OPC UA 客户端写入 SV 后画面更新；
15. 关闭应用后无残留受管理子进程。

---

## 19. 验收标准

只有同时满足以下条件才算完成：

1. `config-tool` 成为该模板唯一用户入口；
2. 固定流程图看起来像简化现场 P&ID，而不是 React Flow 方框图；
3. 停止状态显示 DSL 初值，运行状态显示 Engine 实时值；
4. 点击对象能看到正确实例名、类型和参数；
5. 保存后的 YAML 可以被现有 DataFactory 直接运行；
6. 设备参数修改明确要求重启；
7. PID 在线调参能在下一个周期真实生效；
8. 保存 DSL、当前草稿和当前运行配置不会混淆；
9. 仿真和实时运行复用同一画面；
10. 外部 OPC UA 写值能通过下一次快照显示；
11. 趋势能够支持修改前后对照；
12. 批量生成不会把全部大数据直接绘制到 Recharts；
13. WebSocket 断线有清晰状态，不继续显示伪实时动画；
14. 不改变 `PV/SV/CSV/MV/PB/TI/TD/MODE` 等位号后缀；
15. 不修改水箱、阀门和 PID 核心算法；
16. 现有通用 DSL 画布没有回归；
17. 前端 build、Go tests、Python tests 通过；
18. 仓库中没有运行时生成的临时 CSV、临时 YAML、日志或未跟踪测试目录。

---

## 20. Agent 最终回报格式

实现完成后一次性回报：

```text
1. 修改/新增文件列表
2. 页面入口和启动方式
3. DSL 导入、保存和另存为实现
4. SVG 对象与位号绑定表
5. saved/draft/running 状态处理
6. FastAPI/WebSocket 和在线写值接口
7. 调试仿真、实时运行和批量生成结果
8. 新增测试及结果
9. 前端 build、Go tests、Python tests 结果
10. 已知限制和与本设计的偏差
```

如果某项无法完成，不得静默删减或用假数据展示，应说明具体阻塞、已完成范围及最小后续动作。

---

## 21. 最重要的实现原则

本任务的核心不是“画两个会动的水箱”，而是建立清晰可信的用户操作闭环：

```text
打开模板
→ 点击现场对象
→ 修改组态
→ 校验并保存
→ 保存并重新仿真
→ 看现场动画和趋势
→ 在线调 PID
→ 对比控制效果
→ 保存满意方案
→ 实时运行并通过 OPC UA 对外提供数据
```

同一张画面可以同时承担组态和监控，但必须始终让用户分清：

```text
磁盘上已保存的 DSL
当前未保存的组态草稿
当前正在运行实例采用的配置
当前实例上的临时在线调参
```

只要这四种状态不混淆，第一份可视化 DSL 模板就具备继续扩展到串级水箱和精馏塔的可靠基础。
