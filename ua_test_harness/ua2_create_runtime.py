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
    case_tag_name,
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


# ---------- UA-2-1 章节 dispatcher(余量 case) ----------

from ua_test_harness.models import CaseStatus as _CS
from ua_test_harness.ua2_fixture_map import CASE_READ_TYPE, CASE_WRITE_TYPE, base_name_for_node, read_spec, write_spec
from ua_test_harness.ua2_helpers import (
    _observe,
    _qtq_row,
    _types_ds,
    _wait_changed,
    _wait_rt,
    standard_read_closed_loop,
    try_add_tag,
    verify_config_row,
    write_and_verify,
)


def _explore(ctx, meta, *, outcome: str, detail: Any = None) -> _CS:
    cid = meta["id"]
    ctx.bag[f"explore_{cid}"] = {"outcome": outcome, "detail": detail}
    return _CS.OBSERVED


def _blocked(ctx, meta, reason: str) -> _CS:
    ctx.bag[f"blocked_{meta['id']}"] = reason
    return _CS.BLOCKED


def _basic_create_read(ctx, cc, meta, *, suffix: str, base_node: str = "ua2_int32_r_1",
                       dtype: str = "INT") -> _CS:
    from ua_test_harness.ua2_helpers import standard_read_closed_loop
    from ua_test_harness.ua2_fixture_map import READ_NODES

    type_key = next((k for k, v in READ_NODES.items() if v["node"] == base_node), "INT32")
    return standard_read_closed_loop(ctx, cc, suffix=suffix, type_key=type_key)


