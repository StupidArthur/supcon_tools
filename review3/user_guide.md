# Data Factory Standalone (review3) 用户手册

> data_factory_server 的单 exe 打包版：不要 Redis、不要 Web UI、不要 DuckDB。一个 `DataFactory.exe` 起引擎 + OPC UA Server，全靠内存 dict + queue 通信。
>
> **当前版本**：v1.20.0（`DataFactoryToolV1`）
>
> designed by yzc

---

## 1. 这是什么

review3 是 `data_factory_server` 的精简单 exe 形态。区别：

| 维度 | data_factory_server | review3 |
| ---- | ---- | ---- |
| 打包 | Python 源码（pip 安装依赖） | PyInstaller 单 exe `DataFactory.exe` |
| 数据总线 | Redis | 内存 `dict` + `queue.Queue` |
| 历史存储 | DuckDB | 无 |
| Web UI | Vite + React + AntD | 无 |
| 消息总线 | Redis Pub/Sub + ServiceRegistry | `queue.Queue` |
| OPCUA Server | 订阅 Redis + 消息总线 | 直接读内存 dict |
| 客户端写值回传 | Redis 消息总线 → Engine | `cmd_queue` → `engine.override_variable` |
| 目标 | 多引擎编排、Web 管理、长时历史 | 现场快速部署、单实例或少量实例、无依赖运行 |

> 源码层面两边的 `controller/`、`components/programs/`、`datacenter/opcua_server.py` 等核心模块几乎一致；review3 主要差异是把所有"Redis 驱动的部分"换成了内存版本（`StandaloneOpcuaServer`）。

---

## 2. 使用入门

### 2.1 最简单的用法

把 `DataFactory.exe` 和 `config/` 目录放在同一文件夹下，双击 exe，或在 cmd 里：

```cmd
DataFactory.exe
```

默认行为：

- 扫描 `config/` 下所有 `.yaml` / `.yml` 文件
- 每个文件起一个 Engine 线程 + 一个 OPC UA Server
- 端口从 `18951` 起递增（第一个 config 用 18951，第二个 18952，依此类推）
- 每个 Engine 都是 REALTIME 模式，按各自 YAML 的 `cycle_time` sleep

`config/tank_constant_sv.yaml` 是自带的示例，会在 18951 起一个 OPC UA Server。

### 2.2 命令行参数

```
DataFactory.exe [--config <yaml>] [--config-dir <dir>]
                [--name <name>] [--port <port>]
                [--batch N --export <out.csv>]
                [--daemon]
```

| 参数 | 说明 |
| ---- | ---- |
| `-c / --config <yaml>` | 单 YAML 模式：不扫描目录，只跑这一个 YAML |
| `-n / --name <name>` | 实例名（默认 `default`，影响日志前缀和 server URL 后缀） |
| `--port <port>` | 单实例模式指定端口（默认 18951）；自动发现模式作为基准端口递增 |
| `--config-dir <dir>` | 扫描目录（默认 `config`） |
| `--batch N` | 批处理模式：在 GENERATOR 模式下跑 N 个周期并退出 |
| `--export <out.csv>` | 批处理模式下的 CSV 输出路径（默认 `output.csv`） |
| `--daemon` | 把所有线程设为 daemon（主进程可立即退出；生产慎用） |

参数查找顺序：

- 指定了 `--config` → 单 YAML 模式（如果同时给了 `--batch`，跑批处理）
- 否则 → 扫描 `--config-dir`，逐个起实例（若有 `--batch` 则强制要求 `--config`）

### 2.3 一个具体的案例

把 demo 跑起来看：

```cmd
DataFactory.exe --config config\tank_constant_sv.yaml
```

输出大致：

```
Using config: config\tank_constant_sv.yaml
[Main:default] Engine thread started
[Engine:default] Started with config: config\tank_constant_sv.yaml
[Engine:default] Cycle time: 0.5s, Mode: ClockMode.REALTIME
[Main:default] OPCUA thread started
[OPCUA:default] Starting server at opc.tcp://0.0.0.0:18951
[OPCUA:default] Update cycle: 0.1s
[OPCUA:default] Server started, press Ctrl+C to stop
```

