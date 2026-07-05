"""
时间解析：dateutil 一段代码。

承诺 cover(2 种,带 S):
    "%Y/%m/%d %H:%M:%S"   # 2024/06/30 12:00:00
    "%Y-%m-%d %H:%M:%S"    # 2024-06-30 12:00:00

赠送 cover(不在承诺,出问题归 dateutil):
    ISO 8601               # 2024-06-30T12:00:00
    含微秒                  # 2024-06-30 12:00:00.123456
    单位数月日              # 2024/6/3 19:00:00
    纯日期                  # 2024-06-30 (默认 0:00)

不 cover:
    epoch 数字(返回 None)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    from dateutil import parser as _dateutil_parser

    _HAS_DATEUTIL = True
except ImportError:  # pragma: no cover - 极端环境兜底
    _HAS_DATEUTIL = False


def parse_time(value: Any) -> datetime | None:
    """
    把任意输入解析为 datetime,失败返回 None。

    行为:
      - 已是 datetime → 原样返回
      - None / 空字符串 → None
      - str → dateutil.parser.parse
      - 其他类型 → None
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if not _HAS_DATEUTIL:
            raise ImportError(
                "解析时间字符串需要 python-dateutil: pip install python-dateutil"
            )
        try:
            return _dateutil_parser.parse(s)
        except (ValueError, TypeError, OverflowError):
            return None
    return None
