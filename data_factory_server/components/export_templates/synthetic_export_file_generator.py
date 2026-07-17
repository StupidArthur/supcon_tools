"""
独立合成数据文件生成工具

在不运行仿真的情况下，按已有导出模板（YAML）生成与「快照导出」结构一致的 CSV / Excel 文件；
各数据列数值为 100～199 的整数锯齿波，便于联调与格式校验。

说明：Python 包名为 **components**（末尾有 s），导入时请写 ``from components....``，
不要写成 ``component``（会报 No module named 'component'）。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Sequence, Union

# 未设置 PYTHONPATH 时，将仓库根目录加入 sys.path，使 ``import components`` 可用（亦支持直接运行本脚本）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from components.export_templates.csv_exporter import CSVExporter
from components.export_templates.excel_exporter import ExcelExporter
from components.export_templates.template_manager import TemplateManager
from components.utils.logger import get_logger


logger = get_logger()

# 锯齿波取值范围（含端点）：100, 101, …, 199 后回到 100
SAWTOOTH_MIN = 100
SAWTOOTH_MAX = 199
SAWTOOTH_WIDTH = SAWTOOTH_MAX - SAWTOOTH_MIN + 1

# 默认输出目录（位于本包下，避免与业务 output/ 混淆）
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "generated_data"

# 解析 starttime/endtime 时依次尝试的格式（含 ISO）
_DATETIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y/%m/%d %H:%M:%S.%f",
    "%Y-%m-%d",
    "%Y/%m/%d",
)


def _parse_datetime(text: str) -> datetime:
    """
    将用户给定的时间字符串解析为 datetime（本地时区 naive）。

    优先尝试 ISO 8601（含 ``T`` 或空格分隔），再尝试模块内预置的 strptime 格式。
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("时间字符串不能为空")

    normalized = raw.replace("T", " ", 1) if "T" in raw else raw

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    raise ValueError(
        f"无法解析时间字符串: {text!r}，"
        f"请使用 ISO 或常见格式（如 %Y-%m-%d %H:%M:%S）",
    )


def _sawtooth_value(row_index: int) -> int:
    """第 row_index 行的锯齿波整数值，周期为 SAWTOOTH_WIDTH。"""
    return SAWTOOTH_MIN + (row_index % SAWTOOTH_WIDTH)


def _build_snapshots(
    tags: Sequence[str],
    times: List[datetime],
) -> List[dict[str, Union[bool, float, int, str]]]:
    """
    构造与 CSVExporter / ExcelExporter 兼容的快照列表。

    每行 need_sample=True；sim_time 为该行时刻的 Unix 时间戳（秒）；
    各 tag 列使用同一锯齿波数值（同索引行相同）。
    """
    snapshots: List[dict[str, Union[bool, float, int, str]]] = []
    for i, dt in enumerate(times):
        ts = dt.timestamp()
        val = _sawtooth_value(i)
        row: dict[str, Union[bool, float, int, str]] = {
            "need_sample": True,
            "sim_time": float(ts),
        }
        for name in tags:
            row[name] = val
        snapshots.append(row)
    return snapshots


def generate_synthetic_export_file(
    tags: List[Any],
    template: str,
    starttime: str,
    endtime: str,
    interval: float = 5.0,
) -> Path:
    """
    按导出模板生成合成数据文件（CSV 或 Excel，由模板 YAML 的 file_format 决定）。

    时间轴从 starttime 起，每隔 interval 秒一行，直到不超过 endtime。
    所有 tag 列在每一行取相同值，该值随行号在 100～199 间呈锯齿变化。

    Args:
        tags: 位号/列名列表（将转为 str）。
        template: 模板名，对应 ``templates/{template}.yaml``。
        starttime: 起始时刻字符串（可解析即可）。
        endtime: 结束时刻字符串（含该时刻所在采样点，若对齐）。
        interval: 采样间隔（秒），须为正数。

    Returns:
        写入文件的绝对路径。

    Raises:
        ValueError: 时间解析失败、interval 非法、或起止时刻无有效采样点。
        FileNotFoundError: 模板不存在。
    """
    if interval <= 0:
        raise ValueError(f"interval 必须为正数，当前为 {interval!r}")

    tag_names = [str(t).strip() for t in tags if str(t).strip()]
    start_dt = _parse_datetime(starttime)
    end_dt = _parse_datetime(endtime)
    if start_dt > end_dt:
        raise ValueError(f"starttime 不能晚于 endtime: {start_dt} > {end_dt}")

    times: List[datetime] = []
    cur = start_dt
    delta = timedelta(seconds=float(interval))
    while cur <= end_dt:
        times.append(cur)
        cur += delta

    if not times:
        raise ValueError("在给定起止时间与间隔下没有生成任何采样点")

    manager = TemplateManager()
    export_template = manager.load_template(template)
    snapshots = _build_snapshots(tag_names, times)

    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = export_template.file_format.lower()
    out_name = f"{template}_synthetic_{stamp}.{ext}"
    output_path = (DEFAULT_OUTPUT_DIR / out_name).resolve()

    fmt = export_template.file_format.lower()
    if fmt == "csv":
        exporter = CSVExporter(export_template, sample_interval=interval)
        exporter.export(snapshots, output_path, column_keys=tag_names or None)
    elif fmt in ("xlsx", "xls"):
        exporter = ExcelExporter(
            export_template,
            file_format=fmt,
            sheet_name=export_template.sheet_name,
            sample_interval=interval,
        )
        exporter.export(snapshots, output_path, column_keys=tag_names or None)
    else:
        raise ValueError(f"不支持的 file_format: {export_template.file_format}")

    logger.info(
        "合成导出文件已生成: path=%s, rows=%d, tags=%s",
        output_path,
        len(times),
        tag_names,
    )
    return output_path


if __name__ == "__main__":
    # 直接运行本模块时生成一份最小示例（不使用命令行参数）
    tags = [f'1_double_ch_{i}' for i in range(501, 1001)]
    _demo_path = generate_synthetic_export_file(
        tags=tags,
        template="prediction",
        starttime="2026-03-01 00:00:00",
        endtime="2026-04-01 00:10:00",
        interval=5.0,
    )
    logger.info("demo 输出: %s", _demo_path)
