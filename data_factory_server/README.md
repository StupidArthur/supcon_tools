# Data Factory Next

> 统一数据模拟与播放架构 - 工业数据生成、实时模拟与数据管理平台

**Data Factory Next** 是一个高性能的工业数据生成与模拟平台，采用统一的有状态周期执行引擎，支持批量数据生成和实时周期运行两种模式。系统集成了消息总线、诊断系统、历史数据存储和 OPCUA 服务，为工业大模型测试、PLC 仿真、数据分析和系统集成提供强大的数据支撑。

## ✨ 核心特性

### 🎯 统一执行引擎

- **有状态周期执行**：采用统一的有状态周期执行模型，确保算法逻辑一致性
- **双模式运行**：
  - **GENERATOR 模式**：快速批量生成，不 sleep，适合离线数据生成和测试
  - **REALTIME 模式**：实时运行，按周期 sleep，适合在线模拟和系统集成
- **灵活采样控制**：执行周期与采样间隔分离，支持按需采样
- **动态配置管理**：支持运行时加载配置、修改参数、增删节点和变量

### 📊 强大的数据管理

- **实时数据推送**：自动推送到 Redis，支持 Pub/Sub 通知机制
- **历史数据存储**：基于 DuckDB 的高性能时序数据存储，支持按采样周期存储
- **数据查询接口**：提供历史查询、采样查询、统计查询和最新值查询
- **OPCUA 集成**：独立的 OPCUA Server，自动从 Redis 读取数据并更新节点，支持写值回传

### 🔧 灵活的配置系统

- **DSL 配置**：基于 YAML 的声明式配置，支持复杂的数据关系定义
- **表达式引擎**：支持数学函数、方法调用、属性访问和历史数据访问（`[-N]` 语法）
- **动态节点创建**：支持算法节点、模型节点和表达式节点的动态创建
- **命名空间支持**：支持多命名空间配置，便于模块化管理

### 🚌 消息总线架构

- **服务注册与发现**：基于 Redis 的服务注册中心，支持服务自动发现
- **组态同步**：Engine 自动推送组态变更，StorageService 和 OPCUA Server 自动同步
- **命令传递**：支持通过消息总线传递写值命令，实现 OPCUA 写值回传
- **事件通知**：基于 Pub/Sub 的事件通知机制，实现服务间解耦

### 📈 诊断系统

- **统一诊断框架**：基于 Redis 的集中式诊断数据存储
- **服务级诊断**：Engine、StorageService、OPCUA Server 各自提供诊断信息
- **实时监控**：秒级更新诊断数据，支持前端实时展示
- **性能指标**：执行时间、实时比、资源使用率、I/O 速率等关键指标

### 🌐 Web 管理界面

- **服务状态监控**：实时查看各服务运行状态和心跳信息
- **诊断信息展示**：可视化展示各服务的详细诊断数据
- **配置管理**：通过 Web 界面加载、修改配置
- **数据导出**：支持 CSV 格式数据导出，支持模板配置

## 🏗️ 系统架构

### 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                    UnifiedEngine                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Clock   │  │ Variable │  │ Expression│  │ Algorithm│   │
│  │          │  │  Store   │  │  Nodes   │  │  Nodes   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         │                    │                    │
    ┌────▼────┐         ┌─────▼─────┐      ┌──────▼──────┐
    │GENERATOR│         │ REALTIME   │      │ Message Bus │
    │  Mode   │         │   Mode     │      │             │
    └─────────┘         └────────────┘      └─────────────┘
         │                    │                    │
         │                    │                    │
    ┌────▼────┐         ┌─────▼─────┐      ┌──────▼──────┐
    │  List   │         │ Generator │      │  Redis +    │
    │ Return  │         │  Return   │      │  Pub/Sub    │
    └─────────┘         └────────────┘      └─────────────┘
                                                      │
                    ┌─────────────────────────────────┼─────────────────────┐
                    │                                 │                     │
            ┌───────▼──────┐              ┌──────────▼────────┐  ┌────────▼────────┐
            │StorageService│              │  OPCUA Server     │  │  Diagnostics    │
            │  (DuckDB)    │              │                   │  │  System         │
            └──────────────┘              └───────────────────┘  └─────────────────┘
