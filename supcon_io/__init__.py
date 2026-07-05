"""
supcon_io - 通用二维数据集(CSV / xlsx / xls)读写模块。

单一入口:
    read(path, **kwargs)  -> Table
    write(path, table, **kwargs) -> None
    Table                 : NamedTuple(title, desc, data)

设计原则:
- 只管文件长什么样,不管数据在业务上是什么意思
- 单一入口 + 内部 _read_csv/_xlsx/_xls 拆分
- 无 FormatProfile,参数全在 read/write 的 keyword 上
- 内部 sniff(encoding/delimiter/header_rows)走 None 触发,显式传则跳过
- CSV 元素类型:str
- xlsx/xls 元素类型:openpyxl/xlrd 原生类型(int/float/datetime/str/None),
  excel_numeric_handling='forbid' 时数字 cell 抛 ExcelPrecisionError

时间解析(从 _time 暴露):
    parse_time(value) -> datetime | None
"""
from __future__ import annotations

from ._dispatch import read, write
from ._time import parse_time
from ._xlsx import ExcelPrecisionError
from .types import Table

__all__ = ["read", "write", "Table", "parse_time", "ExcelPrecisionError"]
__version__ = "0.1.0"
