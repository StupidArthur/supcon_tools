"""Precise UA-2-2 query scenarios using tag-info/page only."""
from __future__ import annotations

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.ua2_common import active_rows, create_read_tag, prepare_datasource, unique


def _prepared(ctx, cc):
    ds = prepare_datasource(ctx, cc)
    name = unique(ctx, "ua_auto_ua22")
    tag, row = create