```

### 服务架构

```
┌─────────────────────────────────────────────────────────────┐
│                    ServiceManager                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │    Engine    │  │ StorageService│  │ OPCUA Server │      │
│  │              │  │              │  │              │      │
│  │ - 实时运行   │  │ - 历史存储   │  │ - 节点更新   │      │
│  │ - 配置管理   │  │ - 批量写入   │  │ - 写值回传   │      │
│  │ - 数据推送   │  │ - 性能优化   │  │ - 动态节点   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Message Bus     │
                    │  (Redis Pub/Sub)  │
                    └───────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Redis (K-V)     │
                    │  - 实时数据       │
                    │  - 组态信息       │
                    │  - 诊断数据       │
                    └───────────────────┘
```

### 数据流

**GENERATOR 模式**：
```
配置文件 → DSLParser → UnifiedEngine → run_generator(n) → List[Snapshot]
```

**REALTIME 模式**：
```
配置文件 → UnifiedEngine → run_realtime() → Generator[Snapshot]
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
              Redis (实时)    DuckDB (历史)    OPCUA Server
                    │               │               │
                    └───────────────┼───────────────┘
                                    │
                            Message Bus (组态同步)
```

## 🚀 快速开始

### 环境要求

- Python >= 3.10
- Redis（用于实时数据管理和消息总线）
- DuckDB（自动安装，用于历史数据存储）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动方式

#### 1. WebService 联动启动（推荐）

通过 WebService API 启动，自动启动 Engine、StorageService 和 OPCUA Server：

```bash
# 启动后端服务
python web_backend/start_server.py

# 或使用函数参数方式
python -c "from web_backend.start_server import start_server; start_server(host='0.0.0.0', port=8000)"
```

启动前端界面（可选）：

```bash
cd web_frontend
npm install
npm run dev
```

访问 `http://localhost:5173` 查看 Web 管理界面。

#### 2. 独立启动存储服务

独立启动存储服务，从 Redis 读取数据并存储到 DuckDB：

```bash
python -m datacenter.run_storage_service
```

#### 3. 本地运行数据导出

使用导出运行器进行一次性数据导出：

```python
from services.export_runner import run_export

# 执行导出
result = run_export(
    config_path="classical_config/典型水箱液位控制.yaml",
    steps=1000,
    template_name="moban_1",
    output_path="output.csv"
)
```

### 基础使用

#### 1. 批量数据生成（GENERATOR 模式）

```python
from components import programs  # 注册程序类型
from components import functions  # 注册函数

from controller.parser import DSLParser
from controller.engine import UnifiedEngine

# 解析配置文件
parser = DSLParser()
config = parser.parse_file("classical_config/典型水箱液位控制.yaml")

# 创建引擎
engine = UnifiedEngine.from_program_config(config)

# 批量生成 10000 个周期的数据
results = engine.run_generator(10000)

# results 是一个列表，包含所有周期的快照
print(f"生成了 {len(results)} 个周期的数据")
```

#### 2. 实时运行（REALTIME 模式）

通过 WebService 启动，或使用 `services/realtime_runner.py`：

```python
from services.realtime_runner import RealtimeRunner, create_default_runner

# 创建实时运行器
runner = create_default_runner()

# 加载配置
from controller.parser import DSLParser
parser = DSLParser()
config = parser.parse_file("classical_config/典型水箱液位控制.yaml")
runner.load_config(config)

# 运行器已在后台运行，可通过 WebService API 交互
```

## 📝 配置示例

### DSL 配置文件格式

```yaml
# classical_config/典型水箱液位控制.yaml
cycle_time: 0.5              # 执行周期（秒）
sample_interval: 5.0         # 采样间隔（秒），可选
start_time: 0.0              # 起始时间
time_format: "%Y-%m-%d %H:%M:%S"  # 时间格式

program:
  # 算法/模型实例
  - name: sin1
    type: SIN
    init_args:
      amplitude: 100.0
      period: 1200
      phase: 0.0
    expression: sin1.execute()
  
  - name: valve1
    type: VALVE
    init_args:
      min_opening: 0.0
      max_opening: 100.0
      step: 0.1
      full_travel_time: 10.0
    expression: valve1.execute(target_opening=sin1.out)
  
  # 变量表达式
  - name: non_sense_3
    type: Variable
    expression: non_sense_3 = non_sense_1[-30] + 2 * sqrt(non_sense_2)
```

