"""UA-2 tag management scenarios.

Only scenarios with confirmed API semantics live here.
"""
from __future__ import annotations

import time

from ua_test_harness.assertions import check_true, AssertFail
from ua_test_harness.fixtures.tag import (
    create_tag,
    find_tag,
    soft_delete_tag,
    restore_from_recycle,
)


def scenario_create_and_read(ctx, name, ds_id):
    tag = create_tag(ctx, name=name, ds_id=ds_id, data_type="INT32", tag_base_name=f"2_{name}")
    row = find