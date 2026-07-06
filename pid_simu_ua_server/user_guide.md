# pid_simu_ua_server 用户手册

> PyQt6 桌面工具，把"圆柱水箱 + 阀 + PID"的一次性仿真结果导出 CSV，再回放成 OPC UA Server，给 UAExpert / KEPServer / SCADA 之类的工业客户端订阅读数。
>
> **当前版本**：v3
>
> **当前状态**：**代码无法直接启动**。`simulation_thread.py` 顶部四个 import 指向旧的 `plc.Clock / module.CylindricalTank / module.Valve / algorithm.PID`，这些包已经被搬走，仓库里不存在了。运行 `python main.py` 会立刻 `ModuleNotFoundError`，主窗口不会弹出。
>
> 详细说明见第 5 节。
>
> designed by yzc

---

## 1. 这是什么

`pid_simu_ua_server_v3` 是一个 **PyQt6 桌面应用**，做一次性 PID 控制回路仿真，然后把仿真结果作为 OPC UA Server 循环播放给工业客户端。三段式工作流：

1. **填参数**：界面左半边配水箱 / 阀 / PID，界面右半边看实时 SV / PV / MV 曲线；
2. **跑仿真**：点 "开始模拟"，PID + 水箱 + 阀在内部循环跑出 `data_records`；
3. **做两件事之一**：
   - 导出 CSV / Excel（预测模板、PID 整定模板、TPT 导入位号模板）给下游工具；
   - 启动内置 OPC UA Server，把 `data_records` 推送到工业客户端。

整套数据通路在单进程里，没有外部依赖服务。

> 文档里所有"界面元素"和"默认值"都来自 `main_window.py` 的源码；行为细节来自 `simulation_thread.py` / `opcua_server_thread.py` / `export_handler.py` 等。

---

## 2. 使用入门

### 2.1 启动方式

按设计，源码启动方式：

```cmd
python main.py
```

启动后会弹出主窗口，标题栏写 `PID模拟与OPCUA Server工具 v3`，右下角水印 `pid_simu_ua_server_v3 designed by @yuzechao`，窗口尺寸 1600×900。

> **当前已知问题**：`main.py` → `main_window.py` → `simulation_thread.py` 的 import 链是断的。运行 `python main.py` 会直接抛 `ModuleNotFoundError: No module named 'plc'`（以及 `'module'`、`'algorithm'`），主窗口不会弹出。等代码修复后才能正常启动；详见第 5 节。**在使用前请先确认你的工程已经合并了 import 修复。**

### 2.2 工程依赖

源码方式运行需要：

- Python 3.10+（建议）
- `PyQt6`
- `asyncua`（OPC UA 异步服务器）
- `matplotlib`（Qt5Agg 后端，被 `main_window.py` 强制设置）
- `openpyxl`（TPT 模板导出，可选；缺这个库时 "TPT导入位号模板" 按钮会报错提示安装）

> 当前没有 PyInstaller 打包产物；如果有内部分发需求，需要先解决第 5 节的 import 问题再做打包。

### 2.3 操作系统

- **Windows** 10 / 11（开发与验证机）
- **Linux**：理论上可行（PyQt6 + asyncua 都跨平台），但 import 修复前不要尝试

### 2.4 停止

仿真进行中无法中途取消——只能等它跑完或直接关窗口。OPC UA Server 在跑的时候可以点 "停止服务器"。

---

## 3. 界面介绍

主窗口分上下两栏，中间一条横向分隔线：

### 3.1 上半：PID 仿真区

```
┌─────────────────────────┬─────────────────────────────┐
│  参数（左，垂直堆叠）    │   PID控制曲线（右，matplotlib）│
│   - 水箱参数             │   - 双 Y 轴：左 SV/PV，右 MV  │
│   - 阀门参数             │   - 实时绘制，标题"PID控制曲线"│
│   - PID参数              │                             │
│   - 模拟设置             │   位号列表（两行四列，跟随     │
│   - 实例名 + 模板按钮    │   实例名变化实时更新）         │
│   - 开始模拟             │                             │
│   - 时间拉伸 + 导出按钮  │                             │
│   - 数据源名称 + TPT导出 │                             │
│   - 进度条               │                             │
└─────────────────────────┴─────────────────────────────┘
```

> 左侧负责配置和触发控制，右侧负责观察曲线 + 显示最终位号清单。仿真跑完后位号清单就是 OPC UA 地址空间里会出现哪些节点的"预览"。

### 3.2 下半：OPCUA 服务器区

