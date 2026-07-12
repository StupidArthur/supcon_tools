"""UA-2 case-private residual cleanup.

Default scope: tags (active + recycle) whose tagName starts with `ua_case_ua2_`.
NEVER touches `ua_shared_ua2_` resources. Does NOT delete datasources unless
`--include-case-datasources` is given (and even then only `ua_case_ua2_ds_`).

Order: paginate+collect -> physical delete tags -> (opt) disable+delete case ds
       -> re-check -> report (exit 1 on any case-private residual).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from ua_test_harness.env_config import load_env_json

PREFIX = "ua_case_ua2_"
CASE_DS_PREFIX = "ua_case_ua2_ds_"
SHARED_PREFIX = "ua_shared_ua2_"


def _login(ctx: dict[str, str]):
    from tpt_api.client import AlgAPI

    api = AlgAPI(base_url=ctx["base_url"], timeout=20.0)
    api.login(ctx["username"], ctx["password"], "")
    return api


def _collect_tag_ids(api, name_prefix: str) -> tuple[list[int], list[int]]:
    from tpt_api.datahub import list_tags, list_recycle_tags

    active_ids: list[int] = []
    page = 1
    while True:
        res = list_tags(api, page=page, page_size=500, data={"tagName": name_prefix})
        recs = (res or {}).get("records") or []
        if not recs:
            break
        active_ids.extend(
            int(r["id"]) for r in recs if str(r.get("tagName", "")).startswith(name_prefix)
        )
        if len(recs) < 500:
            break
        page += 1

    recycle_ids: list[int] = []
    page = 1
    while True:
        raw = list_recycle_tags(api, page=page, page_size=200)
        recs = ((raw or {}).get("tagInfoList") or {}).get("records") or []
        if not recs:
            break
        recycle_ids.extend(
            int(r["id"]) for r in recs if str(r.get("tagName", "")).startswith(name_prefix)
        )
        if len(recs) < 200:
            break
        page += 1
    return active_ids, recycle_ids


def _collect_case_ds_ids(api) -> list[int]:
    from tpt_api.datahub import list_ds_info

    out: list[int] = []
    page = 1
    while True:
        res = list_ds_info(api, page=page, page_size=500, data={"dsName": CASE_DS_PREFIX})
        recs = (res or {}).get("records") or []
        if not recs:
            break
        out.extend(
            int(r["id"])
            for r in recs
            if str(r.get("dsName", "")).startswith(CASE_DS_PREFIX)
            or str(r.get("name", "")).startswith(CASE_DS_PREFIX)
        )
        if len(recs) < 500:
            break
        page += 1
    return out


def main() -> int:
    env_cfg = load_env_json()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=env_cfg.get("baseUrl", "http://10.10.58.153:31501/"))
    parser.add_argument("--username", default=env_cfg.get("username", "admin"))
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--include-case-datasources", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--result", default="-")
    args = parser.parse_args()

    if args.prefix.startswith(SHARED_PREFIX):
        print(f"refusing to clean shared resources (prefix={args.prefix!r})", file=sys.stderr)
        return 2

    ctx = {
        "base_url": args.base_url,
        "username": args.username,
        "password": env_cfg.get("password", ""),
    }
    if not ctx["password"]:
        print("env.json missing password", file=sys.stderr)
        return 2

    api = _login(ctx)
    active_ids, recycle_ids = _collect_tag_ids(api, args.prefix)
    case_ds_ids = _collect_case_ds_ids(api) if args.include_case_datasources else []

    log: dict[str, Any] = {
        "prefix": args.prefix,
        "dryRun": bool(args.dry_run),
        "tagsActive": len(active_ids),
        "tagsRecycle": len(recycle_ids),
        "caseDatasources": len(case_ds_ids),
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
        if case_ds_ids:
            for ds_id in case_ds_ids:
                try:
                    change_ds_state(api, ds_id, False)
                    log["actions"].append(f"ds_disable_ok id={ds_id}")
                except Exception as exc:
                    log["actions"].append(f"ds_disable_failed id={ds_id} error={type(exc).__name__}: {exc}")
            try:
                delete_ds_info(api, case_ds_ids)
                log["actions"].append(f"delete_case_ds count={len(case_ds_ids)}")
            except Exception as exc:
                log["actions"].append(f"delete_case_ds_failed error={type(exc).__name__}: {exc}")

    post_active, post_recycle = _collect_tag_ids(api, args.prefix)
    post_ds = _collect_case_ds_ids(api) if args.include_case_datasources else []
    log["residualActive"] = len(post_active)
    log["residualRecycle"] = len(post_recycle)
    log["residualCaseDatasources"] = len(post_ds)
    any_residual = bool(post_active or post_recycle or post_ds)
    log["exitCode"] = 1 if any_residual else 0

    out = json.dumps(log, ensure_ascii=False, indent=2)
    if args.result == "-":
        print(out)
    else:
        from pathlib import Path

        Path(args.result).parent.mkdir(parents=True, exist_ok=True)
        Path(args.result).write_text(out, encoding="utf-8")
    return log["exitCode"]


if __name__ == "__main__":
    raise SystemExit(main())
