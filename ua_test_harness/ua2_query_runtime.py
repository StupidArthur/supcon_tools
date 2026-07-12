"""UA-2 query scenarios."""
from ua_test_harness.assertions import check_true
from ua_test_harness.ua2_common import active_rows, exact


def query_by_name(ctx, cc, tag_name: str):
    rows = active_rows(ctx)
    check_true("tag_query_by_name", bool(exact(rows, "tagName", tag_name)))


def query_returns_active_only(ctx, cc):
    rows = active_rows(ctx)
    check_true("tag_query_response", isinstance(rows, list))