```
┌────────────────────────────────────────────────────────┐
│ OPCUA服务器配置                                         │
│   端口 [18951]            [启动服务器]  [停止服务器]    │
├────────────────────────────────────────────────────────┤
│ 数据轮询进度                                             │
│   进度条                                                  │
│   状态文字（"等待开始..." / "正在启动..." / 进度百分比） │
└────────────────────────────────────────────────────────┘
```

服务器只在仿真跑完、数据有了之后才允许点 "启动服务器"。

### 3.3 底部右下角

水印：`pid_simu_ua_server_v3 designed by @yuzechao`（灰色 10px 字体，永远显示）。

---

## 4. 功能介绍

### 4.1 工作流总述

```
填写参数 ─► 点"开始模拟" ─► 看实时曲线 ─► 仿真完成
                                      │
                                      ├──► 导出 CSV / Excel（预测 / 整定 / TPT 模板）
                                      │
                                      └──► 点"启动服务器" ─► UA 客户端连进来读数
                                              │
                                              └─► 点"停止服务器"
```

仿真与回放是两段独立的生命周期：仿真只跑一次，回放可以无限循环（`opcua_server_thread.py` 的 `_poll_data_loop` 是 `while self._running` 包 `while self._current_index < len(...)`，跑到末尾回到索引 0 重新来）。

### 4.2 PID 仿真参数（左侧表单）

以下默认值都来自 `main_window.py._set_default_values`，可直接在 UI 上看到。

#### 4.2.1 水箱参数（CylindricalTank）

| 字段 | 含义 | 单位 | 默认值 | 校验 |
| --- | --- | --- | --- | --- |
| 高度 | 水箱高度 | m | 2.0 | > 0 |
| 半径 | 水箱半径 | m | 0.5 | > 0 |
| 入水口面积 | 进水口截面积 | m² | 0.06 | > 0 |
| 入水速度 | 进水流速（用于计算入口体积流量） | m/s | 3.0 | ≥ 0 |
| 出水口面积 | 底部出水口截面积 | m² | 0.001 | > 0 |
| 初始水位 | 仿真开始时的水位 | m | 0.0 | ≥ 0 |

#### 4.2.2 阀门参数（Valve）

| 字段 | 含义 | 单位 | 默认值 | 校验 |
| --- | --- | --- | --- | --- |
| 最小开度 | 阀门开度下限 | % | 0.0 | 0–100 |
| 最大开度 | 阀门开度上限 | % | 100.0 | 0–100，且 > 最小开度 |
| 满行程时间 | 阀门从最小开到最大开度需要的时间 | s | 5.0 | > 0 |

#### 4.2.3 PID 参数（PID）

| 字段 | 含义 | 单位 | 默认值 | 校验 |
| --- | --- | --- | --- | --- |
| 比例系数 (Kp) | 比例增益 | — | 12.0 | ≥ 0 |
| 积分时间 (Ti) | 积分时间常数 | s | 30.0 | ≥ 0 |
| 微分时间 (Td) | 微分时间常数 | s | 0.15 | ≥ 0 |
| 设定值 (SV) | **多值，逗号分隔**，如 `1.5,0.5,0` | — | `1.5,0.5,0` | ≥ 1 个 |
| 过程值 (PV) | 初始 PV | — | 0.0 | — |
| 输出值 (MV) | 初始 MV | — | 0.0 | — |
| 输出上限 (H) | MV 上限 | % | 100.0 | > 输出下限 |
| 输出下限 (L) | MV 下限 | % | 0.0 | < 输出上限 |

> **SV 多值怎么用**：你写 `1.5,0.5,0`，仿真时长会被均分成 N 段（N = SV 个数），每段用对应的 SV。例：时长 900s、`1.5,0.5,0` 三段 → 前 300s 用 1.5，中间 300s 用 0.5，后 300s 用 0。这是一个内置的"分段阶跃"测试曲线生成方式。
>
> 只写一个值（`1.5`）也行，相当于恒定 SV。

#### 4.2.4 模拟设置 + 实例名

| 字段 | 含义 | 默认值 |
| --- | --- | --- |
| 模拟时长 | 仿真跑多久 | 900.0 秒 |
| 实例名 | 用于 CSV 表头 / OPC UA NodeId / 位号列表前缀 | `PID_TEST_1` |
| 时间拉伸 | 导出时把仿真秒数乘以这个倍数再写到时间戳上 | 1 |
| 数据源名称 | TPT 导入位号模板里"数据源名称"列填什么 | `yzc_test` |

