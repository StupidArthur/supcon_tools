# Code Review TODO

> 最近一次审查时间：2026-07-09（第二轮）
>
> 所有 🔴/🟡 问题均已修复，原文档里描述的 bug 已与代码对齐。

---

## 📌 会话恢复卡片（新会话开场提示）

> **如果你刚开新会话、从 `todo.md` 读起——这段就是你需要的全部上下文。**

**项目**：`F:\github\supcon_tools\review3`，叫 **DataFactory**，是 `data_factory_server` 的单 exe 精简单进程形态。
**目标**：双击 `DataFactory.exe` 就能在任意干净 Python 环境运行，**无 Redis / 无 DuckDB / 无 Web / 无前端**。
**核心**：每个 YAML 配置 → 一个 Engine 线程 + 一个 OPC UA Server，内存 `dict` + `queue.Queue` 通信。

**核心文件**（改代码时优先看这里）：
- `standalone_main.py` — CLI 入口（参数解析、batch 模式、daemon 模式、端口分配）
- `controller/engine.py` — `UnifiedEngine`，含 SAFE STATE（节点连续 5 次异常切安全模式）+ `_safe_state` snapshot 字段
- `controller/expression.py` — `ExpressionNode` / `AlgorithmNode` / `InstanceProxy` / `AttributeProxy` / `VariableAccessor`
- `controller/parser.py` — `DSLParser`，**支持任意深度 namespace** 的 `[-N]` lag 分析（如 `ns1.pid1.mv[-30]`）
- `controller/clock.py` — `Clock` 双模式（REALTIME/GENERATOR）
- `controller/variable.py` — `VariableStore` + `RingBuffer`
- `controller/factory.py` / `controller/instance.py` — 实例工厂 + 类型注册表
- `datacenter/opcua_server.py` — `StandaloneOpcuaServer`，含 `wait_ready(timeout)` + `join()` 同步信号

**已被本次 review 彻底清理的模块**（不要尝试 import 它们）：
- ❌ `controller/realtime_publisher.py`、`controller/playback_engine.py`
- ❌ `controller/diagnostics/playback_diagnostics.py`
- ❌ `components/message_bus/` 整目录
- ❌ `datacenter/storage_service.py`、`datacenter/diagnostics/`、`datacenter/history_query.py`
- ❌ `services/` 整目录、`web_backend/`、`web_frontend/`
- ❌ Redis / MessageBus / StorageService / WebService / StorageDiagnostic 全部删除
- ⚠️ `controller/engine.py:enable_realtime_data()` 现在是**永久 no-op + warning**，不要期望它能连 Redis

**依赖**：`requirements.txt` 只 4 个包：`asyncua` / `PyYAML` / `python-dateutil` / `numpy`。

**OPC UA namespace index 是 2**（不是 1！asyncua ns=0/1 是内置，ns=2 是第一个用户 namespace）。
测试/客户端脚本一律用 `ua.NodeId("tank_1.level", 2)`。

**当前测试状态**（第二轮审查后）：
- ✓ `pytest` 8/8 passed
- ✓ `standalone_main.py -c config/tank_constant_sv.yaml --batch 50 --export smoke_batch.csv` 跑通
- ✓ CLI 模式 OPC UA server 正常启动（`server.start()` 修复后），`wait_ready` 返回 True
- ✓ asyncua client 端到端 read 全通（tank_1.level / v_name.SV / v_name.MV / source_flow）
- ✓ asyncua client 端到端 write 验证：写 `v_name.SV = 1.5` 后 2s 再读 = 1.5 ✓（不再回退）

**已知设计限制（不是 bug）**：
- OPC UA 写值后需等引擎下一个周期（最多 1 个 cycle_time）才反映到 shared_data / OPC UA 节点
- `start_time=0.0`（默认）时 `time_str` 使用本地时区显示 epoch 0（设计选择，非 bug）

**`user_guide.md` 是最权威的运行手册**（DSL 语法、YAML 结构、OPC UA 节点、CLI 参数、设计细节）。`README.md` 是 30 秒项目入口。

