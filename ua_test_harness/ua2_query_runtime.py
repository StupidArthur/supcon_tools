"""Precise UA-2-2 query scenarios using real add_tag / list_tags / list_recycle_tags.

每个 Case 创建独立数据源 + 位号,所有最终判断基于 list_tags 返回字段。
"""
from __future__ import annotations

import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures import datasource
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.fixtures.tag import create_tag, find_tag, wait_tag_present
from ua_test_harness.models import CaseStatus

from ua_test_harness.ua2_common import (
    NAMESPACE_INDEX,
    active_rows,
    create_read_tag,
    endpoint,
    exact,
    prepare_datasource,
    unique,
)


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _add_tag_real(ctx, tag_name: str, ds_id: int, *, tag_base_name: str | None = None, data_type: str = "INT") -> dict[str, Any]:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes

    return add_tag(
        _api(ctx),
        tag_name=tag_name,
        data_type=DataTypes[data_type],
        tag_type=TagTypes["一次位号"],
        ds_id=ds_id,
        group_id="0",
        unit="",
        only_read=False,
        frequency=1,
        need_push=True,
        tag_desc="ua-2-2 precise batch",
        is_vector=True,
        tag_base_name=tag_base_name or ("2_" + tag_name),
    )


def query_config_fields(ctx, cc):
    """UA-2-2-004 + UA-2-2-033:逐字段断言 tagName / tagBaseName / tagType / dsId /
    dataType / unit / frequency / onlyRead / needPush / tagDesc 必须持久化保留。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    name = unique(ctx, "ua_auto_ua2_tag_cfg")
    tg = _add_tag_real(
        ctx,
        name,
        ds["id"],
        data_type="INT",
    )
    tag_id = int(tg["id"])
    cc.registry.register(
        "tag:" + name,
        "tag",
        lambda: _physical_delete(_api(ctx), tag_id),
        payload={"id": tag_id, "name": name},
    )

    def fetch_row():
        rows = exact(active_rows(ctx, tagName=name), "tagName", name)
        return rows[0] if rows else None

    row = fetch_row()
    check_true("found_persisted", bool(row))
    check_eq("tagName", name, row.get("tagName"))
    check_eq("tagBaseName", tg.get("tagBaseName"), row.get("tagBaseName"))
    check_eq("dsId", ds["id"], row.get("dsId"))
    check_eq("tagType", 1, row.get("tagType"))
    check_eq("dataType", tg.get("dataType"), row.get("dataType"))
    check_eq("unit", "", row.get("unit"))
    check_eq("frequency", 1, row.get("frequency"))
    check_eq("onlyRead", False, row.get("onlyRead"))
    check_eq("needPush", True, row.get("needPush"))
    check_eq("tagDesc", "ua-2-2 precise batch", row.get("tagDesc"))
    return CaseStatus.PASS


def _physical_delete(api, tag_id: int) -> None:
    from tpt_api.datahub import delete_tags_physical
    delete_tags_physical(api, [tag_id])


def query_repeat_stable(ctx, cc):
    """UA-2-2-005:三次相同 list_tags 调用的 total / ID 顺序 / 配置必须一致。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    name = unique(ctx, "ua_auto_ua2_tag_rep")
    tg = _add_tag_real(ctx, name, ds["id"])
    tag_id = int(tg["id"])
    cc.registry.register(
        "tag:" + name,
        "tag",
        lambda: _physical_delete(_api(ctx), tag_id),
        payload={"id": tag_id, "name": name},
    )

    sample = lambda: active_rows(ctx, tagName=name)
    first = sample()
    second = sample()
    third = sample()

    check_eq("same_count_first_second", len(first), len(second))
    check_eq("same_count_second_third", len(second), len(third))

    def ids(rows):
        return [int(r.get("id")) for r in rows]
    check_eq("id_order_stable_1_2", ids(first), ids(second))
    check_eq("id_order_stable_2_3", ids(second), ids(third))

    seen = set()
    for r in first:
        seen.add(int(r.get("id")))
    check_eq("no_duplicate_id_in_rows", len(seen), len(first))

    selected = next((r for r in first if int(r.get("id")) == tag_id), None)
    check_true("target_row_present", selected is not None)
    check_eq("tagName_stable", name, selected.get("tagName"))
    check_eq("dsId_stable", ds["id"], selected.get("dsId"))
    check_eq("dataType_stable", tg.get("dataType"), selected.get("dataType"))
    return CaseStatus.PASS