> **实例名**：影响一切"标签化"输出的前缀。改了它，右侧"位号列表"预览会实时更新；改了它再导 CSV，CSV 表头会跟着变；改了它再起服务器，OPC UA NodeId 里的前缀也会变。**重启服务器才能让 NodeId 改变生效**。

### 4.3 仿真内部数据流（用户视角）

仿真线程 `SimulationThread` 跑一个固定步长 0.5 秒的循环（`cycle_time=0.5`），逻辑闭环：

```
PID(输出 MV)
   ↓ 阀门 target_opening
Valve.execute(step=0.5s) → 当前开度
   ↓ 水箱 valve_opening
Tank.execute(step=0.5s) → 当前液位（PV 来自这里）
   ↓
PID(输入 PV)
```

每周期往 `data_records` 里追加一行字典，键名见下表：

| 键 | 含义 | 备注 |
| --- | --- | --- |
| `sim_time` | 仿真秒数 | 从 0 开始递增 |
| `pid.sv` / `pid.pv` / `pid.mv` | 设定值 / 过程值 / 输出值 | 仿真主量 |
| `pid.kp` / `pid.ti` / `pid.td` | 三个 PID 系数 | 仿真过程中不变 |
| `pid.pb` | 比例带 | **数值恒等于 Kp** |
| `pid.mode` | PID 模式 | 固定为 20 |
| `pid.cas` | 级联标志 | 固定为 0 |
| `pid.swpn` | 开关逻辑 | 固定为 1 |
| `pid.svsch` / `pid.svh` | SV 上量程 / 工程上限 | 等于水箱高度 |
| `pid.svscl` / `pid.mvscl` / `pid.svl` / `pid.mvl` | 各类下限 | 固定为 0 |
| `pid.mvsch` / `pid.mvh` | MV 上量程 / 工程上限 | 固定为 100 |
| `tank.level` | 水箱当前液位（米） | 仿真过程中由 PID 闭环驱动 |
| `valve.current_opening` | 阀门当前开度（%） | PID 输出折算过来的 |

> 上表中"固定"的值是当前代码硬编码的常量，UI 上没有让用户改的入口。这部分 PID 上下限位号（svh / svl / mvh / mvl 等）模拟的是 SCADA 系统里 PID 块的标准量程。

### 4.4 模板（JSON）

界面提供两个按钮：

- **导出模板**：把当前所有参数（水箱 / 阀 / PID / 模拟时长）打包成 JSON，落盘。默认文件名 `pid_template_YYYYMMDD_HHMMSS.json`。
- **导入模板**：从 JSON 文件读回，逐项填到左侧表单上。

JSON 结构示例（直接复制可被工具识别）：

```json
{
    "tank": {
        "height": "2.0",
        "radius": "0.5",
        "inlet_area": "0.06",
        "inlet_velocity": "3.0",
        "outlet_area": "0.001",
        "initial_level": "0.0"
    },
    "valve": {
        "min_opening": "0.0",
        "max_opening": "100.0",
        "full_travel_time": "5.0"
    },
    "pid": {
        "kp": "12.0",
        "ti": "30.0",
        "td": "0.15",
        "sv": "1.5,0.5,0",
        "pv": "0.0",
        "mv": "0.0",
        "h": "100.0",
        "l": "0.0"
    },
    "simulation": {
        "duration": "900.0"
    }
}
```

> 模板不保存实例名 / TPT 数据源名称 / 时间拉伸——这些是"导出设置"，不是仿真参数。

### 4.5 数据导出（CSV / Excel）

仿真跑完后导出按钮才可用。三个出口：

| 按钮 | 目标格式 | 默认文件名 | 列结构 |
| --- | --- | --- | --- |
| 导出数据[预测模板] | CSV | `pid_export_YYYYMMDD_HHMMSS.csv` | timeStamp + 19 个 PID/tank/valve 位号（全部） |
| 导出数据[PID整定模板] | CSV | `pid_tuning_export_YYYYMMDD_HHMMSS.csv` | 时间 + PV + MV + SV（精简三列） |
| TPT导入位号模板 | Excel (.xlsx) | `tpt_tag_template_YYYYMMDD_HHMMSS.xlsx` | TPT 导入需要的一位号清单（不含数据） |

#### 4.5.1 预测模板（CSV）

时间戳列写法：`2024/6/3 19:00:00`（月份和日期不补零，小时分钟秒补零）。基准时间是 `2024-06-03 19:00:00`（`constants.DEFAULT_BASE_TIME`），每条记录的时间戳 = 基准时间 + sim_time × 时间拉伸。

