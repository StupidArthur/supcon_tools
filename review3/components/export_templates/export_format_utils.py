"""
导出格式解析：将对话框中的 title_names 解析为时间列表头与第二行说明。
"""

from __future__ import annotations

from typing import Tuple

from .template_manager import DEFAULT_TIME_DESCRIPTION


def parse_title_names(header_rows: int, title_names: str) -> Tuple[str, str | None]:
    """
    解析 TITLE 名字符串为时间列第 1 行表头与（可选）第 2 行说明。

    - header_rows == 1：整串为时间列第 1 行表头；第 2 行无。
    - header_rows == 2：按第一个英文逗号 `,` 拆成两段；第一段为第 1 行，第二段为第 2 行。
      若无逗号，第二行回退为 DEFAULT_TIME_DESCRIPTION。

    Args:
        header_rows: 1 或 2
        title_names: 用户输入的 TITLE 名

    Returns:
        (time_column_name, time_row2_description)
        header_rows==1 时第二项为 None
    """
    text = (title_names or "").strip()
    if header_rows == 1:
        return (text or "timeStamp", None)
    # header_rows == 2
    if "," in text:
        first, rest = text.split(",", 1)
        row1 = first.strip() or "timeStamp"
        row2 = rest.strip() or DEFAULT_TIME_DESCRIPTION
        return (row1, row2)
    return (text or "timeStamp", DEFAULT_TIME_DESCRIPTION)