18951 起监听；用任意 OPC UA 客户端连 `opc.tcp://127.0.0.1:18951` 即可看到节点。

### 2.4 停止

按 `Ctrl + C` 中断（如果是 `--daemon`，主进程会立即退出，引擎和 OPC UA 也跟着退）。

---

## 3. 功能介绍

### 3.1 总述 — 进程内的架构

review3 没有分布式组件，所有东西跑在同一个进程：

```
DataFactory.exe
 ├── main 线程
 │   ├── 读 CLI 参数
 │   ├── 扫描 config/ 或加载 -c 指定的 YAML
 │   └── 为每个实例起两个线程：
 │
 ├── Engine 线程（每个实例一条）
 │   ├── DSLParser.parse_file
 │   ├── UnifiedEngine.from_program_config
 │   ├── clock.start()
 │   └── 死循环：
 │        a. 清空 cmd_queue → engine.override_variable
 │        b. engine._step_once（按 cycle_time sleep）
 │        c. 写共享内存 dict（位号全名 → 当前值）
 │
 └── OPCUA 线程（每个实例一条，独立 asyncio 事件循环）
     ├── StandaloneOpcuaServer
     │   ├── 100ms 轮询 shared_data
     │   └── 客户端写入 → cmd_queue.put
     └── asyncua Server，端口递增
```

线程间通过两个对象通信：

- `shared_data: Dict[str, float]` — 引擎写入，OPC UA 读取
- `cmd_queue: queue.Queue` — OPC UA 写入，引擎读取

每个实例有**独立的** `shared_data` 和 `cmd_queue`，实例之间不串扰。

### 3.2 支持的操作系统

- **Windows** 10 / 11（64 位，主要验证平台）
- **Linux**：理论上 PyInstaller 产物也能跑，但本手册未在 Linux 上验证

打包产物是单文件，目标机不需要装 Python。

### 3.3 DSL 配置

跟 data_factory_server 是**同一套**，详见 review3 的 `controller/parser.py` 与 data_factory_server 完全等价。最简示例 `config/tank_constant_sv.yaml`：

```yaml
clock:
  mode: REALTIME
  cycle_time: 0.5

program:
  - name: source_flow
    type: VARIABLE
    expression: source_flow = 0.18
    display_args: []
  - name: valve_1
    type: VALVE
    init_args:
      full_travel_time: 10
    display_args: []
    expression: valve_1.execute(target_opening=v_name.MV, inlet_flow=source_flow)
  - name: tank_1
    type: CYLINDRICAL_TANK
    init_args: {}
    display_args: []
    expression: tank_1.execute(inlet_flow=valve_1.outlet_flow)
  - name: v_name
    type: PID
    init_args:
      PB: 12
      TI: 30
      TD: 0.15
      SV: 1.0
    display_args: ["MV[100]", "PV[2]", "SV[2]", "MODE"]
    expression: v_name.execute(PV=tank_1.level)
```

支持的 program 类型与 data_factory_server 一致：`PID / SINE_WAVE / TRIANGLE_WAVE / SQUARE_WAVE / LIST_WAVE / RANDOM / VALVE / CYLINDRICAL_TANK / Variable / TAG`。详见 data_factory_server 手册第 3.4 / 4.1 节。

> 与 data_factory_server demo 的细微差异：review3 这份 demo 没在表达式里传 `SV=sin1.out`，而是把 SV 设成 `init_args` 里的常量 1.0；改 SV 用 OPC UA 客户端直接写 `v_name.SV`（详见下文 3.5 注意事项）。

### 3.4 OPC UA 暴露

- **默认端点**：`opc.tcp://0.0.0.0:18951`（单 YAML 模式）；自动发现模式从 18951 起每个实例递增
- **命名空间**：`http://data_factory.opcua`（通常 `ns=2`，asyncua 自动分配）
- **服务器名**：`Data Factory OPCUA Server`
- **根容器**：`Objects/DataFactory`
- **NodeId**：`ns=2;s=<param_name>`（位号全名）
- **更新周期**：100ms 轮询共享内存
- **写值**：默认开启；通过 `cmd_queue` 推回 Engine

