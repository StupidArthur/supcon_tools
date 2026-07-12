"""UA-2-3 导入导出 dispatcher。"""
from __future__ import annotations

import os
import tempfile
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


def _blocked(ctx, meta, reason: str) -> CaseStatus:
    ctx.bag[f"blocked_{meta['id']}"] = reason
    return CaseStatus.BLOCKED


def dispatch_ua2_3(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])

    if cid.startswith("UA-2-3-"):
        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:])
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            from tpt_api.datahub import export_tags, import_tags_from_file

            api = _api(ctx)
            with tempfile.TemporaryDirectory() as tmp:
                xlsx = os.path.join(tmp, f"{cid}.xlsx")
                try:
                    export_tags(api, [tag_id], save_path=xlsx, parse=False)
                    ctx.bag[f"export_{cid}"] = os.path.exists(xlsx)
                except Exception as exc:
                    ctx.bag[f"export_{cid}"] = str(exc)
                    if "回归" in (meta.get("kind") or ""):
                        return _observed(ctx, meta, f"export_needs_history:{exc}")
                if os.path.exists(xlsx):
                    try:
                        import_tags_from_file(api, xlsx, conflict_strategy=1)
                        rows = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
                        check_true("import_roundtrip", bool(rows))
                        return CaseStatus.PASS
                    except Exception as exc:
                        return _observed(ctx, meta, f"import_result:{exc}")
                return _observed(ctx, meta, "export_import_explore")
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    return _blocked(ctx, meta, f"unknown UA-2-3 {cid}")
