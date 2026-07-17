# 交互与变更记录

本文档按时间记录与导出/接口相关的重要交互与行为变更，便于追溯。

## 2025-03-26：导出对话框与多格式导出

### 行为摘要
- 数据模拟页「数据生成」改为 **Modal**：左侧模板名列表仅作预设；右侧可编辑导出格式（与 YAML 解耦）；请求携带 `export_format`。
- 支持导出 **csv / xlsx / xls**；Excel 默认 sheet 名「控制器」（请求体 `sheet_name` 可覆盖）。
- 未携带 `export_format` 的 `POST /export/run` 仍按原逻辑：读 `template_name` 对应 YAML，导出 CSV。

### 接口变更
- 新增 `GET /export/format-defaults/{template_name}`。
- `POST /export/run`：请求体增加可选 `export_format`（`header_rows`、`title_names`、`time_format`、`file_format`、`sheet_name`）；响应在 `csv` 时返回 `file_content`；`xlsx`/`xls` 时返回 `file_content_base64`、`mime_type`、`filename`。

### 依赖
- `doc/requirements.txt` 增加 `openpyxl`、`xlwt`。

## 2025-03-26：实时数据页显示 N/A 修复

### 原因
- `RealtimePublisher` 仅写 Redis V2 Hash，未再写 V1 键 `data_factory:current`，而 `GET /realtime/snapshot` 原从该键读 `params`，导致始终为空。
- 存在重复的 `/realtime/snapshot` 注册；前端也未解析嵌套 `snapshot` 字段。

### 修复
- 每次推送在 `_do_push` 中同步 `SET data_factory:current`（JSON 含 `params`）。
- 合并为单一 `GET /realtime/snapshot`：Redis 无有效 `params` 时回退 `RealtimeRunner.latest_snapshot()`。
- 前端 `getCurrentValue` 增加对 `snapshot.xxx` 的取值。

### 补充（仍无实时值）
- `GET /realtime/snapshot` 改为 **合并** Redis V2 Hash（`data_factory:v2:current`，按位号 field 合并，多引擎更全）+ V1 `params` + 内存 runner，**runner 覆盖同名字段**；避免只读 V1 被覆盖或某路径未写入。
- 前端轮询只要返回 JSON 对象即 `setSnapshotData`，不依赖 `status === 'ok'`。

## 2026-03-26：Redis HSET 兼容性修复

### 现象
- 日志持续报错：`wrong number of arguments for 'hset' command`（`realtime_publisher.py`），导致实时快照写入失败。

### 原因
- 当前运行环境下 Redis 客户端/服务对 `hset(name, mapping=...)` 参数形态不兼容。

### 修复
- 在 `RealtimePublisher._do_push` 中对 V2 Hash 写入增加兼容分支：
  - 先尝试 `hset(..., mapping=payload)`；
  - 失败时回退为逐条 `hset(name, field, value)`（pipeline 批量执行）。

## 2026-03-26：Storage/OPCUA“已注册但已停止”排查与修复

### 现象
- 服务诊断页显示：`storage_service` / `opcua_server` 为“已注册、已停止”。

### 日志结论
- `StorageService` 启动失败：`storage_service.duckdb` 文件被占用（Windows 文件锁）。
- `OPCUA Server` 启动失败：`18951` 端口占用（WinError 10048）。

### 根因
- `web_backend/main.py` 在**模块导入阶段**直接执行 `service_manager.start_all()`；
- 配合 `uvicorn reload`/文件变更重载，服务可能被重复启动，触发 DuckDB 文件锁与 OPCUA 端口冲突。

### 修复
- 将服务启动迁移到 `@app.on_event("startup")`，并用 `_services_started` 防重复执行；
- 在 `shutdown` 事件复位 `_services_started`；
- `web_backend/start_server.py` 默认 `reload=False`，减少开发环境重复启动副作用。
- `ServiceManager` 健康检查加入自愈：检测到 `StorageService` / `OPCUA Server` 未运行时自动尝试重启。
- `HistoryQuery` 增加 `read_only` 可配置；Web 同进程模式下设为 `read_only=False`，避免与 StorageService 的 DuckDB 连接配置冲突。

## 2026-03-26：Redis v1 下线（统一 v2）

### 调整范围
- `RealtimePublisher`：移除 `data_factory:current`（v1）镜像写入，仅保留 `data_factory:v2:current`（Hash）与 Pub/Sub 通知。
- `GET /realtime/snapshot`：移除 v1 读取与合并，仅保留 v2 + 内存 runner 回退。
- `OPCUA Server` Pub/Sub 分支：移除 v1 回退读取，统一读取 v2 hash。
- `ServiceManager`：删除未接入调用且依赖 v1 的 `_restore_state_from_redis` 遗留方法。

