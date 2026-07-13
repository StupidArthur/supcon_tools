"""UA-2-3 导入导出 helper。"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from ua_test_harness.assertions import check_eq, check_true

EXPECTED_EXPORT_COLUMNS = 21
EXPECTED_HEADER_ROW = [
    "Tag Name", "Base Tag Name", "Tag Type", "Datasource Name", "Unit", "Data Type",
    "Expression", "Tag Value", "Frequency", "High Limit", "HH Limit", "HHH Limit",
    "Low Limit", "LL Limit", "LLL Limit", "Description", "Group Name",
    "Real-time Push", "Readonly", "Lo EU", "Hi EU",
]


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def wait_collectible(ctx, tag_name: str, timeout: float = 60.0) -> None:
    """导出前等待 RT 有效(服务端要求有采集数据)。"""
    from ua_test_harness.ua2_precise import rt_row
    rt_row(ctx, tag_name, timeout=timeout)


def export_to_temp(ctx, tag_ids: list[int], *, suffix: str = "export") -> tuple[str, list[list[Any]]]:
    from tpt_api.datahub import export_tags

    tmp = tempfile.mkdtemp(prefix="ua23_")
    path = os.path.join(tmp, f"{suffix}.xlsx")
    rows = export_tags(_api(ctx), tag_ids, save_path=path, parse=True)
    return path, rows


def assert_export_rows(rows: list[list[Any]], *, min_rows: int = 2, tag_names: set[str] | None = None) -> None:
    check_true("has_header", len(rows) >= 1)
    check_eq("column_count", EXPECTED_EXPORT_COLUMNS, len(rows[0]))
    check_true("enough_rows", len(rows) >= min_rows)
    if tag_names:
        exported = {str(r[0]) for r in rows[1:] if r and r[0]}
        check_true("names_subset", tag_names.issubset(exported) or exported.issubset(tag_names))


def import_file(ctx, path: str, *, conflict_strategy: int = 1) -> dict[str, Any]:
    from tpt_api.datahub import import_tags_from_file
    return import_tags_from_file(_api(ctx), path, conflict_strategy=conflict_strategy)


def write_invalid_file(path: str, content: bytes) -> None:
    with open(path, "wb") as f:
        f.write(content)
