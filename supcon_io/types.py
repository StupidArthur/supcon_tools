"""
supcon_io 内部数据类型。

设计原则：
- Table 是 read() 的返回、write() 的输入
- 读者/写者对"二维数据集"的统一抽象
- 不引入工业语义(位号/容器/OPC UA 一概不管)

字段说明:
  title: 第一行表头的列名(列名数组)。
         无表头时为空 list []。
  desc:  第二行描述(双行表头才有)。
         单行表头 / 无表头时为 None。
  data:  数据行,每行一个 list。
         元素类型随文件源而定:
           CSV → str
           xlsx / xls → openpyxl/xlrd 的原生类型(int/float/datetime/str/None)
"""
from __future__ import annotations

from typing import Any, NamedTuple


class Table(NamedTuple):
    title: list[str]
    desc: list[str] | None
    data: list[list[Any]]
