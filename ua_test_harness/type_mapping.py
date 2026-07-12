"""OPC UA 类型名和底层位号名到 TPT 表示的统一映射。"""
from __future__ import annotations

import re
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
    "