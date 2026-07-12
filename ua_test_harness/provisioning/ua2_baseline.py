"""Shared baseline datasource provisioning for UA-2.

Two shared datasources are provisioned once per batch on the TPT server:
  ua_shared_ua2_types_ds  -> ua2_types.yaml mock (port 18965)
  ua_shared_ua2_empty_ds  -> ua2_empty.yaml mock (port 18967)

Cases look them up by fixed name via require_shared_datasource(); they never
create or delete them. Provisioning never auto-deletes a config-mismatched
datasource -- that is a BLOCKED environment error.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

SHARED_TYPES_DS_NAME = "ua_shared_ua2_types_ds"
SHARED_EMPTY_DS_NAME = "ua_shared_ua2_empty_ds"


class BaselineError(Exception):
    """Baseline cannot be established; caller should map to BLOCKED."""


@dataclass
class Ua2Baseline:
    types_ds_id: int
    types_ds_name: str
    types_endpoint: str
    empty_ds_id: int
    empty_ds_name: str
    empty_endpoint: str


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _find_ds_by_name(api, name: str) -> dict[str, Any] | None:
    from tpt_api.datahub import list_ds_info
    page = list_ds_info(api, page=1, page_size=500, data={"dsName": name})
    for row in (page or {}).get("records") or []:
        if str(row.get("dsName") or row.get("name") or "") == name:
            return row
    return None


def _wait_ds_alive(ctx, ds_id: int, timeout: float) -> bool:
    from ua_test_harness.polling import wait_until
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        api = _api(ctx)
        row = None
        from tpt_api.datahub import list_ds_info
        p = list_ds_info(api, page=1, page_size=500, data={"id": ds_id})
        for r in (p or {}).get("records") or []:
            if int(r.get("id", -1)) == int(ds_id):
                row = r
        if row and row.get("alive"):
            return True
        time.sleep(1.0)
    return False


def _types_endpoint(ctx) -> str:
    ep = ctx.config.mock.endpoints.functional
    if not ep:
        raise BaselineError("functional mock endpoint (types) is empty")
    return ep


def _empty_endpoint(ctx) -> str:
    ep = os.environ.get("UA2_EMPTY_ENDPOINT", "").strip()
    if ep:
        return ep
    ip = getattr(ctx.config, "local_ip", "") or "127.0.0.1"
    return f"opc.tcp://{ip}:18967/ua_mocker/"


def _ensure_one(ctx, name: str, endpoint: str, *, must_be_empty: bool) -> dict[str, Any]:
    api = _api(ctx)
    row = _find_ds_by_name(api, name)
    if row is None:
        from tpt_api.datahub import add_ds_info, change_ds_state
        created = add_ds_info(api, ds_name=name, ds_tar_url=endpoint)
        ds_id = int(created.get("id") or 0)
        if not ds_id:
            raise BaselineError(f"created datasource {name!r} returned no id: {created!r}")
        change_ds_state(api, ds_id, True)
        if not _wait_ds_alive(ctx, ds_id, timeout=getattr(ctx.config.timeouts, "ds_connect_sec", 60)):
            raise BaselineError(f"datasource {name!r} did not become alive")
        row = {"id": ds_id, "dsName": name, "dsTarUrl": endpoint, "alive": True, "dsStatus": 1}
    else:
        actual_ep = str(row.get("dsTarUrl") or "")
        if actual_ep != endpoint:
            raise BaselineError(
                f"datasource {name!r} exists with endpoint {actual_ep!r}, expected {endpoint!r}; "
                "refusing to auto-delete a config-mismatched shared datasource"
            )
        ds_id = int(row.get("id"))
        if not row.get("alive"):
            from tpt_api.datahub import change_ds_state
            change_ds_state(api, ds_id, True)
            if not _wait_ds_alive(ctx, ds_id, timeout=getattr(ctx.config.timeouts, "ds_connect_sec", 60)):
                raise BaselineError(f"datasource {name!r} did not become alive after enable")
        row["alive"] = True
    if must_be_empty:
        _assert_no_tags(ctx, ds_id, name)
    return row


def _assert_no_tags(ctx, ds_id: int, name: str) -> None:
    from tpt_api.datahub import list_tags, list_recycle_tags
    api = _api(ctx)
    # active tags by dsId (server-side filter)
    active = (list_tags(api, page=1, page_size=500, data={"dsId": ds_id}) or {}).get("records") or []
    if active:
        raise BaselineError(f"shared empty datasource {name!r} has {len(active)} active tag(s); BLOCKED")
    # recycle: paginate (no server dsId filter), then client-filter by dsId
    all_recycle: list[dict] = []
    page = 1
    while True:
        raw = list_recycle_tags(api, page=page, page_size=200)
        info = (raw or {}).get("tagInfoList") or {}
        recs = info.get("records") or []
        if not recs:
            break
        all_recycle.extend(recs)
        if len(recs) < 200:
            break
        page += 1
    matching = [r for r in all_recycle if int(r.get("dsId", -1)) == int(ds_id)]
    if matching:
        raise BaselineError(f"shared empty datasource {name!r} has {len(matching)} recycle tag(s); BLOCKED")


def ensure_ua2_baseline(ctx) -> Ua2Baseline:
    from ua_test_harness.fixtures.environment import ensure_logged_in
    ensure_logged_in(ctx)
    types_ep = _types_endpoint(ctx)
    empty_ep = _empty_endpoint(ctx)
    types_row = _ensure_one(ctx, SHARED_TYPES_DS_NAME, types_ep, must_be_empty=False)
    empty_row = _ensure_one(ctx, SHARED_EMPTY_DS_NAME, empty_ep, must_be_empty=True)
    return Ua2Baseline(
        types_ds_id=int(types_row["id"]), types_ds_name=SHARED_TYPES_DS_NAME, types_endpoint=types_ep,
        empty_ds_id=int(empty_row["id"]), empty_ds_name=SHARED_EMPTY_DS_NAME, empty_endpoint=empty_ep,
    )


def require_shared_datasource(ctx, logical_name: str) -> dict[str, Any]:
    from ua_test_harness.fixtures.environment import ensure_logged_in
    ensure_logged_in(ctx)
    if logical_name == "types":
        name, endpoint = SHARED_TYPES_DS_NAME, _types_endpoint(ctx)
    elif logical_name == "empty":
        name, endpoint = SHARED_EMPTY_DS_NAME, _empty_endpoint(ctx)
    else:
        raise BaselineError(f"unknown shared datasource logical name: {logical_name!r}")
    api = _api(ctx)
    row = _find_ds_by_name(api, name)
    if row is None:
        raise BaselineError(f"shared datasource {name!r} not found; run baseline provisioning first")
    actual_ep = str(row.get("dsTarUrl") or "")
    if actual_ep != endpoint:
        raise BaselineError(f"shared datasource {name!r} endpoint {actual_ep!r} != expected {endpoint!r}")
    if not row.get("alive"):
        raise BaselineError(f"shared datasource {name!r} is not alive")
    return {"id": int(row["id"]), "name": name, "endpoint": actual_ep, "alive": True, "row": row}


def teardown_ua2_baseline(ctx, *, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise BaselineError("teardown_ua2_baseline requires confirm=True")
    from tpt_api.datahub import change_ds_state, delete_ds_info
    api = _api(ctx)
    result = {"deleted": []}
    for name in (SHARED_TYPES_DS_NAME, SHARED_EMPTY_DS_NAME):
        row = _find_ds_by_name(api, name)
        if row is None:
            continue
        ds_id = int(row["id"])
        try:
            change_ds_state(api, ds_id, False)
        except Exception:
            pass
        delete_ds_info(api, [ds_id])
        result["deleted"].append({"id": ds_id, "name": name})
    return result