### 结果
- 实时链路统一为 v2，减少双格式维护成本。
- 前端实时页、Storage、OPCUA 主链路维持不变（均以 v2 为主）。

## 2026-03-26：彻底移除 history_config 旧链路

### 现象
- 更新 `engines_manifest.yaml` 并重启后，前端组态树仍只显示 `default`。

### 根因
- 引擎加载新 manifest 后，`ConfigServer.publish_config()` 在 `hset(mapping=...)` 上触发兼容性异常，导致启动中断。
- `GET /realtime/config/redis` 仍存在对 `data_factory:history_config` 的回退读取，旧残留数据会误导前端展示。

### 处理
- `services/config_server.py`：`publish_config()` 增加 `hset(mapping=...)` 失败时的逐字段 `hset` 回退，确保注册表能发布成功。
- `web_backend/main.py`：`/realtime/config/redis` 改为仅以 `data_factory:registry:tags` 构建组态树；移除 `history_config` 回退读取。
- `controller/realtime_publisher.py`：`push_config()` 移除写入 `data_factory:history_config` 的旧兼容逻辑，仅保留消息总线 `config_update` 事件。
- `datacenter/storage_service.py`：移除从 `data_factory:history_config` 拉取组态的旧路径，仅通过消息总线接收组态。

### 结果
- 组态来源统一为运行时注册表/消息总线，不再受旧 `history_config` 残留影响。

## 2026-03-26：新增 TAG 程序（统一可写位号）

### 需求
- 支持用 Program 统一承载“可写输入 + 输出透传”的位号建模，替代 VARIABLE 在写值场景下每周期被表达式覆盖的问题。

### 实现
- 新增 `components/programs/tag.py`，提供 `TAG` 程序：
  - `stored_attributes = ["in", "out"]`
  - `execute(in_value=None)` 默认每周期执行 `out = in`
  - 支持 `execute(in_value=other.out)` 进行信号连接
- 接入 `components/programs/__init__.py` 自动注册：`InstanceRegistry.register_algorithm("TAG", TAG)`。

### 说明
- 输入位号已统一改为 `in_value`，表达式与写值接口同名，移除关键字规避说明。

## 2026-03-26：UA 写值链路与前端写值语义对齐

### 问题
- OPCUA 写值命令在 `engine._handle_opcua_write_value` 中使用 `split(".", 1)` 拆分位号，
  对 `ns1.tag.in_value` 这类带命名空间的实例属性会错误拆分，导致写值无法准确命中目标实例参数。

### 修复
- 写值解析改为“前端同语义”：
  1. 先按 `VARIABLE` 全名匹配（支持 `namespace.variable`）；
  2. 否则按 `instance.attr` 解析，使用 `rsplit(".", 1)` 支持 `namespace.instance.attr`；
  3. 实例不存在时再回退为变量写值。

### 结果
- UA 客户端写值与前端 `patchInstanceParams/patchVariable` 路由判定一致，`TAG.in_value` 等实例属性可稳定写入。

## 2026-03-26：OPCUA 写值闭环修复（ns1.sin1.amplitude）

### 现象
- UA 客户端写 `ns1.sin1.amplitude=2` 后，读回或快照未稳定生效，出现被实时刷新值覆盖。

### 根因
- 当前 `asyncua` 版本下，`set_write_value` 回调不可可靠依赖；
- 改为 `set_attribute_value_setter` 后，若不区分来源，会把服务端内部 `write_value` 也当作外部写值转发，形成回写干扰。
- `engine._handle_opcua_write_value` 对 MessageBus 入参默认按 `message.payload` 读取，和 `server` 实际传入 `payload dict` 形态不兼容。

### 修复
- `datacenter/opcua_server.py`
  - 采用 `server.set_attribute_value_setter(...)` 统一拦截 UA 写值；
  - 增加内部写入保护集合 `self._internal_writes`，服务端内部刷新值不再转发；
  - 外部写值命中后，转发到 `engine.opcua_write_value`（与前端写值同通道）。
- `controller/engine.py`
  - `_handle_opcua_write_value` 兼容两种入参：`dict payload` 与 `Message` 对象。

### 自测结果
- 以 UA 客户端实际写入 `ns1.sin1.amplitude=2.0` 后：
  - `/realtime/snapshot` 连续轮询稳定为 `2.0`；
  - OPCUA 节点 `ns1.sin1.amplitude` 连续轮询稳定为 `2.0`；
  - 日志可见 `OPCUA external write captured: ns1.sin1.amplitude=2.0` 与 `OPCUA write instance param queued: ns1.sin1.amplitude = 2.0`。

## 2026-03-27：前端/OPCUA 同位号不一致与刷新跳变修复

### 现象
- 同一个位号在前端与 OPCUA 客户端读值不一致；
- UA 客户端写值后，前端未同步，或 UA 端出现新旧值跳变。