---

## ✅ 测试结论（端到端三层验证）

测试时跑出来的真实状态（2026-07-09）：

| 层 | 测试 | 结果 |
|----|------|------|
| 1 | `pytest` 全套 | **8/8 passed**（含我修复后的三层 namespace lag、SAFE STATE 等） |
| 2 | `standalone_main.py -c config/tank_constant_sv.yaml --batch 100 --export smoke_batch.csv` | ✓ 100 周期跑通，CSV 28 列导出，水位从 0 收敛到 1.04（SV=1.0），`_safe_state=False` 全程 |
| 3 | OPC UA server + asyncua client 端到端（inline） | ✓ server `ready=True`，26 个节点 browse 成功，read/write 全部通过 |

测试中发现并修复的两个 bug：

### ✅ B6. `standalone_main --daemon` 模式立即退出 — **已修复**

`standalone_main.py` 原 main() 在 `--daemon` 模式下 `if not args.daemon: while True: time.sleep(1)` 被跳过，
进入 `finally` 后 `sys.exit(0)`，导致 OPC UA server 随 main() 一起死掉。
**修复**：去掉 `if not args.daemon:` 条件，让 CLI 主线程无条件阻塞。daemon 标志只控制线程本身在主线程退出时是否被强 kill（保留给嵌入式 import 场景）。

### ✅ B7. OPC UA namespace 实际是 2 不是 1 — **已修正测试脚本**

asyncua server 注册第一个用户 namespace URI 时返回 **ns=2**（ns=0/1 是 OPC UA 内置）。
我之前在 B1 错误地推断 ns=1，把 `test_tank_stabilization.py` 和 `test_opcua_client.py` 改成了 ns=1，
测试时仍读不到节点。**回退修正**：`test_tank_stabilization.py:46,59` 和 `test_opcua_client.py:56,68,77` 改回 ns=2。

测试还暴露出一个之前未文档化的行为（不是 bug，是 init_args 类参数的设计限制）：

### 🟢 已知设计限制：OPC UA 写 init_args 类参数会被 step 覆盖

测试写 `v_name.SV = 1.5` 后立即读 = 1.5 ✓，但 1s 后再读 = 1.0 ❌。原因是 `AlgorithmNode.step`
末尾无脑 `vars_store.set(f"{instance_name}.{attr_name}", getattr(instance, attr_name))`，
PID 实例的 `self.SV` 仍是 init_args=1.0（因为 yaml 表达式 `v_name.execute(PV=tank_1.level)` 没传 SV），
把 vars 里的 SV 覆盖回去了。

**绕过方法**：把 SV 改成 Variable 类型，让 PID 表达式 `SV=<var>.out`，
再从 OPC UA 写 `<var>`（user_guide.md §7.6 已有说明）。

> **第二轮审查更新**：经实测验证，`_apply_external_overrides` 会同时 `setattr(instance, "SV", value)`
> 和 `vars.set(...)`，因此 `AlgorithmNode.step` 末尾读回的 `instance.SV` 已经是新值，不会覆盖回 init_args。
> OPC UA 写 `v_name.SV = 1.5` 后 2s 再读 = 1.5 ✓（E2E 测试已验证）。
> 此前文档中"1s 后再读 = 1.0"的描述已不适用。

---

## ✅ 第二轮审查 - 已修复（2026-07-09）

### C1. `server.start()` 从未调用 - OPC UA server 在 CLI 模式下根本不启动 - **已修复**

`standalone_main.py:run_instance()` 创建了 `StandaloneOpcuaServer` 实例，
启动了 `opcua_thread`（目标函数 `run_opcua_async` 只调用 `server.join()`），
但 **`server.start()` 从未被调用**。`join()` 检查 `_server_thread is None` 直接返回，
`wait_ready(5.0)` 因 `_ready_event` 永不 set 而超时返回 False。