**每秒采样一条**（不是按 `cycle_time` 0.5 秒；`sample_records_per_second` 累加 sim_time 跨过 1.0 才写入一行）。原始仿真秒数跨度 = 第一条到最后一条 sim_time 的差；拉伸后跨度 = 该差 × time_stretch。

完整可用 CSV 示例（前 5 行，按实例名 `PID_TEST_3`、time_stretch=1）：

```csv
Timestamp,PID_TEST_3_pid.MV,PID_TEST_3_pid.SV,PID_TEST_3_pid.PV,PID_TEST_3_pid.KP,PID_TEST_3_pid.PB,PID_TEST_3_pid.TD,PID_TEST_3_pid.TI,PID_TEST_3_pid.MODE,PID_TEST_3_pid.CAS,PID_TEST_3_pid.SWPN,PID_TEST_3_pid.SVSCH,PID_TEST_3_pid.SVH,PID_TEST_3_pid.SVSCL,PID_TEST_3_pid.MVSCL,PID_TEST_3_pid.SVL,PID_TEST_3_pid.MVL,PID_TEST_3_pid.MVSCH,PID_TEST_3_pid.MVH,PID_TEST_3_tank.LEVEL,PID_TEST_3_valve.CURRENT_OPENING
2024-6-3 19:00:00,18.300000,1.500000,0.000000,12.000000,12.000000,0.150000,30.000000,20.000000,0.000000,1.000000,2.000000,2.000000,0.000000,0.000000,0.000000,0.000000,100.000000,100.000000,0.011459,10.000000
2024-6-3 19:00:01,18.429192,1.500000,0.032264,12.000000,12.000000,0.150000,30.000000,20.000000,0.000000,1.000000,2.000000,2.000000,0.000000,0.000000,0.000000,0.000000,100.000000,100.000000,0.052876,18.429192
2024-6-3 19:00:02,18.511399,1.500000,0.073395,12.000000,12.000000,0.150000,30.000000,20.000000,0.000000,1.000000,2.000000,2.000000,0.000000,0.000000,0.000000,0.000000,100.000000,100.000000,0.093843,18.511399
2024-6-3 19:00:03,18.580184,1.500000,0.114233,12.000000,12.000000,0.150000,30.000000,20.000000,0.000000,1.000000,2.000000,2.000000,0.000000,0.000000,0.000000,0.000000,100.000000,100.000000,0.134571,18.580184
```

> **注意：CSV 顶部只有一行表头，没有第二行中文描述**——`export_prediction_template` 里实际写出的就是单行表头 + 数据。这个工具内部状态机的"中文描述行"代码虽然存在，但写成 CSV 时并不会再写一行。如果下游脚本期待"描述行"，目前是要手工追加或者改一下 `export_handler.py`。

#### 4.5.2 PID 整定模板（CSV）

精简三列 + 标准时间戳 `yyyy-MM-dd HH:mm:ss`：

```csv
时间,PID_TEST_3_pid.PV,PID_TEST_3_pid.MV,PID_TEST_3_pid.SV
2024-06-03 19:00:00,0.000000,18.300000,1.500000
2024-06-03 19:00:01,0.032264,18.429192,1.500000
2024-06-03 19:00:02,0.073395,18.511399,1.500000
```

同样每秒一条，时间戳规则同预测模板。

#### 4.5.3 TPT 导入位号模板（Excel .xlsx）

> 这个是**位号清单**，不是仿真数据。TPT 是另一个工具的位号导入格式。

列结构（与内置 `tpt_tag_template_20251204_181236.xlsx` 一致）：

| 列 | 内容 |
| --- | --- |
| 系统位号名 | `{实例名}_pid.MV` 这种完整位号名 |
| 底层位号名 | `1_{系统位号名}`（namespace=1） |
| 位号类型 | 一次位号 |
| 数据源名称（一次位号） | 界面上"数据源名称"输入框 |
| 数据类型 | DOUBLE |
| 采集频率 | 1 |
| 缓存数量 | 100 |
| 是否为向量位号 | TRUE |
| 描述 | 与系统位号名相同 |
| 节点名 | 根节点 |

> 必须先装 `openpyxl`（`pip install openpyxl`），否则按钮点了会报错。

### 4.6 OPC UA Server

#### 4.6.1 启动条件

必须先跑完仿真（有 `data_records`），"启动服务器" 按钮才会启用。启动前工具会做端口占用检查（占用会弹对话框问是否继续），并验证端口号在 1–65535 之间。