### 表达式语法

- **数学函数**：`sin()`, `cos()`, `sqrt()`, `log()`, `exp()` 等
- **方法调用**：`pid1.execute()`, `tank1.step()`
- **属性访问**：`sin1.out`, `pid1.mv`
- **历史数据访问**：`variable[-N]`（访问 N 个周期前的值）

## 💾 数据管理

### 实时数据管理（Redis）

**功能**：
- 每个周期自动推送数据到 Redis
- 更新 `data_factory:v2:current` 哈希（最新数据）
- 发布通知到 Pub/Sub 频道（通知 OPCUA 模块）

**Redis 数据结构**：
```json
// data_factory:v2:current (Hash)
// field: "default.tank1.level"
// value: {"v": 50.5, "t": 1234567890.123, "e": "default"}
```

### 历史数据存储（DuckDB）

**功能**：
- 基于 DuckDB 的高性能时序数据存储
- 按采样周期自动存储（使用 Clock 的 `need_sample`）
- 批量插入优化（每500条记录批量插入）
- 支持历史查询、采样查询、统计查询

**性能优化**：
- 批量插入：从单条插入优化为批量插入，写入速率提升 20+ 倍
- ID 生成优化：使用应用层计数器，避免数据库查询
- 缓冲区管理：智能缓冲区刷新，减少数据库交互

### OPCUA Server

**功能**：
- 独立的 OPCUA Server（通过 WebService 联动启动）
- 自动从 Redis 读取数据并更新节点
- 节点的 name、display_name、browse_name、node_id 都使用位号名
- 支持动态节点创建
- 支持写值功能（通过消息总线发送命令给 Engine）

**节点结构**：
```
Objects/
  └── DataFactory/
      ├── tank1.level
      ├── pid1.mv
      ├── pid1.pv
      └── valve1.current_opening
```

### 消息总线

**功能**：
- 服务注册与发现：基于 Redis 的服务注册中心
- 组态同步：Engine 推送组态变更，其他服务自动同步
- 命令传递：支持写值命令传递，实现 OPCUA 写值回传
- 事件通知：基于 Pub/Sub 的事件通知机制

## 🔍 诊断系统

### 诊断框架

系统提供统一的诊断框架，各服务通过 `DiagnosticProvider` 基类实现诊断数据收集：

- **Engine 诊断**：执行时间、实时比、节点统计、消息总线状态等
- **StorageService 诊断**：缓冲区状态、数据库大小、写入性能等
- **OPCUA Server 诊断**：节点数量、服务器状态、更新频率等

### 诊断数据访问

- **后端 API**：`GET /services/diagnostic/detail` 获取详细诊断信息
- **前端界面**：Web 界面实时展示服务状态和诊断数据
- **更新频率**：秒级更新（1秒）

## 📁 目录结构

