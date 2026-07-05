"""
CSV 读写 + 内部 sniff。

设计原则:
- 不做 sheet 选择
- 不做 Excel 风格
- 一切格子读出来都是 str,数字/时间由调用方处理
- 内置 sniff:encoding / delimiter / header_rows;用户显式传则跳过对应项
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ._time import parse_time
from .types import Table

_DEFAULT_ENCODING_HINTS = ("utf-8-sig", "utf-8", "gbk", "gb2312")
_DEFAULT_DELIMITER_CANDIDATES = (",", ";", "\t", "|")
_DEFAULT_SNIFF_BYTES = 4096
_DEFAULT_SNIFF_ROWS = 20

# ───────── sniff ─────────


def _sniff_encoding(raw: bytes, hints: tuple[str, ...]) -> str:
    # BOM 优先(无歧义)
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    # 按 hints 试,第一个能 decode 的胜出
    for enc in hints:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(
        "sniff_encoding", raw, 0, len(raw), f"无法识别编码,尝试过 {hints}"
    )


def _count_delimiter(text: str, delim: str) -> list[int]:
    """统计每一行里 delim 出现的次数。"""
    counts = []
    for line in text.splitlines():
        if not line:
            continue
        counts.append(line.count(delim))
    return counts


def _sniff_delimiter(text: str, candidates: tuple[str, ...]) -> str:
    """
    在前 N 行里统计每个候选分隔符的出现次数,选"行间方差最小"的。
    正常 CSV 每行分隔符出现次数一致,方差接近 0;非分隔符字符出现次数随机,方差大。
    """
    best = None
    best_var = float("inf")
    for delim in candidates:
        counts = _count_delimiter(text, delim)
        if len(counts) < 2:
            continue
        avg = sum(counts) / len(counts)
        var = sum((c - avg) ** 2 for c in counts) / len(counts)
        # 分隔符不会让所有行出现 0 次(没有分隔的文件没有列)
        if avg < 0.5:
            continue
        if var < best_var:
            best_var = var
            best = delim
    if best is None:
        raise ValueError(f"无法嗅探分隔符(候选 {candidates}),请显式传 delimiter")
    return best


def _sniff_header_rows(
    text: str,
    delim: str,
) -> int:
    """
    看前 3 行嗅探表头行数。

    启发式:
      - 拆出第 1 行的列数 N1
      - 如果第 2 行存在,且列数 == N1,且第 2 行"汉字比例 ≥ 60%"
        → 双行表头(header_rows=2)
      - 否则单行(header_rows=1)

    边界:全英文描述行(如 timestamp / value)会被归为单行;这种情况
    用户需要显式传 header_rows=2。
    """
    lines = [ln for ln in text.splitlines() if ln.strip()][:3]
    if len(lines) < 2:
        return 1

    cols1 = [c for c in lines[0].split(delim)]
    cols2 = [c for c in lines[1].split(delim)]
    if len(cols1) != len(cols2):
        return 1

    # 第 2 行"汉字比例 ≥ 60%"判定为描述行
    # 遍历第 2 行全部字符
    all_chars = "".join(cols2)
    cn_count = sum(1 for ch in all_chars if "一" <= ch <= "鿿")
    total = max(1, len(all_chars))
    cn_ratio = cn_count / total
    return 2 if cn_ratio >= 0.6 else 1


def _sniff_csv(
    path: Path,
    encoding_hints: tuple[str, ...],
    delimiter_candidates: tuple[str, ...],
) -> tuple[str, str, int]:
    """嗅探 encoding / delimiter / header_rows。"""
    raw = path.read_bytes()[:_DEFAULT_SNIFF_BYTES]
    encoding = _sniff_encoding(raw, encoding_hints)
    text = raw.decode(encoding, errors="replace")
    # delimiter 用嗅探过的 encoding 解码后的文本做统计
    delimiter = _sniff_delimiter(text, delimiter_candidates)
    # 嗅探 header_rows 用文本前若干行足够
    head_lines = "\n".join(text.splitlines()[:_DEFAULT_SNIFF_ROWS])
    header_rows = _sniff_header_rows(head_lines, delimiter)
    return encoding, delimiter, header_rows


# ───────── read ─────────


def _read_csv(  # noqa: PLR0913
    path: str | Path,
    *,
    encoding: str | None = None,
    encoding_hints: tuple[str, ...] = _DEFAULT_ENCODING_HINTS,
    delimiter: str | None = None,
    delimiter_candidates: tuple[str, ...] = _DEFAULT_DELIMITER_CANDIDATES,
    header_rows: int | None = None,
    skip_blank_lines: bool = True,
    sniff: bool = True,
) -> Table:
    p = Path(path)

    # 默认值(允许 None 表示嗅探)
    eff_encoding = encoding
    eff_delimiter = delimiter
    eff_header_rows = header_rows if header_rows is not None else 1

    if sniff:
        # 把需要嗅探的项填进去
        need_enc = eff_encoding is None
        need_delim = eff_delimiter is None
        need_header = header_rows is None

        if need_enc or need_delim or need_header:
            try:
                s_enc, s_delim, s_header = _sniff_csv(
                    p, encoding_hints, delimiter_candidates
                )
                if need_enc:
                    eff_encoding = s_enc
                if need_delim:
                    eff_delimiter = s_delim
                if need_header:
                    eff_header_rows = s_header
            except (UnicodeDecodeError, ValueError):
                if need_enc:
                    eff_encoding = eff_encoding or "utf-8"
                if need_delim:
                    eff_delimiter = eff_delimiter or ","
                # need_header 已经有默认值 1

    if eff_encoding is None:
        eff_encoding = "utf-8"
    if eff_delimiter is None:
        eff_delimiter = ","

    # 用敲定的 encoding 读全文
    text = p.read_text(encoding=eff_encoding)
    reader = csv.reader(
        (ln for ln in text.splitlines() if ln.strip() or not skip_blank_lines),
        delimiter=eff_delimiter,
    )

    it = iter(reader)
    title: list[str] = []
    desc: list[str] | None = None
    data: list[list[Any]] = []

    # 拉表头
    try:
        first = next(it)
    except StopIteration:
        return Table(title=[], desc=None, data=[])

    if eff_header_rows == 0:
        # 无表头:没有 title,把 first 当数据第一行
        data.append([v for v in first])
    else:
        # 第一行表头
        title = [(c or "").strip() for c in first]
        # 可选第二行描述
        if eff_header_rows >= 2:
            try:
                second = next(it)
                desc = [(c or "").strip() for c in second]
            except StopIteration:
                desc = []

    # 数据行
    for row in it:
        if not row:
            continue
        data.append([v for v in row])

    return Table(title=title, desc=desc, data=data)


# ───────── write ─────────


def _write_csv(  # noqa: PLR0913
    path: str | Path,
    table: Table,
    *,
    encoding: str = "utf-8",
    delimiter: str = ",",
    line_terminator: str = "\r\n",
    header_rows: int = 1,
) -> None:
    """写 CSV。table.desc 必须存在且 header_rows >= 2 时才写第 2 行;否则强制 1 行。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    eff_header_rows = header_rows
    if table.desc is None:
        eff_header_rows = 1

    with p.open("w", encoding=encoding, newline="") as f:
        writer = csv.writer(f, delimiter=delimiter, lineterminator=line_terminator)
        # 单行/双行表头
        if table.title:
            writer.writerow(table.title)
        if eff_header_rows >= 2 and table.desc is not None:
            writer.writerow(table.desc)
        for row in table.data:
            writer.writerow([("" if v is None else str(v)) for v in row])