#### 4.6.2 监听端口

- 默认 `18951`（界面输入框预填）
- 范围 1–65535
- 端点：`opc.tcp://0.0.0.0:{port}`（绑所有网卡；跨机访问把客户端里的 `127.0.0.1` 换成运行机 IP）

> 不要和 `ua_player`（默认 18950）冲突；同时跑两个工具时把其中一个换端口。

#### 4.6.3 地址空间结构

- **命名空间**：`ns=1`（固定，不可改）
- **容器对象**：`Objects/PLC`
- **变量节点 NodeId**：`ns=1;s={实例名}_{prefix}.{SUFFIX}`，其中 `SUFFIX` 是大写
  - 例如实例名 `PID_TEST_3`、数据键 `pid.mv` → NodeId 字符串 `PID_TEST_3_pid.MV`
  - 例如 `tank.level` → `PID_TEST_3_tank.LEVEL`
  - 例如 `valve.current_opening` → `PID_TEST_3_valve.CURRENT_OPENING`
- **变量类型**：Double，所有节点只读（`set_writable(False)`）

浏览路径示意：

```
Objects
  └── PLC                         ← ns=1;s=PLC
       ├── PID_TEST_3_pid.MV          ← ns=1;s=PID_TEST_3_pid.MV
       ├── PID_TEST_3_pid.SV
       ├── PID_TEST_3_pid.PV
       ├── ...（共 19 个，见 4.3 表）
       └── PID_TEST_3_valve.CURRENT_OPENING
```

所有位号节点共 19 个，全部来自 `constants.TAG_DEFINITIONS`。

#### 4.6.4 客户端连上去

```cmd
opc.tcp://127.0.0.1:18951/
```

工具用的 `asyncua.Server()` 默认是 `NoSecurity`，不用配证书、用户名密码；UAExpert / KEPServerEX / 自家 SCADA 客户端直接连。

#### 4.6.5 数据循环播放节奏

时间间隔 = 当前 data_records 第 i 行与第 i+1 行的 sim_time 之差（默认 0.5s）。每写完所有节点，等待这个差值秒数才推下一帧；跑完最后一帧回到第 0 行重新开始（不停顿也无缝循环）。

界面进度条显示 `进度: 当前索引/总数 (百分比%) - 当前sim_time`，带"第 N 轮循环播放"提示文字。

#### 4.6.6 停止

点 "停止服务器" 按钮，等几秒状态从 "正在停止服务器..." 变成 "服务器已停止"，按钮恢复。

#### 4.6.7 安全策略 / 写入

- 只支持 `NoSecurity`（匿名无加密）
- 客户端能**读**，**不能写**所有节点都是只读
- 多个仿真数据连到同一端口不会冲突，但 NodeId 会被覆盖（见 4.6.8）

#### 4.6.8 多实例

理论上可以改不同端口同时跑多个进程，但每个进程里只有一个仿真 + 一个 Server。如果想在同一个 server 上跑两段仿真结果，需要自己改 `data_records` 来源。同一端口被占用时工具会弹对话框问是否继续——一般选"否"，换端口。

---

## 5. 已知问题与状态

### 5.1 启动失败（核心）

`simulation_thread.py` 第 13–16 行的：

```python
from plc.clock import Clock
from module.cylindrical_tank import CylindricalTank
from module.valve import Valve
from algorithm.pid import PID
```

仓库里**没有** `pid_simu_ua_server/plc/`、`module/`、`algorithm/` 这些目录——相关实现已经被搬到 `data_factory_server/controller/clock.py` 和 `data_factory_server/components/programs/`。

直接 `python main.py` 会立刻 `ModuleNotFoundError`，主窗口不会弹出。在 import 修复前，**整个工具都用不起来**。

### 5.2 物理模型对照（修复参考）

仓库里的实现搬到新位置后，物理模型和参数名没变，主要 API 形态：

| `simulation_thread.py` 里的用法 | `data_factory_server/` 新位置 | 说明 |
| --- | --- | --- |
| `Clock(cycle_time=0.5)` | `controller/clock.py` 的 `Clock`（`Clock(ClockConfig(cycle_time=0.5))`） | API 形态变了，需要用 `ClockConfig` 包装；但启动 / 步进概念一致 |
| `CylindricalTank(height, radius, inlet_area, inlet_velocity, outlet_area, initial_level)` | `components/programs/cylindrical_tank.py` 的 `CYLINDRICAL_TANK` | 新版参数去掉了入水口面积和入水速度（用 `execute(inlet_flow=...)` 注入流量），初始化签名不同 |
| `Valve(min_opening, max_opening, full_travel_time)` | `components/programs/valve.py` 的 `VALVE` | 概念保留 |
| `PID(kp, ti, td, sv, pv, mv, h, l)` | `components/programs/pid.py` 的 `PID` | 概念保留 |

