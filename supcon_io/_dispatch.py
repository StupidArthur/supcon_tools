"""
read() / write() 单一入口。按扩展名分发到 _read_csv/_xlsx/_xls 等。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._csv import _read_csv, _write_csv
from ._xls import _read_xls, _write_xls
from ._xlsx import _read_xlsx, _write_xlsx
from .types import Table


def read(  # noqa: PLR0913
    path: str | Path,
    *,
    encoding: str | None = None,
    encoding_hints: tuple[str, ...] = (
        "utf-8-sig",
        "utf-8",
        "gbk",
        "gb2312",
    ),
    delimiter: str | None = None,
    delimiter_candidates: tuple[str, ...] = (",", ";", "\t", "|"),
    line_terminator: str = "\r\n",
    header_rows: int | None = None,
    skip_blank_lines: bool = True,
    excel_numeric_handling: str = "forbid",
    sniff: bool = True,
) -> Table:
    """
    读文件,按扩展名分发:

      .csv           → _read_csv
      .xlsx / .xlsm  → _read_xlsx
      .xls           → _read_xls

    返回 Table(title, desc, data)。
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return _read_csv(
            path,
            encoding=encoding,
            encoding_hints=encoding_hints,
            delimiter=delimiter,
            delimiter_candidates=delimiter_candidates,
            header_rows=header_rows,
            skip_blank_lines=skip_blank_lines,
            sniff=sniff,
        )
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(
            path,
            header_rows=header_rows,
            excel_numeric_handling=excel_numeric_handling,
            sniff=sniff,
        )
    if suffix == ".xls":
        return _read_xls(
            path,
            header_rows=header_rows,
            excel_numeric_handling=excel_numeric_handling,
            sniff=sniff,
        )
    raise ValueError(f"不支持的扩展名: {suffix},仅支持 .csv/.xlsx/.xlsm/.xls")


def write(  # noqa: PLR0913
    path: str | Path,
    table: Table,
    *,
    encoding: str = "utf-8",
    delimiter: str = ",",
    line_terminator: str = "\r\n",
    header_rows: int = 1,
    sheet_name: str = "Sheet1",
) -> None:
    """写文件,按扩展名分发。"""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        _write_csv(
            path,
            table,
            encoding=encoding,
            delimiter=delimiter,
            line_terminator=line_terminator,
            header_rows=header_rows,
        )
    elif suffix in (".xlsx", ".xlsm"):
        _write_xlsx(path, table, sheet_name=sheet_name, header_rows=header_rows)
    elif suffix == ".xls":
        _write_xls(path, table, sheet_name=sheet_name, header_rows=header_rows)
    else:
        raise ValueError(f"不支持的扩展名: {suffix},仅支持 .csv/.xlsx/.xlsm/.xls")
