"""UA-2 batch 残留资源清理工具。

清理以 `ua_auto_ua2_` 开头的:
  - 活动位号(active)
  - 回收站位号(recycle)
  - 数据源(ds-info)

顺序:收集 -> 物理删除位号 -> 删除数据源 -> 复核 -> 报告。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

PREFIX = "ua_auto_ua2_"


def _login(ctx: dict[str, str]):
    from tpt_api.client import AlgAPI

    api = AlgAPI(base_url=ctx["base_url"], timeout=20.0)
    api.login(ctx["username"], ctx["password"], "")
    return api


def _collect_tag_ids(api, name_prefix: str) -> tuple[list[int], list[int]]:
    from tpt_api.datahub import list_tags, list_recycle_tags

    active_page = list_tags(api, page=1, page_size=500, data={"tagName": name_prefix})
    active_rows = active_page.get("records") or []
    active_ids = [
        int(r["id"])
        for r in active_rows
        if str(r.get("tagName", "")).startswith(name_prefix)
    ]

    recycle_raw = list_recycle_tags(api, page=1, page_size=500)
    recycle_rows = (recycle_raw or {}).get("tagInfoList", {}).get("records") or []
    recycle_ids = [
        int(r["id"])
        for r in recycle_rows
        if str(r.get("tagName", "")).startswith(name_prefix)
    ]
    return active_ids, recycle_ids


def _collect_ds_ids(api, name_prefix: str) -> list[int]:
    from tpt_api.datahub import list_ds_info

    page = list_ds_info(api, page=1, page_size=500, data={"dsName": name_prefix})
    rows = page.get("records") or []
    return [
        int(r["id"])
        for r in rows
        if str(r.get("dsName", "")).startswith(name_prefix)
        or str(r.get("name", "")).startswith(name_prefix)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.153:31501/"))
    parser.add_argument("--username", default=os.environ.get("DATAHUB_USER", "admin"))
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--result", default="-")
    args = parser.parse_args()

    ctx = {
        "base_url": args.base_url,
        "username": args.username,
        "password": os.environ.get("DATAHUB_PASSWORD", ""),
    }
    if not ctx["password"]:
        print("DATAHUB_PASSWORD is required", file=sys.stderr)
        return 2

    api = _login(ctx)
    active_ids, recycle_ids = _collect_tag_ids(api, args.prefix)
    ds_ids = _collect_ds_ids(api, args.prefix)

    log: dict[str, Any] = {
        "prefix": args.prefix,
        "dryRun": bool(args.dry_run),
        "tagsActive": len(active_ids),
        "tagsRecycle": len(recycle_ids),
        "datasources": len(ds_ids),
        "actions": [],
    }

    if args.dry_run:
        log["actions"].append("dry_run_no_action")
    else:
        from tpt_api.datahub import change_ds_state, delete_ds_info, delete_tags_physical
        if active_ids or recycle_ids:
            all_tag_ids = sorted(set(active_ids + recycle_ids))
            try:
                delete_tags_physical(api, all_tag_ids)
                log["actions"].append(f"physical_delete_tags count={len(all_tag_ids)}")
            except Exception as exc:
                log["actions"].append(f"physical_delete_tags_failed error={type(exc).__name__}: {exc}")
        if ds_ids:
            # Must disable ds first or TPT refuses delete with "currently in use".
            for ds_id in ds_ids:
                try:
                    change_ds_state(api, ds_id, False)
                    log["actions"].append(f"ds_disable_ok id={ds_id}")
                except Exception as exc:
                    log["actions"].append(f"ds_disable_failed id={ds_id} error={type(exc).__name__}: {exc}")
            try:
                delete_ds_info(api, ds_ids)
                log["actions"].append(f"delete_ds count={len(ds_ids)}")
            except Exception as exc:
                log["actions"].append(f"delete_ds_failed error={type(exc).__name__}: {exc}")

    # Re-check
    post_active, post_recycle = _collect_tag_ids(api, args.prefix)
    post_ds = _collect_ds_ids(api, args.prefix)
    log["residualActive"] = len(post_active)
    log["residualRecycle"] = len(post_recycle)
    log["residualDatasources"] = len(post_ds)
    any_residual = (post_active or post_recycle or post_ds)
    log["exitCode"] = 1 if any_residual else 0

    if args.result == "-":
        print(json.dumps(log, ensure_ascii=False, indent=2))
    else:
        path = args.result
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    return log["exitCode"]


if __name__ == "__main__":
    raise SystemExit(main())
