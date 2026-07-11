"""ua_mocker YAML 组态解析。

按 ua_mocker/server_main.py:35 `_node_id_string` 的约定展开节点名：
    name + count → [name+"1", name+"2", ..., name+"N"]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ua_mocker 服务端 13 种类型 → tpt DataTypes 反向映射。
# 见 ua_mocker/type_mapping.py 的 TYPE_MAP；按常见类型先覆盖，需要时再补。
MOCKER_TYPE_TO_TPT = {
    "Boolean": 1,    # BOOLEAN
    "SByte": 2,      # S_BYTE
    "Byte": 3,       # BYTE
    "Short": 4,      # SHORT
    "UShort": 5,     # U_SHORT
    "Int32": 6,      # INT
    "UInt32": 7,     # U_INT
    "Int64": 8,      # LONG
    "UInt64": 9,     # U_LONG
    "Float": 10,     # FLOAT
    "Double": 11,    # DOUBLE
    "String": None,  # tpt tag 不支持字符串（DataTypes 无 STRING）
    "DateTime": None,  # tpt tag 不支持 DateTime
}


@dataclass
class MockerNode:
    """单条 YAML node 配置 + 展开后的实际节点 id 列表。"""
    name: str
    type: str
    count: int
    change: bool
    writable: bool
    default: Any = None
    expected_node_ids: list[str] = field(default_factory=list)
    tpt_data_type: int | None = None  # None 表示 tpt 不支持，需跳过


@dataclass
class MockerSpec:
    """解析后的 ua_mocker 组态。"""
    host: str
    port: int
    cycle_ms: int
    namespace_index: int
    endpoint: str
    nodes: list[MockerNode]

    @property
    def all_expected_node_ids(self) -> list[str]:
        """所有展开后的节点 id（按 YAML 顺序）。"""
        out: list[str] = []
        for n in self.nodes:
            out.extend(n.expected_node_ids)
        return out

    @property
    def registerable_node_ids(self) -> list[tuple[str, int]]:
        """(node_id, tpt_data_type) 列表 — tpt 支持的、可注册成 tag 的。"""
        out: list[tuple[str, int]] = []
        for n in self.nodes:
            if n.tpt_data_type is not None:
                for nid in n.expected_node_ids:
                    out.append((nid, n.tpt_data_type))
        return out

    @property
    def unsupported_node_ids(self) -> list[str]:
        """tpt 不支持的节点（如 String / DateTime），应跳过。"""
        out: list[str] = []
        for n in self.nodes:
            if n.tpt_data_type is None:
                out.extend(n.expected_node_ids)
        return out

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MockerSpec":
        """从 ua_mocker 的 YAML 文件解析。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"mocker YAML 不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        host = str(raw.get("server", "0.0.0.0"))
        port = int(raw.get("port", 18950))
        cycle_ms = int(raw.get("cycle", 1000))
        ns = int(raw.get("namespace_index", 1))

        nodes: list[MockerNode] = []
        for node_cfg in raw.get("nodes", []):
            name = str(node_cfg["name"])
            type_name = str(node_cfg["type"])
            count = int(node_cfg.get("count", 1))
            change = bool(node_cfg.get("change", False))
            writable = bool(node_cfg.get("writable", False))
            default = node_cfg.get("default", None)

            # 展开实际节点 id：name + i, i 从 1 到 count
            expected = [f"{name}{i}" for i in range(1, count + 1)]
            tpt_dt = MOCKER_TYPE_TO_TPT.get(type_name)

            nodes.append(MockerNode(
                name=name, type=type_name, count=count,
                change=change, writable=writable, default=default,
                expected_node_ids=expected, tpt_data_type=tpt_dt,
            ))

        endpoint = f"opc.tcp://{host}:{port}/ua_mocker/"
        return cls(
            host=host, port=port, cycle_ms=cycle_ms, namespace_index=ns,
            endpoint=endpoint, nodes=nodes,
        )
