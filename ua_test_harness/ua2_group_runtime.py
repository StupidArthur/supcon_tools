"""UA-2-5 分组 dispatcher。"""
from __future__ import annotations

from typing import Any

from ua_test_harness.assertions import check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import active_rows, cleanup_case_tag, create_case_tag, exact


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _observed(ctx, meta, detail: Any = None) -> CaseStatus:
    ctx.bag[f"observed_{meta['id']}"] = detail or meta.get("title")
    return CaseStatus.OBSERVED


def dispatch_ua2_5(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])

    from tpt_api.datahub import add_tag_group, add_tag_group_relation, get_tag_group_tree

    api = _api(ctx)
    group_name = f"ua_case_ua2_grp_{cid[-3:]}"
    try:
        grp = add_tag_group(api, group_name=group_name, parent_id="0")
        group_id = str(grp.get("id") or grp.get("groupId") or "")
        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:])
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            add_tag_group_relation(api, group_id=group_id, tag_ids=[tag_id])
            rows = active_rows(ctx, tagName=tag_name)
            check_true("tag_still_active", bool(rows))
            groups = get_tag_group_tree(api)
            ctx.bag[f"group_{cid}"] = {"group_id": group_id, "groups": groups}
            return CaseStatus.PASS if group_id else _observed(ctx, meta, "group_create_explore")
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
    except Exception as exc:
        return _observed(ctx, meta, f"group_api:{exc}")
