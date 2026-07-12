"""Precise UA-2-1 tag creation scenarios backed by confirmed APIs."""
from __future__ import annotations

from tpt_api.datahub import add_tag, delete_tags_physical
from tpt_api.types import DataTypes, TagTypes

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.ua2_common import (
    active_rows,
    api,
    create_read_tag,
    prepare_datasource,
    unique,
    wait_rt,
)


def _raw_add(ctx, *, name: str, ds_id: int, base_name: str):
    return add_tag(
        api(ctx),
        tag_name=name,
        data_type=DataTypes["INT"],
        tag_type=TagTypes