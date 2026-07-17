# Data Factory Next 设计文档

## 1. 架构概览
本系统采用分布式“生产者-消费者”模式，依托 Redis 作为高性能数据总线。

### 1.1 总体架构图 (逻辑)
```
[ Web Frontend (Admin) ]
          │
          ▼
[ Web Backend (FastAPI) ] <───> [ engines_manifest.yaml ]
          │
          ▼
[ Config Server (Registry) ] <─── [ Service Manager ]
          │                       │
          ▼                       ▼
[ Redis Data Bus ] <──────── [ Engine Clusters (Sim/Playback) ]
          │
          ▼
[ Storage Service ] [ OPCUA Server ]
```

## 2. 详细设计

### 2.0 配置服务器 (Config Server)
- **职责**：负责解析基础设施编排文件，维护全局位号注册表，并下发同步指令。
- **热重载流程**：
  1. 后端监听到重载请求，加载最新 YAML。
  2. 比对运行中引擎 ID 与目标配置。
  3. 通过 `ServiceManager` 差量启停引擎进程。
  4. 更新 `Redis Registry` 并发布 `reload` 消息通知订阅者。

### 2.1 引擎抽象 (Runtime Interface)
所有运行逻辑必须实现 `BaseRuntime` 接口：
- `step()`：驱动单个周期的逻辑执行。
- `get_metadata()`：声明该引擎负责的所有变量名和数据类型。

### 2.2 数据模型与路由
- **Redis Path**：`data_factory:v2:current` (Multiplexed Hash)。
- **Data Structure**: Hash 的 Key 为完整位号 (`tag`), Value 为 JSON 字符串 `{"value": ..., "timestamp": ..., "engine_id": "..."}`。
- **Global Registry**：`data_factory:registry:tags`，由 Config Server 在启动时构建并发布，供消费者建立位号索引。

### 2.3 下游聚合逻辑
- **Storage Service**：启动后台任务监听 `data_factory:engines:*:current` 的变化。采用批处理模式（Batch Insert）写入 DuckDB，表结构中包含 `engine_id` 字段以供区分。
- **OPCUA Server**：扫描 `Global Registry` 动态构建树状地址空间。收到写指令时，根据映射表将命令反向路由至对应引擎的 Command 频道。

### 2.4 时钟与同步策略
- **当前设计**：各引擎基于配置的 `cycle_time` 调用本地定时器驱动。
- **未来扩展 (软件 NTP)**：当部署在多台物理机器时，计划引入软件 NTP 算法，通过主节点分发基准节拍，从节点计算时钟漂移（Clock Drift）并动态微调休眠时间。

## 3. 技术栈
- **核心逻辑**：Python 3.10+
- **数据总线**：Redis (Streams & Hash)
- **历史存储**：DuckDB (分析型列表存储)
- **协议发布**：Asyncua (OPCUA)
- **前端展示**：React + Ant Design

## 4. Program 展示、DSL `display_args` 与导出过滤
- `BaseProgram`：`stored_attributes`、`param_descriptions`（子类必需）。默认展示列与 `plot_scale_ref` 由 DSL `display_args` 解析为 `ProgramItem.display_specs`；`UnifiedEngine.get_variable_meta()` / `get_display_variables()` / `get_plot_scales()` 基于组态生成元数据与前端的 `plot_scales`（**仅图表**使用 `ref`）。
- `CSVExporter` / `export_to_csv` / `run_export`：`selected_variables` 为 `None` 时使用 `get_display_variables()`；导出值为原始标量，不应用 `ref`。