> 等修复合并后，`simulation_thread.py` 顶部的 import 大致会变成 `from data_factory_server.controller.clock import Clock`（再加 `ClockConfig`）、`from data_factory_server.components.programs.{cylindrical_tank,valve,pid} import ...`。但具体的仿真逻辑（每周期怎么 `step`、怎么从水箱读 PV、怎么写 MV 到阀）也要按新 API 重写——这不是用户能做的。**等仓库有正式修复后再尝试启动。**

### 5.3 其它小坑

- **仿真没有中断按钮**：跑到一半想停，只能关窗口或者等；
- **导出按钮中途可点但会弹"没有数据可导出"**：仿真期间 `export_data_to_csv` 等按钮虽然运行时禁用，刚按完"开始模拟"还没启动的极短瞬间可能点得到；
- **OPC UA Server 没有写入权限**：所有节点只读；如果测试场景要求客户端写一个 SV 回 PID，目前没办法实现，要等代码扩展；
- **matplotlib 用的是 Qt5Agg 后端**而不是 Qt6Agg：在没装 Qt5 库时可能蹦 warning，但装了 PyQt6 一般没问题；
- **默认基准时间 2024-06-03 19:00:00** 是写死在常量里的，不会跟系统时间走，下游工具做时序拼接要小心；
- **循环播放不会从中间断点恢复**：OPC UA Server 跑起来后只能停，不能暂停继续。

---

## 6. 完整工作流示例（等 import 修复后）

1. 安装 Python 3.10+，装好依赖：`pip install PyQt6 asyncua matplotlib openpyxl`
2. 进入项目根目录（`pid_simu_ua_server/` 的父级目录，包含 `tool/` 和 `data_factory_server/`），运行：`python main.py`
3. 等主窗口弹出来，左侧表单保持默认值即可（已经能跑出一段 900s、`SV = 1.5 → 0.5 → 0` 的分段阶跃响应）
4. 改"实例名"为 `PID_TEST_3`（这个唯一会暴露在 OPC UA NodeId 里的字符串）
5. 点 "开始模拟"，看右边曲线 SV / PV / MV 实时出图；仿真完成会弹 "完成"
6. 点 "导出数据[预测模板]" → 默认文件名 `pid_export_<时间戳>.csv` → 保存。CSV 表头里 PID_TEST_3 开头
7. 点 "导出数据[PID整定模板]" → 得到三列 PV/MV/SV 的精简 CSV
8. 点 "TPT导入位号模板" → 需要填了"数据源名称"才能点 → 保存 xlsx
9. 下半部分 "OPCUA服务器配置" 端口保持 18951，点 "启动服务器"。状态文字变成 "OPCUA Server已启动，端口: 18951"
10. 用 UAExpert 连 `opc.tcp://127.0.0.1:18951/`，在 `Objects/PLC` 下找到 19 个 `PID_TEST_3_*` 节点，全部为 Double 只读
11. 节点值每 0.5 秒更新一次（按 `sim_time` 间隔），从第 0 行跑到最后一行循环；UI 进度条同步走
12. 收工点 "停止服务器"，关窗口

---

## 7. 速查：默认值一览

打开工具立刻能跑的配置（来自 `main_window.py._set_default_values`）：

| 模块 | 字段 | 默认值 |
| --- | --- | --- |
| 水箱 | 高度 / 半径 / 入水口面积 / 入水速度 / 出水口面积 / 初始水位 | 2.0 / 0.5 / 0.06 / 3.0 / 0.001 / 0.0 |
| 阀门 | 最小 / 最大开度 / 满行程时间 | 0.0 / 100.0 / 5.0 |
| PID | Kp / Ti / Td / SV / PV / MV / H / L | 12.0 / 30.0 / 0.15 / `1.5,0.5,0` / 0.0 / 0.0 / 100.0 / 0.0 |
| 模拟 | 时长 / 实例名 / 时间拉伸 / 数据源名称 | 900.0 / `PID_TEST_1` / 1 / `yzc_test` |
| Server | 端口 | 18951 |
| 仿真步长 | cycle_time | 0.5 s（不可在 UI 改）|

---

designed by yzc
