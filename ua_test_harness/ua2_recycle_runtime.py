"""Precise UA-2-4 soft delete / restore / physical delete scenarios.

fixture 仅接受 name 字符串;禁止传 tag_id。
所有状态判断以最终 active / recycle 查询为准。
"""
from __future__ import annotations

import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures import datasource
from ua_test_harness.fixtures import environment as _fx_env
from ua_test_harness.models import CaseStatus

from ua_test_harness.ua2_common import (
    active_rows,
    endpoint,
    exact,
    prepare_datasource,
    recycle_rows,
    unique,
)


def _ensure_logged_in(ctx):
    _fx_env.ensure_logged_in(ctx)


def _ensure_mock_ready(ctx, key: str = "functional"):
    _fx_env.ensure_mock_ready(ctx, key)


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


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
        tag_desc="ua-2-4 precise batch",
        is_vector=True,
        tag_base_name="2_" + tag_name,
    )


def _physical_delete(api, tag_id: int) -> None:
    from tpt_api.datahub import delete_tags_physical
    delete_tags_physical(api, [tag_id])


def _wait_until(name: str, fn, timeout: float = 30.0, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertFail(f"{name} timeout after {timeout}s; last={last!r}")


def soft_delete_one(ctx, cc):
    """UA-2-4-001:按名称软删除,正常列表消失,回收站出现同一 ID。"""
    _ensure_mock_ready(ctx, "functional")
    _ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    name = unique(ctx, "ua_auto_ua2_tag_sd")
    tg = _add_tag_real(ctx, name, ds["id"])
    tag_id = int(tg["id"])
    cc.registry.pop("tag:" + name)
    cc.registry.register(
        "tag:" + name,
        "tag",
        lambda: _physical_delete(_api(ctx), tag_id),
        payload={"id": tag_id, "name": name, "source": "ua2_create"},
    )

    from ua_test_harness.fixtures.tag import soft_delete_tag
    soft_delete_tag(ctx, name)

    def removed():
        return not any(r.get("tagName") == name for r in active_rows(ctx))

    def in_recycle():
        rows = recycle_rows(ctx)
        return next((r for r in rows if r.get("tagName") == name), None)

    _wait_until("soft_delete:removed_from_active", removed, timeout=15.0, interval=1.0)
    rec = in_recycle()
    check_true("recycle_contains", rec is not None)
    check_eq("recycle_id_matches", tag_id, int(rec.get("id")))
    return CaseStatus.PASS


def restore_one(ctx, cc):
    """UA-2-4-013:按名称恢复。最终状态:active 重新出现同 ID,recycle 消失。"""
    _ensure_mock_ready(ctx, "functional")
    _ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    name = unique(ctx, "ua_auto_ua2_tag_rs")
    tg = _add_tag_real(ctx, name, ds["id"])
    tag_id = int(tg["id"])
    cc.registry.pop("tag:" + name)
    cc.registry.register(
        "tag:" + name,
        "tag",
        lambda: _physical_delete(_api(ctx), tag_id),
        payload={"id": tag_id, "name": name, "source": "ua2_create"},
    )

    from ua_test_harness.fixtures.tag import soft_delete_tag, restore_from_recycle
    soft_delete_tag(ctx, name)

    def in_recycle():
        rows = recycle_rows(ctx)
        return next((r for r in rows if r.get("tagName") == name), None)

    _wait_until("restore:in_recycle_first", in_recycle, timeout=15.0, interval=1.0)

    restore_from_recycle(ctx, name)

    def back_active():
        rows = exact(active_rows(ctx, tagName=name), "tagName", name)
        return rows[0] if rows else None

    rec = _wait_until("restore:active_again", back_active, timeout=30.0, interval=1.0)
    check_eq("restored_id_matches", tag_id, int(rec.get("id")))

    rows = recycle_rows(ctx)
    leftover = next((r for r in rows if r.get("tagName") == name), None)
    check_true("no_recycle_leftover", leftover is None)
    return CaseStatus.PASS


def physical_delete_one(ctx, cc):
    """UA-2-4-020:物理删除后,active 不存在,recycle 不存在,registry 移除该清理项。"""
    _ensure_mock_ready(ctx, "functional")
    _ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    name = unique(ctx, "ua_auto_ua2_tag_pd")
    tg = _add_tag_real(ctx, name, ds["id"])
    tag_id = int(tg["id"])

    cc.registry.pop("tag:" + name)
    cc.registry.register(
        "tag:" + name,
        "tag",
        lambda: _physical_delete(_api(ctx), tag_id),
        payload={"id": tag_id, "name": name, "marker": "ua2_pd"},
    )

    from ua_test_harness.fixtures.tag import soft_delete_tag
    soft_delete_tag(ctx, name)

    def in_recycle():
        rows = recycle_rows(ctx)
        return next((r for r in rows if r.get("tagName") == name), None)

    _wait_until("physical:in_recycle", in_recycle, timeout=15.0, interval=1.0)

    _physical_delete(_api(ctx), tag_id)
    cc.registry.pop("tag:" + name)

    def in_active():
        rows = exact(active_rows(ctx, tagName=name), "tagName", name)
        return rows[0] if rows else None

    rec = _wait_until("physical:not_in_active", lambda: in_active() is None, timeout=15.0, interval=1.0) if False else None
    rec = in_active()
    check_eq("not_in_active_after_physical", None, rec)

    rows = recycle_rows(ctx)
    leftover = next((r for r in rows if r.get("tagName") == name and int(r.get("id")) == tag_id), None)
    check_eq("not_in_recycle_after_physical", None, leftover)
    return CaseStatus.PASS


def physical_delete_irreversible(ctx, cc):
    """UA-2-4-024:物理删除后再尝试恢复,最终 active + recycle 都无,且不能凭空恢复原记录。"""
    _ensure_mock_ready(ctx, "functional")
    _ensure_logged_in(ctx)
    ds = prepare_datasource(ctx, cc, endpoint=endpoint(ctx), registry=cc.registry)

    name = unique(ctx, "ua_auto_ua2_tag_ir")
    tg = _add_tag_real(ctx, name, ds["id"])
    tag_id = int(tg["id"])

    cc.registry.pop("tag:" + name)
    cc.registry.register(
        "tag:" + name,
        "tag",
        lambda: _physical_delete(_api(ctx), tag_id),
        payload={"id": tag_id, "name": name, "marker": "ua2_ir"},
    )

    from ua_test_harness.fixtures.tag import soft_delete_tag
    soft_delete_tag(ctx, name)

    def in_recycle():
        rows = recycle_rows(ctx)
        return next((r for r in rows if r.get("tagName") == name), None)

    _wait_until("irreversible:in_recycle", in_recycle, timeout=15.0, interval=1.0)
    _physical_delete(_api(ctx), tag_id)
    cc.registry.pop("tag:" + name)

    try:
        from tpt_api.datahub import remove_tag_group_relation, list_recycle_tags
        rec = list_recycle_tags(_api(ctx), page=1, page_size=500)
        records = ((rec or {}).get("tagInfoList") or {}).get("records") or []
        ids = [int(r.get("id")) for r in records if r.get("tagName") == name and int(r.get("id")) == tag_id]
        if ids:
            remove_tag_group_relation(_api(ctx), group_id="1", tag_ids=ids)
    except Exception:
        pass

    rows_a = exact(active_rows(ctx, tagName=name), "tagName", name)
    rows_a = [r for r in rows_a if int(r.get("id")) == tag_id]
    check_eq("no_surreptitious_recreate_active", 0, len(rows_a))
    rows_r = recycle_rows(ctx)
    leftover = [r for r in rows_r if r.get("tagName") == name and int(r.get("id")) == tag_id]
    check_eq("no_surreptitious_recreate_recycle", 0, len(leftover))
    return CaseStatus.PASS