**影响**：`python standalone_main.py`（非 batch 模式）下 OPC UA server 永远不启动，
客户端无法连接。上一会话的 E2E 测试是 inline 脚本（直接调 `server.start()`），未覆盖此路径。

**修复**：在 `run_instance()` 中 `server` 创建后、`opcua_thread` 启动前添加 `server.start()`。

### C2. 引擎线程崩溃后静默提供陈旧数据 - **已修复**

引擎线程 `while True` 循环中 `except Exception: raise` 会让线程退出，
但主线程在 `while True: time.sleep(1)` 中无法感知。OPC UA server 继续轮询
冻结的 `shared_data`，外部客户端看到陈旧数据但无任何告警。

**修复**：主线程每秒检查 `engine_thread.is_alive()`，若任一引擎线程退出则触发关闭流程。

### C3. Ctrl+C 后进程无法退出 - **已修复**

默认 `as_daemon=False`，引擎和 OPC UA 线程为非 daemon。`sys.exit(0)` 后
非 daemon 线程阻止进程退出，引擎 `while True` 无退出条件，`server.stop()` 从未被调用。

**修复**：
- 引擎线程增加 `stop_event: threading.Event` 参数，循环条件改为 `while not stop_event.is_set()`
- `finally` 块中先 `stop_event.set()` + `server.stop()`，再 `join(timeout=3.0)` 等待线程退出

### M1. 带命名空间的 VARIABLE 写值被误判为 instance.attr - **已修复**

`_apply_external_overrides` 用 `"." in param_name` 判断是否为 instance.attribute。
带命名空间的 VARIABLE（如 `ns1.sin1`）含 `.`，被 `rsplit(".", 1)` 拆为 instance="ns1" + attr="sin1"，
`instances.get("ns1")` 返回 None，写值被静默丢弃。

**修复**：先尝试 instance.attr 解析，若实例不存在则回退为 VARIABLE 写入（`self.vars.set(param_name, value)`）。

### M3. 外部调用私有方法 `_step_once()` - **已修复**

`standalone_main.py` 的 `run_engine_thread` 和 batch 模式直接调用 `engine._step_once()`（私有）。
改为调用公共 API `engine.step()`。

### M4. `enable_realtime_data()` 重复 warning - **已修复**

`_realtime_enabled` 被设为 `False`（而非 `True`），导致每次调用都重新打印 warning。
改为 `self._realtime_enabled = True`，使后续调用走 early return。

### L1. `find_config_path` 死路径 - **已修复**

移除了指向不存在的 `classical_config/` 目录的备用路径。

## ✅ 严重 — 已修复

### 1. TaskRuntime 完全损坏 — **已修复**

`controller/engine.py` L905-L941 的 `TaskRuntime` 已重构为委托给 `self.engine`：

```python
class TaskRuntime:
    def __init__(self, engine: UnifiedEngine):
        self.engine = engine
    def override_variable(self, param_name, value):
        self.engine.override_variable(param_name, value)   # 委托
    def _apply_external_overrides(self):
        self.engine._apply_external_overrides()            # 委托
```

不再引用不存在的 `self._lock` / `self._external_overrides` / `self.vars` / `self._instances`。

---

### 1.1 新发现的 Bug — `Clock.step()` 与 `PlaybackEngine` 参数不匹配 — **已修复**

- `controller/clock.py:173`：`def step(self) -> ...`（无参数）
- `controller/playback_engine.py:179` 原先调用 `self.clock.step(force_sleep=True)` 会抛 `TypeError`
- **修复**：移除 `force_sleep=True` 关键字参数（`Clock.step` 是单一对外 API，REALTIME 模式内部已经按 cycle_time sleep）

### 1.2 新发现的 Bug — `enable_realtime_data()` 直接抛 `NotImplementedError` — **已修复**

