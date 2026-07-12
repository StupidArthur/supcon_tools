"""Precise UA-2-4 soft delete / restore / physical delete on shared baseline datasource.

Resource model:
- Shared datasource ua_shared_ua2_types_ds is looked up, never created/deleted.
- Each case creates its own ua_case_ua2_-prefixed tag and exercises the
  soft-delete / restore / physical-delete lifecycle explicitly.
- registry is a FALLBACK only; normal cleanup is visible in each case body
  via `cleanup_case_tag(ctx, cc, tag_id, tag_name)` in finally.
- After the case body's own physical_delete (020/024), the registry fallback
  is popped so the finally cleanup is a safe no-op.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    active_rows,
    all_recycle_rows,
    cleanup_case_tag,
    create_case_tag,
    exact,
    physical_delete_tag,
    restore_tag,
    soft_delete_tag,
)


TAG_DESC = "ua-2-4 precise batch"


def _wait_until(name: str, fn: Callable[[], Any], timeout: float = 30.0, interval: float = 1.0) -> Any:
    """Poll `fn()` until it returns a truthy value, or raise AssertFail on timeout.

    Used for state-confirmation polling (e.g. soft-delete propagation).
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertFail(f"{name} timeout after {timeout}s; last={last!r}")


def soft_delete_one(ctx, cc):
    """UA-2-4-001: 软删除后 active 消失,回收站出现同一 ID。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="sd", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until(
            "soft_delete:removed_from_active",
            lambda: not exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name),
            timeout=15.0,
        )
        rec = next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None)
        check_true("recycle_contains", rec is not None)
        check_eq("recycle_id_matches", tag_id, int(rec.get("id")))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def restore_one(ctx, cc):
    """UA-2-4-013: 软删后恢复,active 重现同 ID,recycle 消失。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="rs", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until(
            "restore:in_recycle_first",
            lambda: next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None),
            timeout=15.0,
        )
        restore_tag(ctx, tag_id)
        rec = _wait_until(
            "restore:active_again",
            lambda: (
                lambda rows: rows[0] if rows else None
            )(exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)),
            timeout=30.0,
        )
        check_eq("restored_id_matches", tag_id, int(rec.get("id")))
        leftover = next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None)
        check_true("no_recycle_leftover", leftover is None)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def physical_delete_one(ctx, cc):
    """UA-2-4-020: 物理删除后 active/recycle 均不存在;registry 已被 case 自身 pop,finally 是 no-op。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="pd", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until(
            "physical:in_recycle",
            lambda: next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None),
            timeout=15.0,
        )
        # Test action: physical delete, then drop the registry fallback so the
        # finally cleanup_case_tag is a safe no-op (idempotent).
        physical_delete_tag(ctx, tag_id)
        cc.registry.pop(f"tag:{tag_name}")

        # Authoritative final-state assertions.
        active_match = next(
            (r for r in exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
             if int(r.get("id")) == tag_id),
            None,
        )
        check_eq("not_in_active_after_physical", None, active_match)
        recycle_match = next(
            (r for r in all_recycle_rows(ctx)
             if r.get("tagName") == tag_name and int(r.get("id")) == tag_id),
            None,
        )
        check_eq("not_in_recycle_after_physical", None, recycle_match)
        return CaseStatus.PASS
    finally:
        # Idempotent: registry entry was popped above; this is a no-op for state.
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def physical_delete_irreversible(ctx, cc):
    """UA-2-4-024: 物理删除后尝试恢复, 不能恢复;所有入口均不存在该 ID。

    The restore attempt is a real test action: we capture whether it raised
    (it should — the tag is no longer in recycle). The try/except swallows
    only the EXPECTED restore failure; the final-state assertions below are
    authoritative and must NOT be silently bypassed.
    """
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="ir", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until(
            "irreversible:in_recycle",
            lambda: next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None),
            timeout=15.0,
        )
        physical_delete_tag(ctx, tag_id)
        cc.registry.pop(f"tag:{tag_name}")

        # Real test action: attempt restore, then assert it could NOT recreate.
        try:
            restore_tag(ctx, tag_id)
        except Exception:
            pass  # restore is expected to fail; final-state assertions are authoritative

        # Authoritative: the tag must not be resurrected into active or recycle.
        rows_a = [
            r for r in exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            if int(r.get("id")) == tag_id
        ]
        check_eq("no_surreptitious_recreate_active", 0, len(rows_a))
        rows_r = [
            r for r in all_recycle_rows(ctx)
            if r.get("tagName") == tag_name and int(r.get("id")) == tag_id
        ]
        check_eq("no_surreptitious_recreate_recycle", 0, len(rows_r))
        return CaseStatus.PASS
    finally:
        # Idempotent: registry entry was popped above.
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


# ---------- UA-2-4 章节 dispatcher ----------

_EXISTING_UA2_4 = {
    "UA-2-4-001": soft_delete_one,
    "UA-2-4-013": restore_one,
    "UA-2-4-020": physical_delete_one,
    "UA-2-4-024": physical_delete_irreversible,
}


def _blocked_ua2_4(ctx, meta, reason: str) -> CaseStatus:
    ctx.bag[f"blocked_{meta['id']}"] = reason
    return CaseStatus.BLOCKED


def _observed_ua2_4(ctx, meta, detail=None) -> CaseStatus:
    ctx.bag[f"observed_{meta['id']}"] = detail or meta.get("title")
    return CaseStatus.OBSERVED


def _make_tag(ctx, cc, suffix: str):
    ds = require_shared_datasource(ctx, "types")
    return create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, tag_desc=TAG_DESC)


def dispatch_ua2_4(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    if cid in _EXISTING_UA2_4:
        return _EXISTING_UA2_4[cid](ctx, cc)

    if cid == "UA-2-4-002":
        ids = []
        try:
            for i in range(3):
                tag = _make_tag(ctx, cc, f"b{i}")
                ids.append(int(tag["id"]))
            for tid in ids:
                soft_delete_tag(ctx, tid)
            recycle = [r for r in all_recycle_rows(ctx) if int(r.get("id")) in ids]
            check_eq("batch_in_recycle", len(ids), len(recycle))
            return CaseStatus.PASS
        finally:
            for tid in ids:
                physical_delete_tag(ctx, tid)

    if cid == "UA-2-4-003":
        types = require_shared_datasource(ctx, "types")
        empty = require_shared_datasource(ctx, "empty")
        t1 = create_case_tag(ctx, cc, int(types["id"]), suffix="3a")
        t2 = create_case_tag(ctx, cc, int(empty["id"]), suffix="3b")
        try:
            soft_delete_tag(ctx, int(t1["id"]))
            soft_delete_tag(ctx, int(t2["id"]))
            r1 = [r for r in all_recycle_rows(ctx) if int(r.get("id")) == int(t1["id"])]
            check_eq("types_recycle", 1, len(r1))
            cleanup_case_tag(ctx, cc, int(t1["id"]), t1["name"])
            cleanup_case_tag(ctx, cc, int(t2["id"]), t2["name"])
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, int(t1["id"]), t1["name"])
            cleanup_case_tag(ctx, cc, int(t2["id"]), t2["name"])

    if cid == "UA-2-4-004":
        tag = _make_tag(ctx, cc, "id4")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        snap = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
        try:
            soft_delete_tag(ctx, tag_id)
            rec = next(r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name)
            for field in ("id", "tagName", "tagBaseName", "dsId", "dataType"):
                check_eq(field, snap.get(field), rec.get(field))
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid in {"UA-2-4-005", "UA-2-4-006", "UA-2-4-007", "UA-2-4-008", "UA-2-4-011", "UA-2-4-012",
               "UA-2-4-018", "UA-2-4-019", "UA-2-4-021", "UA-2-4-022", "UA-2-4-023", "UA-2-4-025"}:
        return _observed_ua2_4(ctx, meta)

    if cid == "UA-2-4-009":
        tag = _make_tag(ctx, cc, "w9")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            soft_delete_tag(ctx, tag_id)
            from ua_test_harness.fixtures.tag import write_tag
            failed = False
            try:
                write_tag(ctx, tag_name, 1.0)
            except Exception:
                failed = True
            check_true("write_blocked_after_soft_delete", failed)
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid == "UA-2-4-010":
        return _observed_ua2_4(ctx, meta, "asyncua_source_preserved_explore")

    if cid in {"UA-2-4-014", "UA-2-4-015", "UA-2-4-016", "UA-2-4-017"}:
        return _observed_ua2_4(ctx, meta, "batch_restore_or_rt_explore")

    if cid == "UA-2-4-026":
        tag = _make_tag(ctx, cc, "rb")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        base = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0].get("tagBaseName")
        try:
            soft_delete_tag(ctx, tag_id)
            physical_delete_tag(ctx, tag_id)
            cc.registry.pop(f"tag:{tag_name}")
            ok, _ = try_add_tag_rebuild(ctx, int(require_shared_datasource(ctx, "types")["id"]),
                                        tag_name=tag_name, tag_base_name=base)
            check_true("rebuild_after_physical", ok)
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid == "UA-2-4-027":
        victim = _make_tag(ctx, cc, "vic")
        other = _make_tag(ctx, cc, "oth")
        try:
            soft_delete_tag(ctx, int(victim["id"]))
            check_true("other_still_active", bool(exact(active_rows(ctx, tagName=other["name"]),
                                                      "tagName", other["name"])))
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, int(victim["id"]), victim["name"])
            cleanup_case_tag(ctx, cc, int(other["id"]), other["name"])

    return _blocked_ua2_4(ctx, meta, f"UA-2-4 dispatcher gap {cid}")


def try_add_tag_rebuild(ctx, ds_id: int, *, tag_name: str, tag_base_name: str):
    from ua_test_harness.ua2_helpers import try_add_tag
    return try_add_tag(ctx, ds_id, tag_name=tag_name, tag_base_name=tag_base_name)