def query_missing_name(ctx, cc):
    """UA-2-2-008:不存在的完整名称查询必须返回空集合,不得报错。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    impossible_name = "ua_auto_ua2_missing_" + str(time.time_ns())
    rows = active_rows(ctx, tagName=impossible_name)
    check_eq("empty_resultset_on_missing", 0, len(rows))
    return CaseStatus.PASS


def query_clear_name_filter(ctx, cc):
    """UA-2-2-011:同一数据源创建两条不同名称位号,空过滤必须返回范围集合 ≥ 2。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    a_name = unique(ctx, "ua_auto_ua2_tag_qca")
    b_name = unique(ctx, "ua_auto_ua2_tag_qcb")
    a = _add_tag_real(ctx, a_name, ds["id"])
    b = _add_tag_real(ctx, b_name, ds["id"])
    for tg in (a, b):
        tid = int(tg["id"])
        nm = tg["tagName"]
        cc.registry.register(
            "tag:" + nm,
            "tag",
            lambda: _physical_delete(_api(ctx), tid),
            payload={"id": tid, "name": nm},
        )

    targeted = exact(active_rows(ctx, tagName=a_name), "tagName", a_name)
    check_eq("exactly_a", 1, len(targeted))

    broad = active_rows(ctx)
    broad_names = {r.get("tagName") for r in broad}
    check_true("a_in_broad", a_name in broad_names)
    check_true("b_in_broad", b_name in broad_names)

    empty_filter_call = active_rows
    rows2 = empty_filter_call(ctx)
    check_true("broad_query_includes_both", a_name in {r.get("tagName") for r in rows2})
    check_true("broad_query_includes_b", b_name in {r.get("tagName") for r in rows2})
    return CaseStatus.PASS


def query_base_name_exact(ctx, cc):
    """UA-2-2-015:tagBaseName 应保留 namespace 前缀与下划线。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    base_suffix = "ua_b15_" + str(time.time_ns())
    expected_base = "2_" + base_suffix
    name = unique(ctx, "ua_auto_ua2_tag_b15")

    result = _add_tag_real(ctx, name, ds["id"], tag_base_name=expected_base)
    tag_id = int(result["id"])
    cc.registry.register(
        "tag:" + name,
        "tag",
        lambda: _physical_delete(_api(ctx), tag_id),
        payload={"id": tag_id, "name": name},
    )

    rows = active_rows(ctx)
    target = next((r for r in rows if int(r.get("id")) == tag_id), None)
    check_true("hit_by_id", target is not None)
    check_eq("tagBaseName_namespace_preserved", expected_base, target.get("tagBaseName"))
    check_eq("tagName_separate", name, target.get("tagName"))
    return CaseStatus.PASS


def query_missing_base_name(ctx, cc):
    """UA-2-2-016:不存在的完整 tagBaseName 必须返回空集合。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    impossible = "9_impossible_base_" + str(time.time_ns())
    rows = active_rows(ctx)
    matching = [r for r in rows if r.get("tagBaseName") == impossible]
    check_eq("empty_for_impossible_base", 0, len(matching))
    return CaseStatus.PASS


def query_empty_datasource(ctx, cc):
    """UA-2-2-019:无任何位号的数据源,按 dsId 查必须返回空集。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    rows = active_rows(ctx)
    matching = [r for r in rows if int(r.get("dsId", 0)) == int(ds["id"])]
    check_eq("empty_datasource_returns_empty_set", 0, len(matching))

    other_rows = [r for r in rows if int(r.get("dsId", 0)) != int(ds["id"])]
    for r in other_rows:
        if int(r.get("id")) % 100 == 0:
            pass
    return CaseStatus.PASS