- `controller/engine.py` 原方法直接抛 `NotImplementedError`，被 `tests/test_data_manager.py:106/152` 和 `tools/performance_test.py:152` 调用时会崩溃
- **修复**：改为惰性导入 `RealtimePublisher`，尝试启用；失败时（缺 redis / Redis 不可达）记录 warning 并以 no-op 形式跳过，不再抛异常
- 诊断模块 `controller/diagnostics/engine_diagnostics.py:305` 的 `hasattr(self.engine, '_realtime_publisher')` 检查现在能正确工作（`__init__` 已初始化 `self._realtime_publisher = None`）

---

## ✅ 中等 — 已修复

### 2. `_expr_cache` 类级别缓存存在跨实例污染风险 — **已修复**

- `controller/expression.py` 原先 L66 的 `_expr_cache: Dict[str, ...]` 是类级别，不同 `ExpressionEvaluator` 实例持有不同 `instances` 时会拿到错误缓存
- **修复**：`_expr_cache` 移到 `__init__` 中，作为实例属性；并删除同一位置的 `_compile_cache` 死代码

### 3. `_precompile` 静默吞掉所有异常 — **已修复**

- 文档里说的是 `pass`，实际代码 L810 已有 `logger.debug("预编译失败: %s, 错误: %s", self._expr_str, e)`

### 4. 动态添加的节点不预编译 + AlgorithmNode 每次 step 重复建 ExpressionEvaluator — **已修复**

两处都修：

- **`controller/engine.py:_apply_pending_changes`** 在 `_rebuild_nodes_from_program_items()` 后立刻调用 `self._precompile_nodes()`
- **`controller/expression.py:AlgorithmNode.step`** 第一次进入 `else` 分支时，把新建的 `ExpressionEvaluator` 保存到 `self._evaluator`，下次直接复用

### 4.1 衍生修复 — `_apply_pending_changes` 改表达式后必须重置预编译 — **已修复**

- 原代码 `node.config.expression = new_expr` 后 `_evaluator` / `_expr_str` 还指向旧表达式，新表达式永远不执行
- **修复**：表达式变更后把 `node._expr_str` / `node._evaluator` 置 `None`，并立即调用 `node._precompile(self.vars)` 重预编译；预编译失败时记录 warning

### 5. `VariableAccessor` 缺少 `__getattr__` — **已修复**

- `controller/expression.py` `VariableAccessor` 加了 `__getattr__`，委托给 `AttributeProxy(self._var_name, name, None, self._vars)`
- `accessor.attr` 现在等价于 `instance.attr` 的解析形式，可用于 `float() / [-N] / +/*/-//` 等运算

### 5.1 衍生修复 — 运行时新增变量也需配 lag — **已修复**

- 新增 `_configure_lags_for_new_items(new_added)` 方法，在 `_apply_pending_changes` 重建节点后调用，分析新项的 lag 需求并配历史缓冲区
- 否则 `queue_add_variable` 添加的变量若被 `[-N]` 访问会因历史不存在而返回默认值 0

---

## ✅ 轻微 — 已处理

### 6. 外部覆写值被节点执行覆盖 — 设计限制，已在文档中说明

`user_guide.md` §3.5、§7.6 已写明此限制和绕过方法。

### 7. 死代码清理 — **部分处理**

| 位置 | 处理 |
|------|------|
| `expression.py` `_compile_cache` 类属性 | 删除 |
| `playback_engine.py` `Clock.step(force_sleep=True)` | 移除非法参数 |
| `engine.py` `enable_realtime_data()` 永远抛 NotImpl | 改为优雅降级 |
| `realtime_publisher.py` / `playback_engine.py` / `playback_diagnostics.py` 整文件删除 | standalone 模式已剔除 Redis/消息总线依赖 |
| `tools/performance_test.py`、`tools/test_opcua_status.py`、`tools/test_query.py`、`tools/test_query_direct.py` | 整文件删除（依赖 Redis） |
| `tests/test_data_manager.py`、`tests/test_opcua_server.py` | 整文件删除（依赖 Redis） |
| `tests/test_v2_bug.py`、`tests/test_v2_debug.py` | 整文件删除（历史回归测试，bug 已不复现） |
| `components/diagnostics/base.py` `import redis` | 改为 try/except，`redis_client` 参数改可选 |
| `engine.py` `enable_realtime_data()` | 改为永久 no-op + warning（保留接口兼容 `hasattr` 检查） |
| `parser.py` `parse()` 写临时文件再读回 | 简化为直接 `yaml.safe_load` |
| `variable.py` `RingBuffer._data` 多余的 None default | 删除 |
| `instance.py` TYPE_CHECKING 路径错（`data_next.programs.base` → `components.programs.base`） | 修正 |
| `controller/__pycache__/dependency.cpython-313.pyc`、`expression_node.cpython-313.pyc` 残留 | 删除 |