`test_opcua_client.py` 里直接用了 `ua.NodeId("sin1.out", 2)` 这种 `namespace_idx=2` 的写法，验证了命名空间索引。

```
Objects/
  └── DataFactory/
       ├── source_flow
       ├── valve_1.current_opening
       ├── valve_1.outlet_flow
       ├── tank_1.level
       ├── v_name.MV
       ├── v_name.PV
       └── v_name.SV
```

### 3.5 客户端写值回传

OPC UA 客户端写入任意可写节点后：

1. `StandaloneOpcuaServer._bind_write_setter` 捕获写事件
2. 把 `{"tag": param_name, "value": python_value}` 放进 `cmd_queue`
3. Engine 线程下一轮开始先清空 `cmd_queue`，逐条调用 `engine.override_variable(tag, value)`
4. `override_variable` 进入参数更新队列，**周期空闲时**应用

> **坑**（详见 todo.md 第 6 条）：PID 的 `PV / SV / MV` 等每周期被 `execute(PV=..., SV=...)` 重算覆盖的属性，外部覆写在下一周期会被覆盖。`test_tank_stabilization.py` 的方法是把 `SV` 写到 PID 实例属性，并通过 init_args 保留；想从外部真正改变 SV 需要把 SV 改用 `Variable` 实现，让 PID 表达式 `SV=<var>.out`。本 demo（`tank_constant_sv.yaml`）由于表达式里没传 `SV=`，外部写 `v_name.SV` 是有效的。

### 3.6 批处理 / 一次性导出

不需要起 OPC UA Server，只想跑一段时间数据落 CSV：

```cmd
DataFactory.exe -c config\tank_constant_sv.yaml --batch 1000 --export tank_1000.csv
```

行为：

- 强制切到 `ClockMode.GENERATOR`（不 sleep）
- 跑 1000 个周期
- 写到 `tank_1000.csv`，列名是 `set(snapshot.keys())` 排序后去掉元数据（`cycle_count / need_sample / time_str / sim_time / exec_ratio`）
- 每 100 周期在 stdout 打一次进度
- 跑完即退出

> `--batch` 必须搭配 `-c / --config`（一次只能跑一份 YAML）。

### 3.7 多实例的支持

把多个 YAML 放进 `config/`：

```cmd
DataFactory.exe --config-dir config
```

自动发现模式下，文件名（不含扩展名）作为实例名，端口从 `--port`（默认 18951）递增：

- `tank_constant_sv.yaml` → 实例 `tank_constant_sv` → 端口 18951
- `mypid.yaml` → 实例 `mypid` → 端口 18952
- ...

各实例的 `shared_data` 与 `cmd_queue` 相互独立，所以不会有跨实例干扰。

### 3.8 后台运行

```cmd
DataFactory.exe --config config\tank_constant_sv.yaml --daemon
```

主进程会立即返回，引擎和 OPC UA 都以 daemon 线程继续运行，直到用户注销或系统关机。

> 一般生产场景用 Windows 服务 / `nssm` / `pm2` 等托管工具更稳。

---

## 4. 准备输入：YAML DSL

与 data_factory_server 完全一致。详细字段说明、表达式语法、`display_args` 行为、`[-N]` lag 语法都看 `data_factory_server/user_guide.md` 第 4 节。

最短可用的 YAML：

```yaml
clock:
  cycle_time: 0.5

program:
  - name: sin1
    type: SINE_WAVE
    init_args: { amplitude: 1.0, period: 200, phase: 0.0, offset: 1.0 }
    expression: sin1.execute()
  - name: out
    type: VARIABLE
    expression: out = sin1.out
```

复制保存为 `config/simple.yaml`，然后：

```cmd
DataFactory.exe -c config\simple.yaml
```

18951 端口上就能看到 `sin1.out` 跟 `out` 两个节点。

---

## 5. OPC UA 客户端连接

最直接的方式：用 `asyncua` 客户端（Python）或 UAExpert、Prosys OPC UA Browser 等任意支持 OPC UA 的客户端。

### 5.1 用 asyncua 连接（Python）

