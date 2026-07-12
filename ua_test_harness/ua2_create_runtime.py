"""Precise UA-2-1 creation scenarios.

Only uses confirmed tag creation/query/RT helpers.
"""
from __future__ import annotations

from ua_test_harness.assertions import check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.ua2_common import create_read_tag, wait_rt


def create_tag_online(ctx, cc):
    _ds, tag = create_read_tag(ctx, cc)
    row = wait_rt(ctx, tag["name"])
    check_true("tag_created", bool(tag.get("id")))
    check_true("rt_available", bool(row))
    return CaseStatus.PASS


def create_tag_and_query(ctx, cc):
    _ds, tag = create_read_tag(ctx, cc)
    row = wait_rt(ctx, tag["name"])
    check_true("tag_name", row.get("tagName", tag["name"]) == tag["name"])
    return CaseStatus.PASS
