# DataFactory

工业数据模拟与 OPC UA 服务一体化工具。

每个 YAML 配置 → 一个 Engine 线程 + 一个 OPC UA Server，全靠**内存 dict + queue** 通信。
**无中间件**：单进程，单 exe 即可部署到任意干净 Python 环境。

---

## 启动

把 `DataFactory.exe` 和 `config/` 目录放在同一文件夹，双击运行即可。

源码运行：

```bash
pip install -r requirements.txt
python standalone_main.py
```

默认行为：扫描 `config/` 下所有 `.yaml` / `.yml` 文件，每个文件起一个 Engine + 一个 OPC UA Server，
端口从 `18951` 起递增。`config/tank_constant_sv.yaml` 是自带的 PID 水箱液位示例。

## 命令行

```bash
# 单 yaml
python standalone_main.py -c config/tank_constant_sv.yaml

# 指定实例名 + 端口
python standalone_main.py -c config/tank_constant_sv.yaml -n my_tank --port 18960

# 批量跑 N 个周期并导出 CSV（GENERATOR 模式，不启 OPC UA）
python standalone_main.py -c config/tank_constant_sv.yaml --batch 100 --export out.csv

# 嵌入式调用：daemon 模式（主线程阻塞但不阻止其他调用）
python standalone_main.py --daemon
```

## 项目结构

```
review3/
├── components/
│   ├── programs/            # PID/Tank/Valve/Sine/...
│   ├── functions/           # abs/sqrt/...
│   ├── diagnostics/         # 诊断框架（redis 可选）
│   ├── export_templates/    # CSV/Excel 导出模板
│   └── utils/               # logger / doc_helper / export_helper
├── controller/
│   ├── engine.py            # UnifiedEngine + SAFE STATE
│   ├── parser.py            # DSL YAML 解析（含三层 namespace lag 分析）
│   ├── expression.py        # 表达式求值（InstanceProxy/AttributeProxy/VariableAccessor）
│   ├── clock.py             # Clock（REALTIME/GENERATOR 双模式）
│   ├── variable.py          # VariableStore + RingBuffer
│   ├── factory.py / instance.py
│   └── diagnostics/         # Engine 诊断提供者
├── datacenter/
│   └── opcua_server.py      # StandaloneOpcuaServer（内存驱动 + ready/join 信号）
├── tests/                   # pytest 全套 8/8 passed
├── classical_config/  config/   # 示例 YAML
├── standalone_main.py       # CLI 入口
├── requirements.txt         # 4 个依赖
└── DataFactory.spec / DataFactory.exe
```

## 文档

| 文件 | 内容 |
|------|------|
| [user_guide.md](user_guide.md) | 完整用户手册（DSL 语法、YAML 结构、OPC UA 节点、CLI 参数、设计细节、已知限制） |
| [todo.md](todo.md) | 本次 code review 的 bug 修复 + 测试结论 + 设计决策 |
| [doc/_archive/](doc/_archive/) | 历史文档归档（distributed 架构说明、Ubuntu 部署指南、Redis 设计等，仅作历史参考） |

## 依赖

仅 4 个：

- `asyncua` — OPC UA Server
- `PyYAML` — DSL 配置
- `python-dateutil` — 时间解析
- `numpy` — 数值计算（random 模块依赖）

无 Redis / 无 DuckDB / 无 Web 框架 / 无前端。

## OPC UA 客户端示例

```python
from asyncua import Client, ua

async def main():
    async with Client("opc.tcp://127.0.0.1:18951") as client:
        # namespace index 是 2（asyncua 默认：ns=0/1 内置，ns=2 是第一个用户 namespace）
        node = client.get_node(ua.NodeId("tank_1.level", 2))
        v = await node.read_value()  # 读
        await node.write_value(...)   # 写
```

完整示例见 [`test_opcua_client.py`](test_opcua_client.py) 和 [`user_guide.md`](user_guide.md) §5。

## 许可

MIT License

---

**DataFactory** — 让工业数据生成和模拟更简单、更便携。

*Designed by @yuzechao*