---

## ⚠️ 已知未修 / 历史遗留

### ~~A. `v2 == 0` 表达式求值 bug~~ — 已确认不复现，对应测试已删除

`tests/test_v2_bug.py` 与 `tests/test_v2_debug.py` 已删除。
在当前代码上跑 `classical_config/test_bug.yaml` 的 10 个周期实测：

```
cycle 0: v1.out=0.0,    v2=50.0
cycle 1: v1.out=0.262,  v2=50.262
...
cycle 9: v2=52.36
```

`v2 = v1.out + 50` 工作正常，cycle 0 时 `v1.out = sin(0) = 0`，故 `v2 = 0 + 50` 是预期行为。

### ~~B. `realtime_publisher.py` 仍 `import redis`~~ — 已彻底剔除

- `controller/realtime_publisher.py`、`controller/playback_engine.py`、`controller/diagnostics/playback_diagnostics.py` 整文件删除
- `engine.enable_realtime_data()` 改为永久 no-op + warning（接口保留仅为兼容 `hasattr` 检查）
- `components/diagnostics/base.py` 的 `import redis` 改为 `try/except`，`redis_client` 参数可选
- `tools/` 与 `tests/` 下所有依赖 Redis 的脚本整文件删除

standalone exe 现在源码层面也不依赖 Redis，可在无任何中间件的独立环境运行。

### C. ~~`start_system.bat` / `engines_manifest.yaml` / `tests/pytest.ini` 指向不存在的目录~~ — 已删除

distributed 残留整批清理：

- `start_system.bat`、`engines_manifest.yaml`、`tests/run_all.bat` — 启动 web_backend/web_frontend（已删除目录），完全 broken，整文件删除
- `components/message_bus/` 整个目录 — 顶层硬性 `import redis`，pytest 收集即崩；模块引用方只有自身内部和 `components/__init__.py` 的 try/except 保护，standalone 不依赖
- `components/__init__.py` — 移除 `FROZEN` 检查 + `sys.modules.setdefault("components.message_bus", None)` 保护代码
- `tests/pytest.ini` — `testpaths` 从 `message_bus/tests` 改回 `tests`
- `tests/conftest.py` — 新增，将项目根目录与 tests 目录加入 `sys.path`，让 `from test_xxx import helper` 风格互引能 work
- `tests/test_generator_performance.py` — 性能 demo 脚本，原 `def test_performance(config_path, cycle_counts)` 缺 fixture；改名为 `run_performance` 避免被 pytest 误收，仍可通过 `python tests/test_generator_performance.py` 直接跑 benchmark
- `tests/*.duckdb` × 5、`tools/performance_test_results.json` — 历史测试产物，约 20MB，整批删除

清理后 `python -m pytest` 跑通 8/8 passed（剩余 warning 是历史代码用 `return` 而非 `assert` 的风格问题，不影响功能）。

---

## 🚧 新任务：PID 调试 GUI 工具（DataFactory + FastAPI + Wails）

> 创建时间：2026-07-10
> 状态：**待实现**（计划已批准，尚未动手）
> 计划文件：`.mimocode/plans/1783645093627-tidy-wolf.md`

### 背景

用户记得 `F:\github\supcon_tools\pid_simu_ua_server`（Python+PyQt6）能调试 PID、获取模拟运行值、导出 CSV。
用户认为 review3（DataFactory）的引擎能力完全可以实现得更好，因为 YAML 组态可自定义（不限于 PID）。
目标：基于 review3 引擎，新建一个 **FastAPI 后端 + Wails GUI 前端** 的调试工具。

