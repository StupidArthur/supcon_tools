# 多 Engine 运行与数据总线架构改造方案

## 1. 核心设计思想：数据驱动与生产者/消费者解耦
当前的架构正从“单体引擎”演进为“分布式数据平面”。核心逻辑是：**后台服务（Storage、OPCUA）不关心数据来源，只关心数据的流转和内容。**

### 核心解耦原则：
- **Engine (生产者)**：负责产生数据。无论是实时计算（Simulation）还是历史回放（Playback），只需将数据投递到统一总线。
- **Storage/OPCUA (消费者)**：负责消费数据。通过订阅总线数据流，实现自动存储、转换和协议转发，无需感知 Engine 的数量和类型。
- **Config Master (管家)**：负责全局组态的合并与分发。

---

## 2. 详细改造方案

### A. 统一数据平面 (Unified Data Plane)
- **Redis 传输层**：
  - 各 Engine 将 Snapshot 写入 `data_factory:bus:{engine_id}` 或共用的 Redis 流。
  - 维持一个全局最新的 Hash 表 `data_factory:global:current`，由各 Engine 增量更新。
- **时钟同步 (Clock Sync)**：
  - 引入 **Master Clock** 机制。由主服务发送时钟滴答（Tick），各 Engine 监听到 Tick 后执行一步（Step）并输出数据，确保分布式环境下的时间轴对齐。

### B. 多 Engine 实例支持
- **Simulation Engine (模拟引擎)**：沿用现有的 `UnifiedEngine`，支持动态加载算法和模型位号。
- **Playback Engine (回放引擎 - 新增)**：
  - **功能**：加载离线 Excel/CSV 数据集。
  - **逻辑**：监听 Master Clock 的时间偏移，定位数据集中对应的行，将其包装为标准快照格式外发。
  - **优势**：在 OPCUA 客户端看来，回放的数据和实时计算的数据在表现形式上完全一致。

### C. 组态聚合与管理 (Centralized Config)
- **全局组态映射 (Global Registry)**：
  - `ServiceManager` 负责解析包含多个 Engine 定义的“超级 DSL”。
  - 在 Redis 中维护 `data_factory:meta:global_registry`，包含所有活跃位号名及其所属 Engine 信息。
- **Storage Service 改造**：
  - 启动后读取 `Global Registry` 确定存储白名单。
  - 监听总线数据，收到任何位号的更新即触发 DuckDB 批量写入。
- **OPCUA Server 改造**：
  - 基于全局组态一次性构建地址空间树。
  - 写值请求通过位号名反查 Registry，路由到对应的 Engine 消息队列。

---

## 3. 模块具体设计方案

### 3.1 Playback Engine (回放引擎 - 新增)
该引擎用于将 Excel/CSV 等静态数据集“模拟”成实时数据流。

*   **内部结构**：
    *   `DataRegistry`: 封装 `pandas`，负责文件预加载及数据清理（处理缺失值、类型转换）。
    *   `TimeMapper`: 将 `Master Clock` 的仿真秒数映射到数据集的索引（支持最近邻匹配或线性插值）。
*   **主体逻辑**：
    ```python
    while running:
        current_sim_time = wait_for_tick() # 等待 Master Clock 步进
        row = data_registry.get_row_by_time(current_sim_time)
        snapshot = wrap_as_snapshot(row, current_sim_time)
        publisher.push_snapshot(snapshot)
    ```
*   **关键配置**：需要定义 `time_column`（时间参考列）和 `column_mapping`（Excel 列名对位号名的映射）。

### 3.2 统一总线与 RealtimePublisher (改动)
从“单向推送”改为“多源并发推送”。

*   **Redis Key 模式**：
    *   `data_factory:bus:{engine_id}`: 每个引擎的私有实时输出频道。
    *   `data_factory:global:current`: 共享 Hash，键为 `tag_name`，值为实时快照。
*   **发布策略**：
    *   支持**增量发布**：引擎仅发布在本周期内发生变化的位号，减少 Redis 带宽压力。
    *   **Metadata**：快照中必须包含 `engine_id` 和 `source_type` (sim/playback)。

### 3.3 Storage Service (改动)
从“单一订阅”改为“多源收割”。

*   **数据接入层**：
    *   使用 `Redis Stream` 或监听 `data_factory:bus:*`。
    *   维护一个本地的 `Tag Cache`，用于快速过滤不需要存储的位号。
*   **存储逻辑改动**：
    *   `DuckDB` 表结构增加 `engine_id` (String) 和 `batch_id` (String) 字段。
    *   **性能优化**：由于多引擎增加了并发吞吐，必须强制启用 `executemany` 批量写入。

### 3.4 OPCUA Server (改动)
从“单机镜像”改为“分布式网关”。

*   **地址空间生成**：启动时扫描 `data_factory:meta:global_registry`。
*   **读操作**：从 `data_factory:global:current` 直接获取值，对外部请求响应。
*   **写操作 (Reverse Route)**：
    *   收到远程写值指令时，根据 `Global Registry` 找到该位号对应的 `engine_id`。
    *   向 `data_factory:engines:{engine_id}:cmd` 频道发布指令。

### 3.5 Master Clock (主时钟 - 新增/提炼)
确保所有引擎步调一致，避免时间漂移。

*   **实现方式**：在 `ServiceManager` 中启动一个高精度的定时任务。
*   **分发机制**：通过 Redis PubSub 广播 `data_factory:clock:tick` 消息，内容包含当前 `sim_time` 和 `cycle_count`。
*   **引擎响应**：各引擎订阅该频道，收到 Tick 后才执行 `_step_once()`。

---

## 4. 实施路径 (TODO List)

### 第一阶段：基础设施升级
- [ ] 扩展 `RealtimePublisher` 支持多实例前缀，并优化 Redis 写入策略。
- [ ] 在 `ServiceManager` 中引入 `EngineRegistry` 逻辑，管理多个进程/实例。
- [ ] 提取现有的 `Clock` 逻辑为可广播的 `MasterClock` 模块。

### 第二阶段：回放引擎开发
- [ ] 创建 `controller/playback_engine.py` 基类，集成 `pandas` 读取逻辑。
- [ ] 实现位号映射配置解析与时间偏移匹配算法。

### 第三阶段：服务聚合适配
- [ ] 升级 `StorageService`，使其支持订阅通配符频道的数据流。
- [ ] 在 `DuckDB` 表结构中完成字段扩展。
- [ ] 优化 OPCUA Server 的指令路由机制。

### 第四阶段：Web 端与管控
- [ ] 增强 Web 后端 API，支持列出、启动、停止特定引擎。
- [ ] 在前端 `ServiceStatus` 页面增加各引擎运行频率的实时监控视图。

---

> **设计结语**：通过这种设计，系统不仅实现了多引擎的并发运行，更构建了一套标准的“工业数据中台”架构：引擎即插件，总线即核心。
