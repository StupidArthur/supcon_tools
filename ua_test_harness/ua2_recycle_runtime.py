"""UA-2 recycle scenarios."""
from ua_test_harness.assertions import check_true
from ua_test_harness.ua2_common import active_rows, recycle_rows
from ua_test_harness.fixtures.tag import soft_delete_tag, restore_from_recycle


def soft_delete_and_restore(ctx, cc, tag_id, name):
    soft_delete_tag(ctx, tag_id)
    check_true("removed_from_active", not any(x.get("tagName") == name for x in active_rows(ctx)))
    check_true("in_recycle", any(x.get("tagName") == name for x in recycle_rows(ctx)))
    restore_from_recycle(ctx, tag_id)