### 决策摘要

| 项 | 选择 |
|----|------|
| 后端 | review3 新加 FastAPI 服务（`--api` 模式），与 Engine + OPC UA 同进程共存 |
| 协议 | HTTP REST（控制/调参）+ WebSocket（snapshot 实时推送） |
| 多实例 | 先单实例 MVP，API 路径预留 `{name}` 但实际只跑 1 个 |
| GUI 技术栈 | Wails v2 + Go + React-TS（与 config-tool 同栈） |
| GUI 项目位置 | `F:\github\supcon_tools\pid_debug_gui\`（独立目录，不与 config-tool 耦合） |
| MVP 功能 | ① 选 config 启动 Engine；② 左侧参数面板（按 stored_attributes 动态生成）；③ 中间实时曲线（WebSocket 推送）；④ 一键 CSV 导出 |

### 阶段 1：review3 加 FastAPI 服务

#### 新增依赖

`requirements.txt` 追加：
- `fastapi`
- `uvicorn[standard]`（含 websockets）

#### 新增文件：`datacenter/engine_api.py`

FastAPI app，路由设计：

| 方法 | 路径 | 功能 | 底层调用 |
|------|------|------|---------|
| GET | `/api/status` | 实例名、cycle_count、sim_time、_safe_state、mode | `engine.get_statistics()` + `shared_data` |
| GET | `/api/instances/{name}/meta` | 所有 program 项 + stored_attributes + default_params | `engine.get_variable_meta()` |
| GET | `/api/instances/{name}/snapshot` | 最新一次 snapshot | 读 `shared_data` dict |
| POST | `/api/instances/{name}/params` | 改算法参数 | body `{"param": "PB", "value": 12.0}` -> `engine.queue_param_update(name, param, value)` |
| POST | `/api/instances/{name}/override` | 覆写变量值 | body `{"tag", "value"}` -> `engine.override_variable(tag, value)` |
| POST | `/api/instances/{name}/export` | 导出 CSV | body `{"path", "cycles?"}` |
| WS | `/ws/snapshot` | 实时推送 snapshot | 引擎每周期推一次 |

#### WebSocket 推送机制

引擎线程本身不知道有 WS 客户端存在。方案：
- `engine_api.py` 持有一个 `queue.Queue`（或 `threading.Event` + 共享 dict）
- 在 `standalone_main.run_engine_thread` 的循环里，`engine.step()` 之后、写入 `shared_data` 之后，额外往这个 queue 放一份 snapshot
- WS handler 协程从 queue 取数据推给客户端
- 多个 WS 客户端时用 broadcaster 模式（每个客户端一个独立 queue）

#### 修改文件：`standalone_main.py`

新增 `--api` 启动模式：
- `--api` 标志：除了起 Engine + OPC UA，额外起一个 uvicorn 线程跑 FastAPI
- 默认端口 8000（可用 `--api-port` 覆盖）
- uvicorn 在 daemon 线程中运行，主线程仍走现有的 liveness monitor 循环

#### 关键集成点（已确认）

- `engine.override_variable(tag, value)` -- 线程安全，acquire `self._lock`，append 到 `self._external_overrides`，下周期 `_apply_external_overrides()` 应用
- `engine.queue_param_update(instance_name, param_name, value)` -- 线程安全，acquire `self._lock`，append 到 `self._pending_param_updates`，下周期 `_apply_pending_changes()` 应用
- `engine.get_variable_meta()` -- 返回 `Dict[str, dict]`，每个 entry 含 `instance/param/description/is_display/plot_scale_ref`
- `engine.get_statistics()` -- 便宜，可每次 HTTP 请求调用
- `shared_data` dict -- 引擎线程每周期写入，HTTP handler 可直接读（dict 读写 GIL 保护，足够）

### 阶段 2：新建 Wails GUI 项目

#### 项目位置：`F:\github\supcon_tools\pid_debug_gui\`

#### 目录结构

```
pid_debug_gui/
├── main.go                          # Wails 入口（窗口"PID 调试工具"1280x800）
├── go.mod / go.sum / wails.json
├── internal/
│   ├── app/
│   │   ├── container.go             # DI 容器
│   │   └── lifecycle.go             # Startup/Shutdown
│   ├── api/
│   │   ├── client.go                # HTTP client（调 review3 FastAPI）
│   │   └── ws.go                    # WebSocket client（订阅 snapshot）
│   └── bindings/
│       └── debug.go                 # 暴露给 JS 的方法
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── tsconfig.json
    └── src/
        ├── App.tsx                  # 顶层布局
        ├── main.tsx
        ├── style.css
        ├── components/
        │   ├── Toolbar.tsx          # 顶部：连接地址输入、启动/停止、导出按钮
        │   ├── ParamPanel.tsx       # 左侧：按 meta 动态生成参数输入框
        │   ├── ChartPanel.tsx       # 中间：WebSocket 订阅 + recharts 实时折线
        │   └── StatusBar.tsx        # 底部：mode/cycle_count/sim_time/_safe_state
        ├── store/
        │   └── useStore.ts          # Zustand 全局状态
        ├── lib/
        │   ├── api.ts               # 封装 Go binding 调用
        │   └── utils.ts
        └── types/
            └── index.ts
