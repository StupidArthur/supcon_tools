"""格式转换: 平台导出格式 (长表, 每 tag 1 sheet) → 平台导入格式 (宽表, 1 sheet 多 tag).

只关心数据 (字符串、列表、字典), 不接触 openpyxl. 数据从 xlsx_io 拿, 转换后交给 xlsx_io 写.

导出格式 (long):
  sheet 名 = tag 名
  每 sheet 4 列: [Tag Time, App Time, Quality, Tag Value]
  采样时间: 优先取 App Time (列 1), 缺失时回退 Tag Time (列 0)
  时间格式 'yyyy-MM-dd HH:mm:ss' (横杠, 可选带亚秒)
  Tag Value 是字符串
  时间方向: 倒序 (最新在前)
  跳 Quality 列 (不写入新表)

导入格式 (wide, 给 importTagValueHistory):
  1 个 sheet, A 列时间 + B+ 列 tag 值
  A1 = 'startTime,endTime,frequency,cron'  (4 段逗号)
  时间格式 'yyyy/MM/dd HH:mm:ss' (斜杠)
  Tag Value: 保持字符串 (V2 验证过平台强转)
  时间方向: 保持原方向 (V3 验证过倒序也能落地)
  cron: 活的 (SGW_3daeed6cb0 验证过, 占位不触发)

标准化函数: convert_export_to_wide_input(sheets) -> {"a1", "headers", "rows"}
"""
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# 活 cron (5 秒触发, 一次性导入足够)
ACTIVE_CRON = "0/5 * * * * ?"


def _parse_export_time(s: str) -> datetime:
    """'2026-06-24 03:46:30' 或 '2026-06-24 03:46:30.029' -> datetime.

    兼容平台导出格式可能带亚秒精度 (实测 5~6 位小数, 2026-07 反馈).
    优先 %f 解析; 不带小数时回退到纯秒格式.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间字符串: {s!r} (期望 'yyyy-MM-dd HH:mm:ss' 可选带小数)")


def _format_import_time(dt: datetime) -> str:
    """datetime -> '2026/06/24 03:46:30'."""
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def _infer_frequency(times: list[str]) -> int:
    """从时间列表推断采样周期(秒). 用相邻时间差."""
    if len(times) < 2:
        return 0
    dt1 = _parse_export_time(times[0])
    dt2 = _parse_export_time(times[1])
    diff = abs((dt2 - dt1).total_seconds())
    return int(diff)


def _long_to_internal(sheets: dict[str, list[list]]) -> dict:
    """导出 (long) → 内部统一格式.

    每 sheet 4 列: [Tag Time, App Time, Quality, Tag Value].
    用 App Time (列 1) 作为采样时间:
      - 老格式: Tag Time == App Time == 采样时间
      - 新格式: Tag Time = 值设置时间 (同一值所有行一致), App Time = 真实采样时间
    若 App Time 缺失, 回退到 Tag Time.

    Returns:
        {
            "tag_names": [str],          # tag 列表, 字母序稳定
            "times": [str],              # 'yyyy-MM-dd HH:mm:ss', 保序去重 (按 sheet 内出现顺序)
            "values": [[any, ...]],      # values[i][j] = tag j 在 times[i] 的值
            "frequency": int,            # 推断的采样周期(秒)
        }
    """
    tag_names = sorted(sheets.keys())
    seen = set()
    times = []
    values_by_tag: dict[str, dict[str, object]] = {tag: {} for tag in tag_names}

    for tag in tag_names:
        rows = sheets[tag]
        if not rows:
            continue
        # 跳过表头
        for row in rows[1:]:
            if not row:
                continue
            # 优先 App Time (列 1), 缺失时回退 Tag Time (列 0)
            t_raw = row[1] if len(row) > 1 and row[1] is not None else row[0]
            if t_raw is None:
                continue
            t = str(t_raw)
            v = row[3] if len(row) > 3 else None
            if t not in seen:
                seen.add(t)
                times.append(t)
            values_by_tag[tag][t] = v

    values = []
    for t in times:
        values.append([values_by_tag[tag].get(t) for tag in tag_names])

    return {
        "tag_names": tag_names,
        "times": times,
        "values": values,
        "frequency": _infer_frequency(times),
    }


def _internal_to_input(wide: dict) -> dict:
    """内部统一格式 → 准备写入 xlsx 的数据.

    Returns:
        {
            "a1": str,                  # 元信息 4 段
            "headers": [str],           # tag 名 (写 B1+)
            "rows": [[time, v1, v2, ...]],  # 数据行 (写 A3+)
        }
    """
    times_export = wide["times"]
    tag_names = wide["tag_names"]
    values = wide["values"]
    frequency = wide["frequency"]

    # 时间转换: 解析 → 重新格式化
    times_import = [_format_import_time(_parse_export_time(t)) for t in times_export]

    # A1: startTime=最早, endTime=最晚, frequency, cron
    if times_export:
        all_dt = [_parse_export_time(t) for t in times_export]
        start_dt = min(all_dt)
        end_dt = max(all_dt)
        a1 = f"{_format_import_time(start_dt)},{_format_import_time(end_dt)},{frequency},{ACTIVE_CRON}"
    else:
        a1 = f",,,{ACTIVE_CRON}"

    # 数据行: [time_import, v1, v2, ...] 保持原方向
    rows = [[t] + list(vals) for t, vals in zip(times_import, values)]

    return {
        "a1": a1,
        "headers": list(tag_names),
        "rows": rows,
    }


def convert_export_to_wide_input(sheets: dict[str, list[list]]) -> dict:
    """标准化转换函数: 导出格式 → 导入格式数据.

    Args:
        sheets: {sheet_name: rows}, 来自 read_all_sheets.
                每 sheet 第一行表头 ['Tag Time', 'App Time', 'Quality', 'Tag Value'].

    Returns:
        {"a1": str, "headers": [str], "rows": [[time, v1, v2, ...]]}
        直接喂给 xlsx_io.write_wide_xlsx 即可.
    """
    log.info(
        "convert_export_to_wide_input: %d sheets, 时间列取 App Time (缺失回退 Tag Time)",
        len(sheets),
    )
    wide = _long_to_internal(sheets)
    out = _internal_to_input(wide)
    log.info(
        "convert 完成: %d tags × %d 行 × 1 时间列, frequency=%ds, time range=[%s, %s]",
        len(out["headers"]), len(out["rows"]), wide["frequency"],
        out["rows"][0][0] if out["rows"] else "n/a",
        out["rows"][-1][0] if out["rows"] else "n/a",
    )
    return out
