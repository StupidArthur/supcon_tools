"""
xls 读写(xlrd/xlwt)。

xls 是 Excel 97-2003 旧格式,xlrd 2.x 不再支持 xlsx 只读 xls;xlwt 写 xls。
默认约定同 xlsx。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._xlsx import ExcelPrecisionError, _normalize_excel_handling
from .types import Table

EXCEL_DATE_MODE = 0  # 1900-based(默认)


# ───────── read ─────────


def _read_xls(  # noqa: PLR0913
    path: str | Path,
    *,
    header_rows: int | None = None,
    excel_numeric_handling: str = "forbid",
    sniff: bool = True,
) -> Table:
    handling = _normalize_excel_handling(excel_numeric_handling)
    eff_header_rows = header_rows if header_rows is not None else 1

    try:
        import xlrd  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError("读 xls 需要 xlrd: pip install xlrd==1.2.0") from e

    book = xlrd.open_workbook(str(path))
    sh = book.sheet_by_index(0)
    rows: list[list[Any]] = []
    for rx in range(sh.nrows):
        row = []
        for cx in range(sh.ncols):
            cell = sh.cell(rx, cx)
            v = cell.value
            # xlrd 对日期 cell 返回 tuple(年,月,日,h,m,s,...)
            if cell.ctype == xlrd.XL_CELL_DATE and v != 0.0:
                try:
                    import datetime as _dt

                    y, m, d, h, mi, s = xlrd.xldate_as_tuple(v, EXCEL_DATE_MODE)
                    row.append(_dt.datetime(y, m, d, h, mi, s))
                    continue
                except Exception:
                    pass
            row.append(v if v != "" else None)
        rows.append(row)

    if not rows:
        return Table(title=[], desc=None, data=[])

    if eff_header_rows == 0:
        if handling == "forbid":
            for r in rows:
                _check_no_numbers_xls(r, handling)
        return Table(title=[], desc=None, data=rows)

    title_row = rows[0]
    title = [(v if v is not None else "") for v in title_row]

    desc: list[str] | None = None
    data_start = 1
    if eff_header_rows >= 2 and len(rows) >= 2:
        desc_row = rows[1]
        desc = [(v if v is not None else "") for v in desc_row]
        data_start = 2

    data = rows[data_start:]
    if handling == "forbid":
        for r in data:
            _check_no_numbers_xls(r, handling)

    return Table(title=list(title), desc=desc, data=data)


def _check_no_numbers_xls(row, handling: str) -> None:
    if handling != "forbid":
        return
    import datetime as _dt

    for v in row:
        if v is None or isinstance(v, str):
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (_dt.datetime, _dt.date)):
            # 日期透出,不算"数字"
            continue
        if isinstance(v, (int, float)):
            raise ExcelPrecisionError(
                f"xls 数字 cell 命中 forbid 策略,值={v!r}。"
                "如需容忍,显式传 excel_numeric_handling='allow'。"
            )


# ───────── write ─────────


def _write_xls(  # noqa: PLR0913
    path: str | Path,
    table: Table,
    *,
    sheet_name: str = "Sheet1",
    header_rows: int = 1,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        import xlwt  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError("写 xls 需要 xlwt: pip install xlwt") from e

    book = xlwt.Workbook(encoding="utf-8")
    sh = book.add_sheet(sheet_name)

    eff_header_rows = header_rows
    if table.desc is None:
        eff_header_rows = 1

    row_idx = 0
    if table.title:
        for ci, v in enumerate(table.title):
            sh.write(row_idx, ci, ("" if v is None else str(v)))
        row_idx += 1
    if eff_header_rows >= 2 and table.desc is not None:
        for ci, v in enumerate(table.desc):
            sh.write(row_idx, ci, ("" if v is None else str(v)))
        row_idx += 1
    for row in table.data:
        for ci, v in enumerate(row):
            sh.write(row_idx, ci, ("" if v is None else str(v)))
        row_idx += 1

    book.save(str(p))