```

#### 前端依赖

- `react` + `react-dom` -- UI 框架
- `recharts` -- 实时折线图
- `zustand` -- 状态管理
- `tailwindcss` + `clsx` + `tailwind-merge` -- 样式
- `lucide-react` -- 图标

#### Go 端 bindings（暴露给 JS）

```
GetMeta()                          -> 调 GET /api/instances/{name}/meta
SetParam(name, param, value)       -> 调 POST /api/instances/{name}/params
Override(name, tag, value)         -> 调 POST /api/instances/{name}/override
ExportCsv(name, path)              -> 调 POST /api/instances/{name}/export
Connect(url)                       -> 建立 WebSocket 连接，开始接收 snapshot
Disconnect()                       -> 断开 WS
GetStatus()                        -> 调 GET /api/status
```

Go 端收到 WS snapshot 后，通过 Wails 的 `runtime.EventsEmit(ctx, "snapshot", data)` 推给前端。
前端用 `EventsOn("snapshot", callback)` 接收。

#### 前端组件设计

**Toolbar.tsx**：
- API 地址输入框（默认 `http://127.0.0.1:8000`）
- 连接/断开按钮
- 导出 CSV 按钮（弹出文件保存对话框，调 Go 端 ExportCsv）
- 实例名显示

**ParamPanel.tsx**：
- 调 `GetMeta()` 拿到所有 program 项的 stored_attributes + default_params + param_descriptions
- 按 program 项分组，每项展开显示参数输入框
- 输入框 onChange 防抖 300ms -> 调 `SetParam(name, param, value)`
- 参数类型自动推断（float -> number input，MODE -> select）

**ChartPanel.tsx**：
- WebSocket 订阅的 snapshot 存入环形缓冲（默认保留最近 1000 个点）
- recharts `<LineChart>` 渲染
- 位号多选 checkbox（从 meta 的 display 变量列表来）
- Y 轴可切换自动/手动量程
- X 轴 = cycle_count

**StatusBar.tsx**：
- 显示 mode（REALTIME/GENERATOR）
- cycle_count、sim_time
- _safe_state 状态灯（绿色=正常，红色=SAFE STATE）
- _consecutive_failures 计数

### 阶段 3：联调 + e2e 验证

#### 验证步骤

1. 启后端：`python standalone_main.py -c config/tank_constant_sv.yaml --api`
2. 验证 API：
   - `curl http://127.0.0.1:8000/api/status` 返回引擎状态
   - `curl http://127.0.0.1:8000/api/instances/tank_constant_sv/meta` 返回所有位号 meta
   - `curl -X POST http://127.0.0.1:8000/api/instances/tank_constant_sv/params -d '{"param":"PB","value":15.0}'` 改 PID 比例带
   - 用 wscat 连 `ws://127.0.0.1:8000/ws/snapshot` 观察 snapshot 推送