### 根因
- 多引擎场景中，`Engine` 消息服务统一使用了同名 `engine`，导致写值命令可能被错误引擎消费；
- `opcua_server` 节点创建里直接调用 `set_display_name`，在当前 asyncua 版本下可能不存在，导致节点创建异常与刷新不稳定。

### 修复
- `controller/engine.py`
  - 消息服务名从固定 `engine` 改为 `engine.<engine_id>`，确保命令按命名空间隔离。
- `datacenter/opcua_server.py`
  - 写值转发按位号前缀路由到 `engine.<namespace>`（不存在时回退 `engine`）；
  - `set_display_name` 增加 `hasattr` 兼容判断，避免节点创建异常。

### 验证
- `ns1.sin1.out`：
  - 前端快照连续变化；
  - OPCUA 客户端连续变化（同趋势，采样时刻不同允许微小差异）。
- `ns1.sin1.amplitude`：
  - UA 客户端写入 `2.0` 后读回 `2.0`；
  - 前端 `/realtime/snapshot` 连续轮询稳定为 `2.0`。

## 2026-03-27：导出模板 YAML 与前端导出弹窗字段对齐

### 需求
- 导出模板能力与前端“数据生成”弹窗字段存在偏差，需要统一为同一套字段模型。
- 前端每次打开导出弹窗时，默认值应从模板 YAML 动态加载。
- 后续新增默认模板时，应仅通过新增 YAML 文件实现。

### 实现
- `components/export_templates/template_manager.py`
  - 模板解析改为仅接受 `defaults` 对象：`header_rows/title_names/time_format/file_format/sheet_name`；
  - `ExportTemplate` 新增 `to_export_format_defaults()`，直接返回前端可用默认值；
  - 不再保留旧 YAML 字段解析路径（方案 A，一次性切换）。
- `web_backend/main.py`
  - `GET /export/format-defaults/{template_name}` 改为直接返回模板 `defaults`，不再后端拼接默认值。
- `components/export_templates/templates/*.yaml`
  - `prediction/pid_loop_tuning/ai_loop_tuning` 三个模板统一迁移到新结构。
- `web_frontend/src/pages/DataSimulation.jsx`
  - 移除模板名硬编码兜底 `moban_1`；
  - 导出前增加模板列表为空的保护校验。

### 结果
- 模板 YAML 与前端导出配置字段完全一致；
- 前端打开弹窗和切换模板均可按 YAML 动态加载默认值；
- 新增模板只需新增一个同结构 YAML 文件即可自动生效。

## 2026-03-27：MPC 模板导出失败修复

### 现象
- 选择 `mpc` 模板导出时，后端报错：
  `ExportTemplate.__init__() got an unexpected keyword argument 'time_column_name'`。

### 根因
- `services/export_runner.py` 在 `export_format` 路径仍按旧参数构造 `ExportTemplate`（`time_column_name/time_row2_description`），
  与新模板模型（`title_names/file_format/sheet_name`）不一致。

### 修复
- `services/export_runner.py`
  - 移除旧参数构造方式；
  - 改为使用新参数：`header_rows/title_names/time_format/file_format/sheet_name`；
  - `engine.export_snapshots(...)` 的 `sheet_name` 改为使用 `inline_template.sheet_name`，确保一致。

### 结果
- `mpc` 模板导出链路恢复，可按模板默认值或弹窗编辑值导出。

## 2026-03-27：默认关闭导出列名转大写

### 需求
- 当前导出时位号/参数列名会统一转大写，先默认注释掉该能力。

### 实现
- `components/export_templates/csv_exporter.py`
  - `_write_header(...)` 中取消按 `uppercase_column_names` 转换，直接使用原始列名。
- `components/export_templates/excel_exporter.py`
  - `_display_columns(...)` 中取消按 `uppercase_column_names` 转换，直接返回原始列名。

### 结果
- CSV / XLSX / XLS 导出列名均保持与运行时位号名一致（不再自动转大写）。
- 已保留注释说明，后续可快速恢复旧逻辑。

## 2026-03-30：PID 增加 MODE 参数

### 需求
- 为 `PID` 增加参数 `MODE`，默认 `1`；`execute` 中仅当 `MODE == 1` 时执行原有 PID 运算，否则本周期跳过（不更新 MV、积分与微分状态）。
- 同步更新文档页参数表（`params_table` / `param_descriptions`）。

### 实现
- `components/programs/pid.py`
  - `default_params`、`stored_attributes`、`param_descriptions`、`params_table`、类与模块 `doc` 增加 `MODE`；
  - `execute(..., MODE=None)` 可每周期覆盖；数值比较使用 `float(MODE)==1.0`。
- `doc/实现设计.md`：PID 示例代码片段同步。

### 结果
- 文档 API `/docs/program/pid` 展示的参数表格含 MODE；位号表含 MODE 说明。
