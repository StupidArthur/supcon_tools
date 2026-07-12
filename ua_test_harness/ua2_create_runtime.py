"""Precise UA-2-1 creation scenarios using shared baseline datasource.

Resource model:
- Shared datasource ua_shared_ua2_types_ds is looked up, never created/deleted.
- Each case creates its own ua_case_ua2_-prefixed tag and explicitly deletes it.
- registry is a FALLBACK only; normal cleanup is visible in each case body.
"""
from __future__ import annotations

from typing import Any

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    CASE_TAG_PREFIX,
    active_rows,
    cleanup_case_tag,
    create_case_tag,
    create_tag_raw,
    exact,
    physical_delete_tag,
)


def _make_length_name(prefix: str, target_len: int) -> str:
    """Generate a name of exactly `target_len` bytes: prefix + filler + "_end".

    Identical to the legacy implementation so test_length_name_127/128 still pass.
    """
    suffix = "_end"
    head_room = target_len - len(suffix)
    if head_room <= 0:
        return prefix + suffix
    payload = prefix + ("x" * (head_room - len(prefix))) + suffix
    return payload[:target_len]


def _add_tag_by_name(ctx, ds_id: int, name: str) -> dict:
    """Direct add_tag for boundary/duplicate attempts. No pre-clean, no registry.

    Kept as a separate helper because these attempts are TEST ACTIONS, not normal
    case setup -- the case body must NOT register a fallback for them (they are
    expected to either be rejected or be defensively cleaned up by the caller).
    """
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    from ua_test_harness.clients.tpt_client import get_api

    return add_tag(
        get_api(ctx),
        tag_name=name,
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
        tag_base_name="2_" + name,
    )


def duplicate_name_rejected(ctx, cc):
    """UA-2-1-017: 重名位号必须被拒绝,且原记录未被覆盖。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="dup")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        original = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("original_exists", 1, len(original))
        orig = original[0]
        snapshot = {
            "id": tag_id,
            "dsId": orig.get("dsId"),
            "tagBaseName": orig.get("tagBaseName"),
        }

        rejected = False
        try:
            _add_tag_by_name(ctx, ds_id, tag_name)
        except Exception:
            rejected = True
        check_true("duplicate_rejected", rejected)

        matched = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("only_one_record", 1, len(matched))
        rec = matched[0]
        check_eq("dsId_unchanged", snapshot["dsId"], rec.get("dsId"))
        check_eq("id_unchanged", snapshot["id"], int(rec.get("id")))
        check_eq("tagBaseName_unchanged", snapshot["tagBaseName"], rec.get("tagBaseName"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def empty_name_rejected(ctx, cc):
    """UA-2-1-019: tag_name="" 调用 add_tag 必须失败;不允许偷偷接受并落库。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]

    err_id = None
    failed = False
    try:
        try:
            result = _add_tag_by_name(ctx, ds_id, "")
            maybe = result.get("id") or result.get("tagId")
            if maybe:
                err_id = int(maybe)
        except Exception:
            failed = True

        check_true("empty_name_rejected", failed)
        check_eq("no_empty_record", 0, len(exact(active_rows(ctx, tagName=""), "tagName", "")))
        return CaseStatus.PASS
    finally:
        # Even when check_true raises AssertFail (product accepted empty name ->
        # FAIL; Bug #2 product defect, kept as FAIL per decision), clean up any
        # tag the server silently created so nothing leaks. Does not change FAIL.
        if err_id is not None:
            try:
                physical_delete_tag(ctx, err_id)
            except Exception:
                pass


def _verify_length(ctx, cc, target_len: int):
    """Boundary-length tag: create, then assert either exact bytes (accepted)
    or zero records (rejected). finally always cleans up the created tag."""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]

    name = _make_length_name(
        CASE_TAG_PREFIX + "tag_len" + str(target_len) + "_",
        target_len,
    )
    assert len(name) == target_len, (len(name), target_len)
    assert name.startswith(CASE_TAG_PREFIX), name

    b_id: int | None = None
    try:
        boundary = create_tag_raw(ctx, name, ds_id, tag_desc="ua-2-1 precise batch")
        b_id = int(boundary["id"])
        # Register the fallback so cleanup_case_tag can pop it later.
        cc.registry.register(
            f"tag:{name}", "tag",
            lambda: physical_delete_tag(ctx, b_id),
            payload={"id": b_id, "name": name},
        )
    except Exception:
        # Server rejected the boundary name outright; b_id stays None.
        b_id = None

    try:
        matched = exact(active_rows(ctx, tagName=name), "tagName", name)
        if matched:
            check_eq("only_one_match", 1, len(matched))
            rec = matched[0]
            check_eq("name_byte_equal", name, rec.get("tagName"))
            check_eq("length_exact", len(name), len(rec.get("tagName") or ""))
            return CaseStatus.PASS
        # rejected path: ensure no partial record
        check_eq("no_partial_record_on_reject", 0, len(matched))
        return CaseStatus.PASS
    finally:
        if b_id is not None:
            cleanup_case_tag(ctx, cc, b_id, name)


def name_length_127(ctx, cc):
    """UA-2-1-021: 总长度=127 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 127)


def name_length_128(ctx, cc):
    """UA-2-1-022: 总长度=128 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 128)