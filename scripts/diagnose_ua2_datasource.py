"""Read-only datasource diagnostic for UA-2.

Default mode lists active (server-side `dsId` filter) and recycle (paginated,
client-filtered by `dsId`) tags for a datasource. Emits a single JSON object
to stdout (or `--result`).

`--attempt-clean-delete` performs a guarded clean delete:
  - Only allowed on datasources whose name starts with `ua_case_ua2_` or
    legacy `ua_auto_ua2_`.
  - Refuses if active or recycle tags are still attached (reports
    `TAG_DEPENDENCY`) — silently deleting a DS that still has tags could mask
    a product behaviour we want to observe.
  - On approval: disable -> wait alive=false -> delete -> poll until id gone.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ALLOWED_CLEAN_PREFIXES = ("ua_case_ua2_", "ua_auto_ua2_")


def _login(base_url: str, username: str, password: str):
    from tpt_api.client import AlgAPI

    api = AlgAPI(base_url=base_url, timeout=20.0)
    api.login(username, password, "")
    return api


def _find_ds(api, *, ds_id=None, ds_name=None):
    from tpt_api.datahub import list_ds_info

    data: dict[str, Any] = {}
    if ds_id is not None:
        data["id"] = ds_id
    elif ds_name:
        data["dsName"] = ds_name
    page = list_ds_info(api, page=1, page_size=500, data=data or None)
    for r in (page or {}).get("records") or []:
        if ds_id is not None and int(r.get("id", -1)) != int(ds_id):
            continue
        if ds_name is not None and str(r.get("dsName") or r.get("name") or "") != ds_name:
            continue
        return r
    return None


def _active_tags_by_ds(api, ds_id: int) -> list[dict]:
    """Server-side dsId filter (paginated)."""
    from tpt_api.datahub import list_tags

    out: list[dict] = []
    page = 1
    while True:
        res = list_tags(api, page=page, page_size=500, data={"dsId": ds_id})
        recs = (res or {}).get("records") or []
        if not recs:
            break
        out.extend(recs)
        if len(recs) < 500:
            break
        page += 1
    return out


def _recycle_tags_by_ds(api, ds_id: int) -> list[dict]:
    """Recycle API has NO server-side dsId filter; paginate then client-filter."""
    from tpt_api.datahub import list_recycle_tags

    out: list[dict] = []
    page = 1
    while True:
        raw = list_recycle_tags(api, page=page, page_size=200)
        recs = ((raw or {}).get("tagInfoList") or {}).get("records") or []
        if not recs:
            break
        out.extend(r for r in recs if int(r.get("dsId", -1)) == int(ds_id))
        if len(recs) < 200:
            break
        page += 1
    return out


def _attempt_clean_delete(api, ds_id: int, name: str) -> str:
    """Return a status string describing what happened."""
    if not name.startswith(ALLOWED_CLEAN_PREFIXES):
        return "REFUSED: not a case-private datasource name"
    active = _active_tags_by_ds(api, ds_id)
    recycle = _recycle_tags_by_ds(api, ds_id)
    if active or recycle:
        return "TAG_DEPENDENCY: datasource has tags; not deleting"

    from tpt_api.datahub import change_ds_state, delete_ds_info

    try:
        change_ds_state(api, ds_id, False)
    except Exception:
        pass

    # Wait until not alive (best-effort, capped at 30s)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        row = _find_ds(api, ds_id=ds_id)
        if row is None or not row.get("alive"):
            break
        time.sleep(1.0)

    delete_ds_info(api, [ds_id])

    # Poll until id is gone (best-effort, capped at 15s)
    gone = False
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if _find_ds(api, ds_id=ds_id) is None:
            gone = True
            break
        time.sleep(1.0)
    return "DELETED" if gone else "DELETE_ATTEMPTED_BUT_STILL_PRESENT"


def _emit(result: dict, result_arg: str) -> None:
    out = json.dumps(result, ensure_ascii=False, indent=2)
    if result_arg == "-":
        print(out)
    else:
        out_path = Path(result_arg)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ds-id", type=int, help="Datasource id to diagnose.")
    parser.add_argument("--ds-name", help="Datasource name to diagnose.")
    parser.add_argument("--attempt-clean-delete", action="store_true",
                        help="If the DS name is case-private and has no tags, disable+delete it.")
    parser.add_argument("--result", default="-",
                        help="Path to write JSON result, or '-' for stdout.")
    args = parser.parse_args()

    base_url = os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.153:31501/")
    username = os.environ.get("DATAHUB_USER", "admin")
    password = os.environ.get("DATAHUB_PASSWORD", "")
    if not password:
        print("DATAHUB_PASSWORD is required", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    api = _login(base_url, username, password)
    ds = _find_ds(api, ds_id=args.ds_id, ds_name=args.ds_name)
    if ds is None:
        result = {
            "datasource": None,
            "error": "not found",
            "query": {"dsId": args.ds_id, "dsName": args.ds_name},
        }
        _emit(result, args.result)
        return 2

    ds_id = int(ds["id"])
    name = str(ds.get("dsName") or ds.get("name") or "")
    active = _active_tags_by_ds(api, ds_id)
    recycle = _recycle_tags_by_ds(api, ds_id)
    result = {
        "datasource": {
            "id": ds_id,
            "name": name,
            "enabled": bool(ds.get("dsStatus")),
            "alive": bool(ds.get("alive")),
            "endpoint": str(ds.get("dsTarUrl") or ""),
        },
        "activeTags": active,
        "recycleTags": recycle,
        "activeTagCount": len(active),
        "recycleTagCount": len(recycle),
    }
    if args.attempt_clean_delete:
        result["cleanDelete"] = _attempt_clean_delete(api, ds_id, name)

    _emit(result, args.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())