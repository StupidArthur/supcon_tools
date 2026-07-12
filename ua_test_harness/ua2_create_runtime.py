"""Precise UA-2-1 creation scenarios using real add_tag / list_tags.

Sixteen-case batch constraints:
- 每个 Case 自建独立数据源与位号
- 资源登记到 cc.registry,清理顺序位号 → 数据源
- 名称统一以 ua_auto_ua2_ds_* / ua_auto_ua2_tag_* 开头
- 所有判断基于最终查询结果,不是单点布尔
"""
from __future__ import annotations

import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures import datasource
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus

from ua_test_harness.ua2_common import (
    NAMESPACE_INDEX,
    active_rows,
    endpoint,
    exact,
    prepare_datasource,
    unique,
    wait_for,
)


def _add_tag_real(ctx, tag_name: str, ds_id: int) -> dict[str, Any]:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes

    return add_tag(
        _api(ctx),
        tag_name=tag_name,
        data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"],
        ds_id=ds_id,
        group_id="0",
        unit="",
        only_read=False,
        frequency=1,
        need_push=True,
        tag_desc="ua-2-1 precise batch",
        is_vector=True,
        tag_base_name="2_" + tag_name,
    )


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _delete_tag_physical(ctx, tag_id: int) -> None:
    from tpt_api.datahub import delete_tags_physical

    delete_tags_physical(_api(ctx), [tag_id])


def _delete_ds(ctx, ds_id: int) -> None:
    from tpt_api.datahub import delete_ds_info

    delete_ds_info(_api(ctx), [ds_id])


def duplicate_name_rejected(ctx, cc):
    """UA-2-1-017:

    重名位号必须被拒绝,且原记录未被覆盖。
    """
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)
    ds_id = ds["id"]

    first_name = unique(ctx, "ua_auto_ua2_tag_dup")
    first = _add_tag_real(ctx, first_name, ds_id)
    first_id = int(first["id"])
    cc.registry.register(
        "tag:" + first_name,
        "tag",
        lambda: _delete_tag_physical(ctx, first_id),
        payload={"id": first_id, "name": first_name},
    )

    original_snapshot = {
        "id": first_id,
        "dsId": first.get("dsId"),
        "tagName": first.get("tagName"),
        "tagBaseName": first.get("tagBaseName"),
        "dataType": first.get("dataType"),
    }

    rejected = False
    try:
        _add_tag_real(ctx, first_name, ds_id)
    except Exception:
        rejected = True

    check_true("duplicate_rejected", rejected)

    matched = exact(active_rows(ctx, tagName=first_name), "tagName", first_name)
    check_eq("only_one_record", 1, len(matched))
    rec = matched[0]
    check_eq("dsId_unchanged", original_snapshot["dsId"], rec.get("dsId"))
    check_eq("id_unchanged", original_snapshot["id"], int(rec.get("id")))
    check_eq("tagBaseName_unchanged", original_snapshot["tagBaseName"], rec.get("tagBaseName"))
    return CaseStatus.PASS


def empty_name_rejected(ctx, cc):
    """UA-2-1-019:

    tag_name="" 调用 add_tag 必须失败;不允许偷偷接受并落库。
    """
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    err_id: int | None = None
    failed = False
    try:
        result = _add_tag_real(ctx, "", ds["id"])
        maybe_id = result.get("id") or result.get("tagId")
        if maybe_id:
            err_id = int(maybe_id)
    except Exception:
        failed = True

    check_true("empty_name_rejected", failed)
    matched = exact(active_rows(ctx, tagName=""), "tagName", "")
    check_eq("no_empty_record", 0, len(matched))

    if err_id is not None:
        try:
            _delete_tag_physical(ctx, err_id)
        except Exception:
            pass
        return CaseStatus.FAIL
    return CaseStatus.PASS


def _make_length_name(prefix: str, target_len: int) -> str:
    suffix = "_end"
    head_room = target_len - len(suffix)
    if head_room <= 0:
        return prefix + suffix
    payload = prefix + ("x" * (head_room - len(prefix))) + suffix
    return payload[:target_len]


def _verify_length(ctx, cc, target_len: int):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    name = _make_length_name("ua_auto_ua2_tag_len" + str(target_len) + "_", target_len)
    assert len(name) == target_len, (len(name), target_len)

    accepted = False
    err_id: int | None = None
    try:
        result = _add_tag_real(ctx, name, ds["id"])
        maybe_id = result.get("id") or result.get("tagId")
        if maybe_id:
            err_id = int(maybe_id)
            accepted = True
    except Exception:
        accepted = False

    if accepted:
        cc.registry.register(
            "tag:" + name,
            "tag",
            lambda: _delete_tag_physical(ctx, err_id) if err_id else None,
            payload={"id": err_id, "name": name},
        )
        matched = exact(active_rows(ctx, tagName=name), "tagName", name)
        check_eq("only_one_match", 1, len(matched))
        rec = matched[0]
        check_eq("name_byte_equal", name, rec.get("tagName"))
        check_eq("length_exact", len(name), len(rec.get("tagName") or ""))
        return CaseStatus.PASS

    rows = exact(active_rows(ctx, tagName=name), "tagName", name)
    check_eq("no_partial_record_on_reject", 0, len(rows))
    if err_id is not None:
        try:
            _delete_tag_physical(ctx, err_id)
        except Exception:
            pass
    return CaseStatus.PASS


def name_length_127(ctx, cc):
    """UA-2-1-021:总长度=127 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 127)


def name_length_128(ctx, cc):
    """UA-2-1-022:总长度=128 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 128)