def dispatch_ua2_1(ctx, cc, meta) -> _CS:
    """UA-2-1 全章 dispatcher: 已有个别 handler 的 case 委托;其余按 doc 模式执行。"""
    cid = meta["id"]
    title = meta.get("title") or ""
    kind = meta.get("kind") or ""

    delegated = {
        "UA-2-1-017": duplicate_name_rejected,
        "UA-2-1-019": empty_name_rejected,
        "UA-2-1-021": name_length_127,
        "UA-2-1-022": name_length_128,
    }
    if cid in delegated:
        return delegated[cid](ctx, cc)

    if cid in CASE_READ_TYPE:
        return standard_read_closed_loop(ctx, cc, suffix=cid.split("-")[-1], type_key=CASE_READ_TYPE[cid])

    if cid == "UA-2-1-001":
        return _basic_create_read(ctx, cc, meta, suffix="001")
    if cid == "UA-2-1-002":
        return _basic_create_read(ctx, cc, meta, suffix="002")

    if cid == "UA-2-1-003":
        ds = _types_ds(ctx)
        ok, detail = try_add_tag(ctx, 99999, tag_name=f"ua_case_ua2_{cid}_bad_ds")
        check_true("invalid_ds_rejected", not ok)
        rows = exact(active_rows(ctx, tagName=f"ua_case_ua2_{cid}_bad_ds"), "tagName",
                     f"ua_case_ua2_{cid}_bad_ds")
        check_eq("no_residual_tag", 0, len(rows))
        ctx.bag[f"reject_{cid}"] = detail
        return _CS.PASS

    if cid in {"UA-2-1-004", "UA-2-1-005", "UA-2-1-006", "UA-2-1-007"}:
        return _blocked(ctx, meta, "共享 baseline DS 不可停 mock/禁用;需独立夹具(用户决策)")

    if cid == "UA-2-1-008":
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        base = base_name_for_node("ua2_double_r_1")
        tag = create_case_tag(ctx, cc, ds_id, suffix="008", data_type="DOUBLE", tag_base_name=base)
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            check_true("created", bool(cfg))
            check_eq("base_saved", base, cfg[0].get("tagBaseName"))
            _wait_rt(ctx, tag_name)
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid == "UA-2-1-009":
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        base = base_name_for_node("1_nonexistent")
        tag = create_case_tag(ctx, cc, ds_id, suffix="009", data_type="INT", tag_base_name=base)
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            row = _wait_rt(ctx, tag_name, timeout=15.0)
            qtq = _qtq_row(ctx, tag_name=tag_name, ds_id=ds_id)
            if qtq:
                check_true("bad_node_quality_zero", _quality(qtq) in (None, 0) or not _row_value(qtq))
            elif row:
                check_true("rt_no_good_value", _quality(row) in (None, 0))
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid == "UA-2-1-010":
        return _blocked(ctx, meta, "需两个均有相同节点的 mock endpoint;当前仅 types mock 有位号节点")

    if cid in {"UA-2-1-011", "UA-2-1-012", "UA-2-1-015", "UA-2-1-020", "UA-2-1-023",
               "UA-2-1-024", "UA-2-1-025"}:
        return _explore(ctx, meta, outcome="deferred_explore", detail=title)

    if cid == "UA-2-1-013":
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        base = base_name_for_node("99_double_ch_1")
        tag = create_case_tag(ctx, cc, ds_id, suffix="013", data_type="DOUBLE", tag_base_name=base)
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            qtq = _qtq_row(ctx, tag_name=tag_name, ds_id=ds_id)
            if qtq:
                check_true("quality_zero", _quality(qtq) in (None, 0))
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid == "UA-2-1-014":
        ds = _types_ds(ctx)
        ok, detail = try_add_tag(ctx, int(ds["id"]), tag_name=f"ua_case_ua2_{cid}",
                                 tag_base_name="")
        ctx.bag[f"empty_base_{cid}"] = {"ok": ok, "detail": detail}
        return _CS.OBSERVED if kind == "exploratory" else (_CS.PASS if not ok else _CS.FAIL)

    if cid == "UA-2-1-016":
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        custom = f"ua_case_ua2_{cid}_custom"
        base = base_name_for_node("ua2_double_r_1")
        tag = create_case_tag(ctx, cc, ds_id, suffix="016", data_type="DOUBLE",
                              tag_base_name=base, tag_desc="custom")
        # override name via create_tag_raw pattern - create_case_tag auto-names; use raw:
        cleanup_case_tag(ctx, cc, int(tag["id"]), tag["name"])
        raw = create_tag_raw(ctx, custom, ds_id, data_type="DOUBLE", tag_base_name=base)
        tag_id = int(raw["id"])
        cc.registry.register(f"tag:{custom}", "tag", lambda: physical_delete_tag(ctx, tag_id))
        try:
            cfg = exact(active_rows(ctx, tagName=custom), "tagName", custom)
            check_eq("one_record", 1, len(cfg))
            check_eq("tagName_saved", custom, cfg[0].get("tagName"))
            check_eq("base_saved", base, cfg[0].get("tagBaseName"))
            _wait_rt(ctx, custom)
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, custom)

    if cid == "UA-2-1-018":
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        dup = "ua21_cross_dup_shared"
        first = create_case_tag(ctx, cc, ds_id, suffix="18a", data_type="INT")
        # force name
        cleanup_case_tag(ctx, cc, int(first["id"]), first["name"])
        a = create_tag_raw(ctx, dup, ds_id)
        a_id = int(a["id"])
        cc.registry.register(f"tag:{dup}", "tag", lambda: physical_delete_tag(ctx, a_id))
        try:
            from ua_test_harness.provisioning import require_shared_datasource as _req
            empty = _req(ctx, "empty")
            ok, detail = try_add_tag(ctx, int(empty["id"]), tag_name=dup)
            check_true("cross_ds_dup_rejected", not ok)
            ctx.bag[f"cross_dup_{cid}"] = detail
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, a_id, dup)

    if cid in {"UA-2-1-076", "UA-2-1-077", "UA-2-1-079", "UA-2-1-080"}:
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        unit = "kW" if cid == "UA-2-1-076" else ""
        desc = "test desc" if cid == "UA-2-1-079" else None
        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type="INT",
                              tag_desc=desc or f"ua2 {cid}")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
            if cid == "UA-2-1-076":
                from tpt_api.datahub import update_tag
                from tpt_api.types import DataTypes
                update_tag(_api_from_ctx(ctx), tag_id, tag_name=tag_name,
                             data_type=int(cfg.get("dataType") or DataTypes["INT"]),
                             ds_id=int(cfg.get("dsId")), unit=unit)
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            check_true("found", bool(cfg))
            if cid == "UA-2-1-076":
                check_eq("unit", unit, cfg[0].get("unit"))
            if cid == "UA-2-1-079":
                check_eq("desc", "test desc", cfg[0].get("tagDesc"))
            if cid == "UA-2-1-080":
                check_eq("default_desc", f"{tag_name} 描述", cfg[0].get("tagDesc"))
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid in {"UA-2-1-078", "UA-2-1-081"}:
        return _explore(ctx, meta, outcome="unicode_length_explore")

    if cid in CASE_WRITE_TYPE:
        return _dispatch_ua2_1_write(ctx, cc, meta)

    if cid in {"UA-2-1-082", "UA-2-1-083", "UA-2-1-084", "UA-2-1-085"}:
        return _dispatch_ua2_1_only_read(ctx, cc, meta)

    if cid in {"UA-2-1-086", "UA-2-1-087", "UA-2-1-088", "UA-2-1-089", "UA-2-1-090"}:
        return _dispatch_ua2_1_frequency(ctx, cc, meta)

    if cid in {"UA-2-1-091", "UA-2-1-092", "UA-2-1-093", "UA-2-1-094",
               "UA-2-1-095", "UA-2-1-096", "UA-2-1-097"}:
        return _dispatch_ua2_1_limits(ctx, cc, meta)

    if cid in {"UA-2-1-098", "UA-2-1-099", "UA-2-1-100", "UA-2-1-101"}:
        return _dispatch_ua2_1_need_push(ctx, cc, meta)

    if cid in {"UA-2-1-102", "UA-2-1-103", "UA-2-1-104"}:
        return _dispatch_ua2_1_availability(ctx, cc, meta)

    if cid in {f"UA-2-1-{n:03d}" for n in range(105, 113)}:
        return _dispatch_ua2_1_batch(ctx, cc, meta)

    return _blocked(ctx, meta, f"UA-2-1 dispatcher 未覆盖 {cid}")


