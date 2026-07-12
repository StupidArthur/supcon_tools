"""Precise UA-2-1 creation scenarios backed by confirmed APIs."""
from __future__ import annotations

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.ua2_common import active_rows, create_read_tag, prepare_datasource, unique, wait_rt


def create_tag_online(ctx, cc):
    ds = prepare_datasource(ctx, cc)
    tag, row = create_read_tag(ctx, cc, ds["id"])
    rt = wait_rt(ctx, tag["name"])
    check_true("tag_created", bool(tag.get("id")))
    check_eq("tag_name", tag["name"], row.get("tagName"))
    check_true("rt_available", bool(rt))
    return CaseStatus.PASS


def duplicate_name_rejected(ctx, cc):
    ds = prepare_datasource(ctx, cc)
    name = unique(ctx, "ua_auto_ua2_dup")
    first, _ = create_read_tag(ctx, cc, ds["id"], name=name)
    before = [r for r in active_rows(ctx, tagName=name) if r.get("tagName") == name]
    failed = False
    try:
        create_read_tag(ctx, cc, ds["id"], name=name)
    except Exception:
        failed = True
    after = [r for r in active_rows(ctx, tagName=name) if r.get("tagName") == name]
    check_true("duplicate_rejected", failed)
    check_eq("single_original_record", 1, len(after))
    check_eq("original_id_unchanged", int(first["id"]), int(after[0]["id"]))
    check_eq("preexisting_count", 1, len(before))
    return CaseStatus.PASS
