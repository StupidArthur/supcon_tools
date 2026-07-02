# -*- coding: utf-8 -*-
"""
数据读取与处理模块：从 CSV 加载数据，解析表头（节点名与类型）、时间戳与值。
编码默认 UTF-8；第一列第一格不关心。支持未来可扩展（当前仅 CSV）。

支持两种播放模式：
  - 时间戳模式（默认）：根据 CSV 中第一列的时间戳计算行间间隔
  - 跳过时间戳模式（skip_timestamp=True）：不依赖时间戳，由调用方指定固定间隔
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

# 时间戳格式（相对时间，仅用于计算间隔）
# 注意：Python strptime 中 %m/%d 自动支持单位数月/日（如 6/3）
TIMESTAMP_FORMATS = [
    "%Y/%m/%d %H:%M:%S",   # 2024/06/03 19:00:00
    "%Y/%m/%d %H:%M",      # 2024/06/03 19:00（无秒）
    "%Y-%m-%d %H:%M:%S",   # 2024-06-03 19:00:00
    "%Y-%m-%d %H:%M",      # 2024-06-03 19:00（无秒）
]

# 节点类型后缀
BOOL_SUFFIX = "[bool]"
WRITABLE_SUFFIX = "[w]"

# 跳过时间戳时使用的占位时间
_PLACEHOLDER_DATETIME = datetime(2000, 1, 1)


def _parse_timestamp(s: str) -> datetime | None:
    """解析时间戳，支持多种格式。"""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_node_header(cell: str) -> tuple[str, str, bool]:
    """
    解析表头单元格：node_name、node_name[bool]、node_name[w]、node_name[bool][w]。
    返回 (节点名，类型，是否可写)，节点名不含后缀；类型为 'float' 或 'bool'。
    """
    cell = (cell or "").strip()
    writable = WRITABLE_SUFFIX in cell
    if writable:
        cell = cell.replace(WRITABLE_SUFFIX, "").strip()
    if cell.endswith(BOOL_SUFFIX):
        name = cell[: -len(BOOL_SUFFIX)].strip()
        return (name or "node", "bool", writable)
    return (cell or "node", "float", writable)


def _parse_value(raw: str, node_type: str) -> Any:
    """将单元格字符串转为 float 或 bool。"""
    raw = (raw or "").strip().lower()
    if node_type == "bool":
        return raw in ("1", "true", "yes", "是")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def load_csv(
    data_file: str | Path,
    skip_timestamp: bool = False,
) -> tuple[list[tuple[str, str, bool]], list[tuple[datetime | None, list[Any]]], list[float]]:
    """
    从 CSV 加载数据。

    :param data_file: CSV 文件路径
    :param skip_timestamp: 是否跳过时间戳解析。
        为 True 时，第一列仍然被跳过（保持 CSV 格式不变），
        但不再要求其为有效时间戳，行不会因时间戳无效被丢弃。
        deltas_seconds 全部为 0.0（由调用方用固定间隔覆盖）。
    :return: (node_specs, rows, deltas_seconds)
      - node_specs: [(node_name, 'float'|'bool', writable), ...]，节点名不含后缀
      - rows: [(datetime|None, [val0, val1, ...]), ...]
      - deltas_seconds: 每行到下一行的间隔秒数
    """
    path = Path(data_file)
    text = path.read_text(encoding="utf-8")
    reader = csv.reader(text.strip().splitlines())

    rows_iter = iter(reader)
    header_row = next(rows_iter)
    # 第 1 行：第 1 列不管，第 2 列起为节点名
    node_specs = [_parse_node_header(cell) for cell in header_row[1:]]

    rows: list[tuple[datetime | None, list[Any]]] = []
    for r in rows_iter:
        if not r:
            continue
        ts = _parse_timestamp(r[0])
        if ts is None and not skip_timestamp:
            # 时间戳模式下，跳过无效时间戳的行
            continue
        # 跳过时间戳模式下，使用占位时间
        if ts is None:
            ts = _PLACEHOLDER_DATETIME
        values = [_parse_value(r[i + 1] if i + 1 < len(r) else "", node_type) for i, (_, node_type, _) in enumerate(node_specs)]
        rows.append((ts, values))

    # 计算相对时间差（秒）
    deltas_seconds: list[float] = []
    if skip_timestamp:
        # 跳过时间戳模式：间隔全部为 0，由调用方用固定值覆盖
        deltas_seconds = [0.0] * len(rows)
    else:
        for i in range(len(rows)):
            if i + 1 < len(rows):
                delta = (rows[i + 1][0] - rows[i][0]).total_seconds()
                deltas_seconds.append(max(0.0, delta))
            else:
                # 最后一行：与上一条的间隔相同
                if len(rows) >= 2:
                    last_delta = (rows[-1][0] - rows[-2][0]).total_seconds()
                    deltas_seconds.append(max(0.0, last_delta))
                else:
                    deltas_seconds.append(0.0)

    return node_specs, rows, deltas_seconds