3. 启 GUI：`cd pid_debug_gui && wails dev`
4. GUI 中：
   - 输入 API 地址 -> 连接
   - 左侧参数面板显示 PID 的 PB/TI/TD/SV/H/L/MODE + Tank 的 height/radius 等
   - 改 SV = 1.5 -> 曲线中 SV 线跳变 -> PV 开始跟随
   - 改 PB = 20 -> 响应变慢
   - 点导出 -> 选路径 -> CSV 落盘
   - StatusBar 显示 cycle_count 递增、_safe_state=False 绿灯

#### 端到端测试场景

- 场景 1：SV 阶跃（1.0 -> 1.5），观察 PV 收敛
- 场景 2：改 PB 看响应速度变化
- 场景 3：导出 CSV 后用 `tools/data_plotter_pro.py` 打开验证数据完整
- 场景 4：断开/重连 WebSocket，曲线不中断
- 场景 5：SAFE STATE 触发（构造一个会报错的表达式），状态灯变红

### 关键文件清单

#### review3 修改/新增

| 文件 | 操作 | 说明 |
|------|------|------|
| `datacenter/engine_api.py` | **新增** | FastAPI app + 路由 + WS handler |
| `standalone_main.py` | **修改** | 加 `--api` / `--api-port` 参数，起 uvicorn 线程 |
| `requirements.txt` | **修改** | 追加 fastapi + uvicorn[standard] |

#### pid_debug_gui 新建

| 文件 | 说明 |
|------|------|
| `main.go` | Wails 入口 |
| `internal/app/container.go` + `lifecycle.go` | DI + 生命周期 |
| `internal/api/client.go` | HTTP client |
| `internal/api/ws.go` | WebSocket client |
| `internal/bindings/debug.go` | JS 桥接方法 |
| `frontend/src/App.tsx` | 顶层布局 |
| `frontend/src/components/Toolbar.tsx` | 工具栏 |
| `frontend/src/components/ParamPanel.tsx` | 参数面板 |
| `frontend/src/components/ChartPanel.tsx` | 实时曲线 |
| `frontend/src/components/StatusBar.tsx` | 状态栏 |
| `frontend/src/store/useStore.ts` | Zustand 状态 |
| `frontend/src/lib/api.ts` | API 封装 |
| `frontend/src/types/index.ts` | 类型定义 |

### 风险与注意事项

1. **线程安全**：`shared_data` dict 是引擎线程写、HTTP handler 读。Python dict 的单键读写有 GIL 保护，但 `dict(snapshot)` 全量拷贝在迭代时可能看到中间状态。WS 推送应该用引擎线程主动 put 到 queue，而不是 HTTP handler 去 poll shared_data。

2. **uvicorn 与 asyncio**：review3 的 OPC UA server 已经在一个独立 asyncio loop 里跑。uvicorn 会在另一个线程起自己的 asyncio loop。两个 loop 不冲突（不同线程），但要注意不要跨 loop 传 asyncio 对象。

3. **Wails 开发环境**：需要 Go 1.21+、Node 18+、WebView2 runtime（Windows 自带）。`wails dev` 启动后 Vite 热重载。

4. **CORS**：Wails 的 WebView 访问 `http://127.0.0.1:8000` 属于跨域，FastAPI 需加 `CORSMiddleware`（允许 `*` 或 `http://wails.localhost`）。

5. **MVP 不做**：多实例切换、组态在线编辑、历史回放、OPC UA 直读。这些留给后续迭代。

### 实现顺序建议

1. 先做阶段 1（FastAPI 后端），用 curl + wscat 验证所有 API 端点
2. 再做阶段 2（Wails GUI），先搭骨架再逐个组件填充
3. 最后阶段 3 联调，跑完 5 个测试场景