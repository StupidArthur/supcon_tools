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


def tpt_data_type_key(opcua_type: str) -> str:
    key = str(opcua_type).upper().replace("_", "")
    return OPCUA_TO_TPT_DATA_TYPE.get(key, str(opcua_type))


def tpt_data_type_value(data_types: Mapping[str, int], opcua_type: str) -> int:
    return data_types[tpt_data_type_key(opcua_type)]