```python
import asyncio
from asyncua import Client, ua

async def main():
    async with Client("opc.tcp://127.0.0.1:18951") as client:
        # 浏览 DataFactory 文件夹
        root = client.get_root_node()
        df = await root.get_child(["0:Objects", "DataFactory"])
        children = await df.get_children()
        for c in children:
            name = await c.read_browse_name()
            val = await c.read_value()
            print(f"{name.Name} = {val}")

        # 改 SV
        sv_node = client.get_node(ua.NodeId("v_name.SV", 2))
        await sv_node.write_value(ua.DataValue(ua.Variant(1.5, ua.VariantType.Double)))

        # 订阅
        tank_node = client.get_node(ua.NodeId("tank_1.level", 2))
        val = await tank_node.read_value()
        print(f"tank_1.level = {val}")

asyncio.run(main())
```

`ua.NodeId(name, 2)` 中的 `2` 是命名空间索引（`asyncua.register_namespace` 后通常是 2）。

### 5.2 用 UAExpert（GUI）

1. 打开 UAExpert
2. `+ Server` → `Custom Discovery` → 填 `opc.tcp://127.0.0.1:18951`
3. 双击出现的 server，OK
4. 在 Address Space 里展开 `Objects / DataFactory`，就能看到所有位号
5. 把节点拖到中间的 Data Access View 即可实时刷新；右键节点 → `Write Value` 可写

---

## 6. 验证脚本

仓库自带两个集成测试脚本，用来快速验证 review3 的"启动 → 客户端连 → 改值 → 看曲线"流程。

### 6.1 `test_opcua_client.py`

作用：连接 OPC UA Server，列出所有节点，演示读/写。

```cmd
# 先启动 DataFactory.exe
DataFactory.exe -c config\tank_constant_sv.yaml

# 另开一个终端
pip install asyncua
python test_opcua_client.py
```

输出会包含 `sin1.out / tank_1.level / v_name.MV / v_name.PV` 等节点的当前值，演示写 `valve_1.target_opening`，然后连续读 5 次 `tank_1.level`。

### 6.2 `test_tank_stabilization.py`

作用：完整的水箱控制回路验证。先连 60 秒记录初始状态，然后把 `v_name.SV` 抬高 0.5，再连 60 秒记录响应。所有数据落到 `tank_test_results.csv`。

```cmd
# 先启动 DataFactory.exe
DataFactory.exe -c config\tank_constant_sv.yaml

# 另开终端
python test_tank_stabilization.py
```

预期：

- PV（`tank_1.level`）初始在 SV 附近振荡
- 改 SV 后 PV 经过一段过渡过程收敛到新 SV
- 输出 CSV 包含两列 `phase=initial` 和 `phase=post_change`，可用 Excel / pandas 绘图

> 这两个脚本是 demo YAML 是否正常的"探针"。脚本和 `DataFactory.exe` 的 OPC UA 端口都要对齐（默认都是 18951）；想换端口就改脚本里的 `OPCUA_URL` 常量。

---

## 7. 已知 bug 与限制

> 最近一次审查：2026-07-09。本节列出的 🔴/🟡 问题均已修复；剩余 🟢 项是已知设计限制或未深挖的边缘 bug。

### 7.1 ✅ 已修复：TaskRuntime 完全损坏

`controller/engine.py` L905-L941 的 `TaskRuntime` 已重构为委托给 `self.engine`，方法不再引用不存在的属性。

### 7.1.1 ✅ 已修复（新发现）：`Clock.step()` 与 `PlaybackEngine` 参数不匹配

`controller/clock.py:173` 的 `step()` 是无参 API。原先 `controller/playback_engine.py:179` 调用 `self.clock.step(force_sleep=True)` 会抛 `TypeError`。已移除非法关键字参数。

### 7.1.2 ✅ 已修复（新发现）：`enable_realtime_data()` 抛 `NotImplementedError` → 现已彻底禁用

原先直接抛异常。中间一度改为惰性导入 `RealtimePublisher` + Redis 不可用时优雅降级。
进一步清理时**整文件删除**了 `controller/realtime_publisher.py`、`controller/playback_engine.py`、
`controller/diagnostics/playback_diagnostics.py`，并把 `enable_realtime_data()` 改为永久 no-op + warning。