```
data_factory_next/
├── components/                # 组件模块
│   ├── programs/             # 程序类型（算法/模型）
│   │   ├── base.py          # 基础程序类
│   │   ├── pid.py           # PID 控制算法
│   │   ├── sine_wave.py     # 正弦波生成器
│   │   ├── valve.py         # 阀门模型
│   │   └── ...
│   ├── functions/           # 数学函数库
│   │   └── math_functions.py
│   ├── message_bus/         # 消息总线
│   │   ├── bus.py           # 消息总线核心
│   │   ├── server.py        # 消息服务器
│   │   ├── client.py        # 消息客户端
│   │   └── registry.py      # 服务注册中心
│   ├── diagnostics/         # 诊断框架
│   │   └── base.py          # 诊断基类
│   └── export_templates/    # 导出模板
│       └── ...
├── controller/               # 核心引擎模块
│   ├── clock.py             # 统一时钟管理
│   ├── variable.py         # 变量存储与历史缓冲区
│   ├── expression.py       # 表达式执行引擎
│   ├── parser.py           # DSL 配置解析器
│   ├── factory.py          # 实例工厂
│   ├── engine.py           # 统一执行引擎
│   ├── realtime_publisher.py # Redis 实时数据发布
│   └── diagnostics/        # Engine 诊断
│       └── engine_diagnostics.py
├── datacenter/              # 数据中心模块
│   ├── storage_service.py   # DuckDB 历史数据存储
│   ├── opcua_server.py     # OPCUA Server
│   ├── diagnostics/        # 服务诊断
│   │   ├── storage_diagnostics.py
│   │   └── opcua_diagnostics.py
│   └── run_storage_service.py  # 存储服务启动脚本
├── services/                # 服务模块
│   ├── realtime_runner.py   # 实时运行器
│   ├── export_runner.py     # 导出运行器
│   └── service_manager.py  # 服务管理器
├── web_backend/            # Web 后端
│   ├── main.py             # FastAPI 应用
│   └── start_server.py     # 服务器启动脚本
├── web_frontend/           # Web 前端
│   ├── src/
│   │   ├── pages/          # 页面组件
│   │   │   ├── ServiceStatus.jsx  # 服务状态页面
│   │   │   └── ...
│   │   └── services/       # API 服务
│   └── ...
├── classical_config/       # 配置文件
│   ├── 典型水箱液位控制.yaml
│   └── ...
├── doc/                    # 项目文档
│   ├── 设计文档.md
│   ├── 用户手册.md
│   ├── 需求文档.md
│   └── interaction_record.md
└── tests/                  # 测试模块
    └── ...
```

## 🛠️ 技术栈

### 核心依赖

- **Python 3.10+**：主要编程语言
- **PyYAML**：YAML 配置文件解析
- **Pandas**：数据处理（用于数据导出）
- **NumPy**：数值计算支持

### 数据管理

- **Redis**：实时数据存储、Pub/Sub 通知、消息总线
- **DuckDB**：高性能时序数据存储和查询
- **asyncua**：OPCUA Server 实现

### Web 框架

- **FastAPI**：后端 Web 框架
- **React + Ant Design**：前端 UI 框架
- **Vite**：前端构建工具

### 设计特点

- **模块化架构**：清晰的模块划分，易于扩展
- **类型安全**：使用类型注解提高代码可读性
- **性能优化**：批量插入、连接池、按需存储等优化策略
- **统一诊断**：集中式诊断系统，便于监控和调试

## 🎯 应用场景

### 1. 工业大模型测试

- 生成符合工业场景的时间序列数据
- 支持复杂的数据关系模式（时间规律、滞后跟随、多项式关系等）
- 批量生成大规模测试数据集

### 2. PLC 仿真与联调

- 实时运行模式，模拟 PLC 周期执行
- OPCUA 集成，与外部系统无缝对接
- 支持物理模型和控制算法的仿真
- 支持写值回传，实现双向通信

### 3. 数据分析与验证

- 历史数据存储和查询
- 数据统计和分析
- 采样查询支持大数据集分析

### 4. 系统集成测试

- 实时数据推送（Redis）
- OPCUA 标准协议支持
- 消息总线实现服务间解耦
- 灵活的配置和扩展能力

## 📚 文档

- [设计文档](doc/设计文档.md) - 系统架构和设计理念
- [用户手册](doc/用户手册.md) - 使用指南和 API 参考
- [需求文档](doc/需求文档.md) - 功能需求说明
- [交互记录](doc/interaction_record.md) - 开发历程和设计决策

## 🔄 运行模式对比

| 特性 | GENERATOR 模式 | REALTIME 模式 |
|------|---------------|---------------|
| **执行速度** | 快速，不 sleep | 实时，按周期 sleep |
| **返回值** | `List[Dict]` | `Iterable[Dict]` (生成器) |
| **数据保留** | 保留所有数据 | 流式处理，不保留 |
| **适用场景** | 批量生成、测试、离线分析 | 实时运行、在线交互、系统集成 |
| **内存占用** | 高（所有数据在内存） | 低（只保留当前快照） |

## 📦 依赖安装

```bash
# 安装所有依赖
pip install -r requirements.txt

# 核心依赖
pip install pyyaml pandas numpy

# 数据管理依赖
pip install redis duckdb asyncua

# Web 框架依赖
pip install fastapi uvicorn
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**Data Factory Next** - 让工业数据生成和模拟更简单、更高效！

*Designed by @yuzechao*
