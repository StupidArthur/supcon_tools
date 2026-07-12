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