调用后不再尝试连接任何外部中间件，只记录 warning（`hasattr(self, '_realtime_publisher')` 仍返回 False，
诊断模块的检查不受影响）。如需让外部系统消费引擎数据，请使用 OPCUA Server（`standalone_main.py` 默认会自动启动）。

### 7.2 ✅ 已修复：`_expr_cache` 类级别缓存跨实例污染

`controller/expression.py` 的 `_expr_cache` 已从类级别迁到实例级别（不同 evaluator 的 `instances` 字典不再互相污染）。同时删除了同一位置的 `_compile_cache` 死代码。

### 7.3 ✅ 已修复：`_precompile` 静默吞异常

`controller/expression.py:810` 已有 `logger.debug("预编译失败: %s, 错误: %s", self._expr_str, e)`。

### 7.4 ✅ 已修复：动态加的节点不预编译 + AlgorithmNode 每次重建 evaluator

- `_rebuild_nodes_from_program_items()` 后 `_apply_pending_changes` 立刻调用 `self._precompile_nodes()`
- `AlgorithmNode.step()` 第一次进入 `else` 分支时把新建的 `ExpressionEvaluator` 保存到 `self._evaluator`，下次直接复用

### 7.4.1 ✅ 已修复（衍生）：`_apply_pending_changes` 改表达式后必须重置预编译

原先 `node.config.expression = new_expr` 改完 `_evaluator` / `_expr_str` 还指向旧表达式。现在会立即 `node._expr_str = None; node._evaluator = None; node._precompile(self.vars)`。

### 7.5 ✅ 已修复：VariableAccessor 缺 `__getattr__`

`controller/expression.py` 的 `VariableAccessor` 已添加 `__getattr__`，委托给 `AttributeProxy(self._var_name, name, None, self._vars)`。`accessor.attr` 现在等价于实例属性的解析形式。

### 7.5.1 ✅ 已修复（衍生）：运行时新增变量也需配 lag

新增 `_configure_lags_for_new_items(new_added)` 方法，在 `_apply_pending_changes` 重建节点后调用，避免新增变量被 `[-N]` 访问时因历史不存在而返回 0。

### 7.6 🟢 已知设计限制：外部覆写被节点执行覆盖

PID 的 `PV / SV / MV` 每个周期被 `execute(PV=..., SV=...)` 重算覆盖，外部写只对 `init_args` 类参数（`PB / TI / TD / MODE` 等）能持久。

**绕过方法**：把 SV 写成 `Variable`，让 PID 表达式 `SV=<var>.out`，再从 OPC UA 写 `<var>` 即可。

### 7.7 ✅ 已剔除 Redis 依赖

- `controller/realtime_publisher.py`、`controller/playback_engine.py`、`controller/diagnostics/playback_diagnostics.py` 整文件删除
- `engine.enable_realtime_data()` 改为永久 no-op + warning
- `components/diagnostics/base.py` 的 `import redis` 改为 `try/except`，`redis_client` 参数可选（传 None 时 `push_diagnostics` 自动跳过）
- `tools/performance_test.py`、`tools/test_opcua_status.py`、`tools/test_query.py`、`tools/test_query_direct.py` 整文件删除
- `tests/test_data_manager.py`、`tests/test_opcua_server.py` 整文件删除

standalone exe 现在**源码层面也不依赖 Redis**，可在无任何中间件的独立环境运行。

### 7.7.1 🟢 残留清理历史

- `parser.py` `parse()` 已简化为直接 `yaml.safe_load`（不再走临时文件）
- `variable.py` `RingBuffer._data` 多余的 None default 已删除
- `instance.py` TYPE_CHECKING 路径错已修正（`data_next.programs.base` → `components.programs.base`）
- 过期的 `dependency.cpython-313.pyc` / `expression_node.cpython-313.pyc` 已删除

### 7.8 ⚠️ 历史遗留：`v2 == 0` 表达式求值 bug（实际未复现）→ 测试已删除

`tests/test_v2_bug.py` 与 `tests/test_v2_debug.py` 已删除。
描述的现象（`classical_config/test_bug.yaml` 中 `v2 = v1 + 50` 每周期 `v2 == 0`）在当前代码实测不复现：

