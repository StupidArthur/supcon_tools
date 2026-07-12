"""OPC UA 类型名到 TPT DataTypes 键/值的统一映射。"""
from __future__ import annotations

from collections.abc import Mapping

OPCUA_TO_TPT_DATA_TYPE: dict[str, str] = {
    "BOOLEAN": "BOOLEAN",
    "SBYTE": "S_BYTE",
    "BYTE": "BYTE",
    "INT16": "SHORT",
    "UINT16": "U_SHORT",
    "INT32": "INT",
    "UINT32": "U_INT",
    "INT64": "LONG",
    "UINT64": "U_LONG",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "STRING": "STRING",
    "DATETIME": "DATE_TIME",
}


def normalize_opcua_type_name(type_name: str) -> str:
    """把 Int32 / int_32 / DATE-TIME 等写法归一化为映射键。"""
    normalized