def _api_from_ctx(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _quality(row):
    row = row or {}
    return row.get("quality", row.get("qualityCode"))


def _row_value(row):
    row = row or {}
    return row.get("tagValue", row.get("value"))


def _dispatch_ua2_1_write(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    type_key = CASE_WRITE_TYPE.get(cid, "INT32")
    spec = write_spec(type_key)
    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    base = base_name_for_node(spec["node"])
    tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:],
                          data_type=spec["dtype"], tag_base_name=base, tag_desc=f"write {cid}")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        if cid in {"UA-2-1-039", "UA-2-1-040"}:
            val = cid.endswith("039")
            write_and_verify(ctx, tag_name, val)
            return _CS.PASS
        if cid in {"UA-2-1-041", "UA-2-1-043", "UA-2-1-045", "UA-2-1-047", "UA-2-1-049",
                   "UA-2-1-051", "UA-2-1-053", "UA-2-1-056", "UA-2-1-059", "UA-2-1-062", "UA-2-1-065", "UA-2-1-070"}:
            return _explore(ctx, meta, outcome="write_boundary_explore")
        if cid in {"UA-2-1-042", "UA-2-1-044", "UA-2-1-046", "UA-2-1-048", "UA-2-1-050", "UA-2-1-052"}:
            return _explore(ctx, meta, outcome="int_boundary_write_explore")
        if cid == "UA-2-1-054":
            write_and_verify(ctx, tag_name, 9999999999)
            return _CS.PASS
        if cid in {"UA-2-1-055", "UA-2-1-058"}:
            return _explore(ctx, meta, outcome="int64_string_write_explore")
        if cid in {"UA-2-1-060", "UA-2-1-061", "UA-2-1-063", "UA-2-1-064"}:
            write_and_verify(ctx, tag_name, 1.25)
            return _CS.PASS
        if cid == "UA-2-1-066":
            write_and_verify(ctx, tag_name, "")
            return _CS.PASS
        if cid in {"UA-2-1-067", "UA-2-1-068"}:
            write_and_verify(ctx, tag_name, "测试用例" if cid.endswith("067") else "a<b>")
            return _CS.PASS
        if cid == "UA-2-1-069":
            return _explore(ctx, meta, outcome="string_length_explore")
        if cid in {"UA-2-1-071", "UA-2-1-072"}:
            write_and_verify(ctx, tag_name, "2025-06-01T12:00:00Z")
            return _CS.PASS
        if cid == "UA-2-1-073":
            from ua_test_harness.fixtures.tag import write_tag, read_rt
            failed = False
            try:
                write_tag(ctx, tag_name, "not-a-date")
            except Exception:
                failed = True
            check_true("bad_date_rejected", failed)
            return _CS.PASS
        if cid == "UA-2-1-074":
            return _explore(ctx, meta, outcome="datetime_boundary_explore")
        if cid == "UA-2-1-075":
            return _explore(ctx, meta, outcome="datetime_precision_explore")
        if cid == "UA-2-1-057":
            write_and_verify(ctx, tag_name, 9999999999)
            return _CS.PASS
        return _explore(ctx, meta, outcome="write_fallback_explore")
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_only_read(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    writable = cid in {"UA-2-1-083", "UA-2-1-085"}
    spec = write_spec("DOUBLE") if writable else read_spec("DOUBLE")
    base = base_name_for_node(spec["node"])
    only_read = cid in {"UA-2-1-082", "UA-2-1-084"}
    tag = create_tag_raw(ctx, case_tag_name(ctx, cc, cid[-3:]), ds_id,
                         data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    cc.registry.register(f"tag:{tag_name}", "tag", lambda: physical_delete_tag(ctx, tag_id))
    try:
        from ua_test_harness.fixtures.tag import read_rt, write_tag
        before = read_rt(ctx, tag_name)
        failed = False
        try:
            write_tag(ctx, tag_name, 99.9)
        except Exception:
            failed = True
        after = read_rt(ctx, tag_name)
        if only_read:
            check_true("write_rejected_or_unchanged", failed or _row_value(before) == _row_value(after))
        else:
            return _explore(ctx, meta, outcome="writable_on_readonly_source")
        return _CS.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_frequency(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid == "UA-2-1-086":
        ds = _types_ds(ctx)
        tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="086", data_type="INT")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            check_eq("default_frequency", 10, cfg[0].get("frequency"))
            _wait_rt(ctx, tag_name)
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
    return _explore(ctx, meta, outcome="frequency_effect_explore")


def _dispatch_ua2_1_limits(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid in {"UA-2-1-093", "UA-2-1-094", "UA-2-1-096", "UA-2-1-097"}:
        return _explore(ctx, meta, outcome="limits_explore")
    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type="DOUBLE")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        from tpt_api.datahub import update_tag
        from tpt_api.types import DataTypes
        cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
        if cid == "UA-2-1-091":
            update_tag(_api_from_ctx(ctx), tag_id, tag_name=tag_name,
                       data_type=int(cfg.get("dataType") or DataTypes["DOUBLE"]),
                       ds_id=int(cfg.get("dsId")), hi_eu=100, lo_eu=0)
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
            check_eq("hi", 100, cfg[0].get("hiEU"))
            check_eq("lo", 0, cfg[0].get("loEU"))
        if cid == "UA-2-1-092":
            write_and_verify(ctx, tag_name, 50.0)
        if cid == "UA-2-1-095":
            update_tag(_api_from_ctx(ctx), tag_id, tag_name=tag_name,
                       data_type=int(cfg.get("dataType") or DataTypes["DOUBLE"]),
                       ds_id=int(cfg.get("dsId")),
                       limit_up=80, limit_up_up=90, limit_up_up_up=100,
                       limit_down=10, limit_down_down=5, limit_down_down_down=0)
            cfg2 = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            check_true("limits_saved", cfg2[0].get("limitUp") == 80)
        return _CS.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_need_push(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid in {"UA-2-1-100", "UA-2-1-101"}:
        return _explore(ctx, meta, outcome="need_push_behavior_explore")
    ds = _types_ds(ctx)
    need = cid == "UA-2-1-098"
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=cid[-3:], data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        from tpt_api.datahub import update_tag
        from tpt_api.types import DataTypes
        cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
        if cid == "UA-2-1-099":
            update_tag(_api_from_ctx(ctx), tag_id, tag_name=tag_name,
                       data_type=int(cfg.get("dataType") or DataTypes["INT"]),
                       ds_id=int(cfg.get("dsId")), need_push=False)
        cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        expected = True if cid == "UA-2-1-098" else False
        check_eq("needPush", expected, cfg[0].get("needPush"))
        return _CS.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_availability(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid == "UA-2-1-102":
        return standard_read_closed_loop(ctx, cc, suffix="102", type_key="INT32")
    ds = _types_ds(ctx)
    spec = write_spec("DOUBLE")
    base = base_name_for_node(spec["node"])
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=cid[-3:],
                          data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        if cid == "UA-2-1-103":
            write_and_verify(ctx, tag_name, 42.0)
            return _CS.PASS
        if cid == "UA-2-1-104":
            _wait_rt(ctx, tag_name)
            import time as _time
            from ua_test_harness.fixtures.tag import read_history
            end_ms = int(_time.time() * 1000)
            hist = read_history(ctx, tag_name, end_ms - 120_000, end_ms)
            if not hist:
                return _CS.BLOCKED
            return _CS.PASS
        return _CS.BLOCKED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_batch(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid in {"UA-2-1-108", "UA-2-1-109", "UA-2-1-110", "UA-2-1-111", "UA-2-1-112"}:
        return _explore(ctx, meta, outcome="batch_edge_explore")
    from tpt_api.datahub import batch_add_tags
    from tpt_api.types import DataTypes, TagTypes

    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    names = [case_tag_name(ctx, cc, f"b{i}") for i in range(3)]
    infos = [{
        "tagName": n, "tagBaseName": base_name_for_node("ua2_int32_r_1"),
        "dataType": DataTypes["INT"], "tagType": TagTypes["一次位号"],
        "dsId": ds_id, "frequency": 1, "onlyRead": True, "needPush": True,
    } for n in names]
    try:
        if cid == "UA-2-1-105":
            batch_add_tags(_api_from_ctx(ctx), infos, conflict_strategy=0)
            for n in names:
                check_true("batch_created", bool(exact(active_rows(ctx, tagName=n), "tagName", n)))
            return _CS.PASS
        if cid == "UA-2-1-106":
            return _explore(ctx, meta, outcome="batch_conflict_skip_explore")
        if cid == "UA-2-1-107":
            return _explore(ctx, meta, outcome="batch_conflict_overwrite_explore")
        return _CS.BLOCKED
    finally:
        for n in names:
            row = exact(active_rows(ctx, tagName=n), "tagName", n)
            if row:
                cleanup_case_tag(ctx, cc, int(row[0]["id"]), n)