```
cycle 0: v1.out=0.0,    v2=50.0
cycle 1: v1.out=0.262,  v2=50.262
...
```

`v2 = 50.0`（不是 0）是 cycle 0 的预期行为（`v1.out = sin(0) = 0`，故 `v2 = 0 + 50`）。

### 7.9 设计上的限制

- **没历史存储**：跑出来就丢了，需要外部 OPC UA 客户端或 OPC UA Recorder 收数据。
- **没 Web 管理界面**：所有交互通过 YAML 文件 + 命令行 + OPC UA 客户端。
- **没热重载**：改完 YAML 必须重启 exe。
- **客户端写值依赖 `override_variable`**：见 7.6。
- **没有日志文件持久化**：默认走 `components.utils.logger`，通常写 `logs/`（如果有）；stdout 是主通道。

---

## 8. 完整可用的运行示例

### 8.1 现场快速跑水箱 demo

1. 复制 `DataFactory.exe` 和 `config/` 到目标机（Win 10/11）。
2. 双击 `DataFactory.exe`，或在 cmd 里运行：

```cmd
DataFactory.exe
```

3. 用 UAExpert 连 `opc.tcp://127.0.0.1:18951`，浏览 `Objects/DataFactory`，订阅 `tank_1.level / v_name.MV / v_name.SV / sin1.out`，看曲线。

4. 在 UAExpert 里写 `v_name.SV = 1.5`，观察 PV 经过 ~30 周期跟随到 1.5 附近。

### 8.2 用 OPC UA 客户端脚本验证

```cmd
:: 1. 启动 exe
DataFactory.exe -c config\tank_constant_sv.yaml

:: 2. 另开终端跑客户端
python test_opcua_client.py
```

### 8.3 跑整定测试（自动记录 SV 阶跃响应）

```cmd
:: 1. 启动
DataFactory.exe -c config\tank_constant_sv.yaml

:: 2. 另开终端跑 2 分钟的整定测试
python test_tank_stabilization.py
```

结束后 `tank_test_results.csv` 含 `timestamp / elapsed_seconds / phase` 三列 + 9 个监控节点的值，可用 Excel 打开看初始阶段与改 SV 后阶段的对照曲线。

### 8.4 跑一次离线导出

```cmd
DataFactory.exe -c config\tank_constant_sv.yaml --batch 2000 --export tank_2000.csv
```

输出 `tank_2000.csv` 含全部位号 2000 行；不写 OPC UA、不起后台线程，跑完即退。

### 8.5 起多个 demo

```cmd
:: 在 config/ 下放多份 yaml
copy config\tank_constant_sv.yaml config\tank_02.yaml
:: 把 tank_02.yaml 里的 instance 名字 (v_name / tank_1) 改成 v_name2 / tank_2
:: （否则多个实例会出现同一位号名，OPC UA 内部会冲突）

:: 然后
DataFactory.exe --config-dir config
```

会看到两个 OPC UA Server：18951（tank_constant_sv）和 18952（tank_02）。

---

## 9. 故障排查

- **exe 启动后立即退出**：看 stdout，应该是 DLL 缺失或路径问题；用 `python standalone_main.py` 跑源码版（需要先 `pip install -r requirements.txt`）能拿到完整 traceback。
- **OPC UA 客户端连不上**：确认 exe 启动日志里有 `Server started, press Ctrl+C to stop`；防火墙放行 18951；客户端用 `opc.tcp://127.0.0.1:18951`。
- **节点看不到 / 写值没生效**：先确认 YAML 里 `display_args` 写了非空列表（`display_args: []` 不会显示）；再确认表达式里的属性名是否在 `stored_attributes` 里。
- **运行时崩 / 没响应**：把 YAML 简化到最小可跑 demo（`sin1.out` 单节点），逐步加复杂定位哪段表达式出问题。
- **`--batch` 模式下生成的 CSV 列不对**：CSV 列由 `snapshot.keys()` 自动收集，是 review3 的最简导出（不走模板）；如需模板格式，请用 data_factory_server 的 `/export/run`。

---

**版本说明**：本手册对应 review3 v1.20.0。如要长期运行、多引擎编排、查历史、用 Web UI，请改用 data_factory_server。