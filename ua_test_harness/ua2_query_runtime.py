"""Precise UA-2-2 query scenarios on shared baseline datasources.

Resource model:
- Shared datasource ua_shared_ua2_types_ds (or ua_shared_ua2_empty_ds for 019)
  is looked up, never created/deleted.
- Each case creates its own ua_case_ua2_-prefixed tag (except 008/016/019)
  and explicitly deletes it.
- Filters that the API supports (tagName, dsId) are pushed down to list_tags;
  tagBaseName is NOT server-filterable, so 016 paginates all_active_rows and
  filters client-side.
- registry is a FALLBACK only; normal cleanup is visible in each case body.
"""
from __future__ import annotations

import time

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    active_rows,
    all_active_rows,
    cleanup_case_tag,
    create_case_tag,
    exact,
)


TAG_DESC = "ua-2-2 precise batch"


def query_config_fields(ctx, cc):
    """UA-2-2-004 + UA-2-2-033: 逐字段断言 10 个配置字段持久化。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="cfg", data_type="INT", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        row = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_true("found_persisted", bool(row))
        rec = row[0]
        check_eq("tagName", tag_name, rec.get("tagName"))
        check_eq("tagBaseName", "2_" + tag_name, rec.get("tagBaseName"))
        check_eq("dsId", ds_id, rec.get("dsId"))
        check_eq("tagType", 1, rec.get("tagType"))
        check_eq("unit", "", rec.get("unit"))
        check_eq("frequency", 1, rec.get("frequency"))
        check_eq("onlyRead", False, rec.get("onlyRead"))
        check_eq("needPush", True, rec.get("needPush"))
        check_eq("tagDesc", TAG_DESC, rec.get("tagDesc"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_repeat_stable(ctx, cc):
    """UA-2-2-005: 三次相同 list_tags 调用 total / ID 顺序 / 配置一致。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="rep", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        sample = lambda: active_rows(ctx, tagName=tag_name)
        first = sample()
        second = sample()
        third = sample()
        check_eq("same_count_first_second", len(first), len(second))
        check_eq("same_count_second_third", len(second), len(third))

        def ids(rows):
            return [int(r.get("id")) for r in rows]
        check_eq("id_order_stable_1_2", ids(first), ids(second))
        check_eq("id_order_stable_2_3", ids(second), ids(third))

        seen = {int(r.get("id")) for r in first}
        check_eq("no_duplicate_id_in_rows", len(seen), len(first))

        sel = next((r for r in first if int(r.get("id")) == tag_id), None)
        check_true("target_row_present", sel is not None)
        check_eq("tagName_stable", tag_name, sel.get("tagName"))
        check_eq("dsId_stable", ds_id, sel.get("dsId"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_missing_name(ctx, cc):
    """UA-2-2-008: 不存在的名称查询返回空集合,不报错。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    require_shared_datasource(ctx, "types")
    impossible = "ua_case_ua2_missing_" + str(time.time_ns())
    check_eq("empty_resultset_on_missing", 0, len(active_rows(ctx, tagName=impossible)))
    return CaseStatus.PASS


def query_clear_name_filter(ctx, cc):
    """UA-2-2-011: 同一 dsId 下两条 case 位号,空过滤恢复 dsId 范围集合;两条均在范围。

    NOTE: Cleanup is per-tag (NOT in a loop over a shared variable) to avoid
    the closure late-binding trap. create_case_tag/cleanup_case_tag handle each
    registry entry independently.
    """
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]

    a = create_case_tag(ctx, cc, ds_id, suffix="qca", tag_desc=TAG_DESC)
    b = create_case_tag(ctx, cc, ds_id, suffix="qcb", tag_desc=TAG_DESC)
    a_id, a_name = int(a["id"]), a["name"]
    b_id, b_name = int(b["id"]), b["name"]

    try:
        targeted = exact(active_rows(ctx, tagName=a_name), "tagName", a_name)
        check_eq("exactly_a", 1, len(targeted))

        broad = active_rows(ctx, dsId=ds_id)  # server-side scope, not global fetch-all
        names = {r.get("tagName") for r in broad}
        check_true("a_in_broad", a_name in names)
        check_true("b_in_broad", b_name in names)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, b_id, b_name)
        cleanup_case_tag(ctx, cc, a_id, a_name)


def query_base_name_exact(ctx, cc):
    """UA-2-2-015: tagBaseName 保留 namespace 前缀与下划线。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    base_suffix = "ua_b15_" + str(time.time_ns())
    expected_base = "2_" + base_suffix
    tag = create_case_tag(
        ctx, cc, ds_id,
        suffix="b15", tag_base_name=expected_base, tag_desc=TAG_DESC,
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_true("hit_by_name", bool(rows))
        rec = rows[0]
        check_eq("tagBaseName_namespace_preserved", expected_base, rec.get("tagBaseName"))
        check_eq("tagName_separate", tag_name, rec.get("tagName"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_missing_base_name(ctx, cc):
    """UA-2-2-016: 不存在的 tagBaseName 返回空集合 (server-side tagBaseName filter is
    not supported, so we paginate all_active_rows and filter client-side)."""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    require_shared_datasource(ctx, "types")
    impossible = "9_impossible_base_" + str(time.time_ns())
    matching = [r for r in all_active_rows(ctx) if r.get("tagBaseName") == impossible]
    check_eq("empty_for_impossible_base", 0, len(matching))
    return CaseStatus.PASS


def query_empty_datasource(ctx, cc):
    """UA-2-2-019: 无位号的 empty 数据源按 dsId 查返回空集 (server-side dsId filter)."""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "empty")
    check_eq("empty_datasource_returns_empty_set", 0, len(active_rows(ctx, dsId=ds["id"])))
    return CaseStatus.PASS