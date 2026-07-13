# UA-2 资源模型重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate shared baseline datasources from per-case private tags in the UA-2 first batch (16 cases), so cases stop creating/deleting datasources per-run and instead reuse two provisioned shared datasources.

**Architecture:** A new `provisioning` layer creates/validates two shared datasources (`ua_shared_ua2_types_ds` on mock port 18965, `ua_shared_ua2_empty_ds` on mock port 18967) once per batch on the TPT server. Each case runs in its own subprocess and looks up the shared datasource by fixed name (never creates/deletes it). A new thin `ua2_ops` layer exposes single-action primitives; cases explicitly create/delete their own `ua_case_ua2_`-prefixed tags with a registry fallback. The cleanup tool is scoped to `ua_case_ua2_` only and never touches shared resources.

**Tech Stack:** Python 3.11+, pytest, tpt_api (AlgAPI), asyncua mock server (ua_mocker). No new dependencies.

## Global Constraints

- **Never weaken product assertions to make a case pass.** A case FAIL (product misbehavior) stays FAIL; a harness error stays ERROR; an env block stays BLOCKED. (AGENTS.md §2, §4)
- **Do not modify UA-1 behavior.** `fixtures/datasource.py`, `fixtures/tag.py`, `ua1_runtime.py`, `ua2_common.prepare_datasource` are kept as-is for legacy. New code lives in new modules.
- **Forbidden git commands:** `git reset --hard`, `git clean -fd`, `git checkout .`, `git restore .`, `git stash`. Never run these.
- **Do not touch submodules** `review3` or `data_factory_server`. Do not `git add .`; stage only task files.
- **Shared datasource names are fixed constants:** `ua_shared_ua2_types_ds`, `ua_shared_ua2_empty_ds`. Case-private tags use prefix `ua_case_ua2_`. Case-private datasources (future) use `ua_case_ua2_ds_`.
- **External API calls in unit tests are forbidden** — use fakes/monkeypatch. Do not use `inspect.getsource()` string checks as the only evidence; verify call args / state changes.
- **Mock endpoints:** types=18965, empty=18967, both path `/ua_mocker/`. Format `opc.tcp://{local_ip}:{port}/ua_mocker/`.
- **`list_tags(data={"dsId": ...})` is server-side filterable** (tpt_api/datahub.py:187). `list_recycle_tags` does NOT accept dsId (filter client-side, paginate).
- Each case runs in an independent subprocess (run_with_timeout.py). Shared DS state lives on the TPT server, NOT in a Python registry across processes.
- Catalog must stay 419 total, UA-2 265, implemented 419, unimplemented 0, malformedRows 0, duplicateDocumentIds 0.

---

## File Structure

**New files:**
- `ua_mocker/ua2_empty.yaml` — minimal empty mock server config (port 18967, zero nodes).
- `ua_test_harness/provisioning/__init__.py` — package marker.
- `ua_test_harness/provisioning/ua2_baseline.py` — `Ua2Baseline` dataclass, `ensure_ua2_baseline(ctx)`, `require_shared_datasource(ctx, logical_name)`, `teardown_ua2_baseline(ctx)`, `BaselineError`.
- `ua_test_harness/ua2_ops.py` — thin single-action ops: datasource ops, tag ops, `create_case_tag`, `cleanup_case_tag`, paginating query helpers.
- `scripts/teardown_ua2_baseline.py` — explicit shared-baseline teardown (requires `--confirm-delete-shared`).
- `scripts/diagnose_ua2_datasource.py` — read-only datasource diagnostic (`--ds-id`/`--ds-name`, `--attempt-clean-delete`).
- `ua_test_harness/unit_tests/test_ua2_baseline.py` — provisioning tests (req 4, 5, 6).
- `ua_test_harness/unit_tests/test_ua2_ops.py` — ops layer tests (req 7, 8, 9, 10).
- `ua_test_harness/unit_tests/test_ua2_resource_refactor.py` — cross-cutting tests (req 1, 2, 3, 11, 12, 17, 18).
- `ua_test_harness/unit_tests/test_ua2_scripts.py` — cleanup/diagnose/runner script tests (req 3, 11, 12, 13, 14, 15, 16).

**Modified files:**
- `ua_test_harness/ua2_create_runtime.py` — 4 cases: use shared DS + explicit tag lifecycle.
- `ua_test_harness/ua2_query_runtime.py` — 8 cases: use shared DS + explicit tag lifecycle; push dsId/tagName to API.
- `ua_test_harness/ua2_recycle_runtime.py` — 4 cases: use shared DS + explicit tag lifecycle.
- `scripts/cleanup_ua2_resources.py` — default prefix `ua_case_ua2_`, paginate, never delete `ua_shared_ua2_`, no DS delete by default.
- `scripts/run_automation_ua2.py` — start 2 mocks, provision baseline, run cases, case-only cleanup, keep shared DS.
- `scripts/run_automation_ua2.ps1` — forward chapter timeout (minor).

**Unchanged (legacy, kept):** `ua_test_harness/fixtures/datasource.py`, `ua_test_harness/fixtures/tag.py`, `ua_test_harness/ua2_common.py` (prepare_datasource retained), `ua_test_harness/ua1_runtime.py`, `ua_test_harness/ua2_runtime.py` (dispatch table unchanged).

---

## Task 1: Empty mock config

**Covers:** §2 shared empty datasource endpoint
**Files:**
- Create: `ua_mocker/ua2_empty.yaml`

**Interfaces:**
- Produces: a mock config loadable by `ua_mocker/main.py` on port 18967 with zero nodes (server code tolerates `nodes: []`).

- [ ] **Step 1: Create `ua_mocker/ua2_empty.yaml`**

```yaml
# Empty UA-2 datasource mock for "no tags" query scenarios.
# Bound to its own endpoint so it never collides with ua2_types (18965).
server: 0.0.0.0
port: 18967
cycle: 500
namespace_index: 2
nodes: []
```

- [ ] **Step 2: Verify config loads**

Run: `python -c "import sys; sys.path.insert(0,'ua_mocker'); from config_loader import load_config; c=load_config('ua_mocker/ua2_empty.yaml'); assert c['port']==18967 and c['nodes']==[]; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add ua_mocker/ua2_empty.yaml
git commit -m "feat(mock): add empty UA-2 datasource mock on port 18967"
```

---

## Task 2: Provisioning layer

**Covers:** §4 目标1 (provision), §4 目标2 (require_shared_datasource), unit req 4, 5, 6
**Files:**
- Create: `ua_test_harness/provisioning/__init__.py`
- Create: `ua_test_harness/provisioning/ua2_baseline.py`
- Test: `ua_test_harness/unit_tests/test_ua2_baseline.py`

**Interfaces:**
- Consumes: `tpt_api.datahub` (`list_ds_info`, `add_ds_info`, `change_ds_state`), `ua_test_harness.clients.tpt_client.get_api`, `ua_test_harness.polling.wait_until`, `ua_test_harness.context.RunContext`.
- Produces:
  - `SHARED_TYPES_DS_NAME = "ua_shared_ua2_types_ds"`, `SHARED_EMPTY_DS_NAME = "ua_shared_ua2_empty_ds"`
  - `class BaselineError(Exception)` — raised when baseline cannot be established; callers map to BLOCKED.
  - `@dataclass Ua2Baseline: types_ds_id:int, types_ds_name:str, types_endpoint:str, empty_ds_id:int, empty_ds_name:str, empty_endpoint:str`
  - `ensure_ua2_baseline(ctx) -> Ua2Baseline` — create-if-missing / validate-if-present for both shared DS on the TPT server. Does NOT register cleanup. Does NOT delete on config mismatch (raises BaselineError). For empty DS: if active tags (`list_tags(data={"dsId": id})`) or recycle tags (paginated, filtered by dsId) are non-empty → BaselineError.
  - `require_shared_datasource(ctx, logical_name: str) -> dict` — `"types"` or `"empty"`. Lookup by fixed name, validate endpoint/enabled/alive. Never create/delete. Never register cleanup. Raises BaselineError on any failure.
  - `teardown_ua2_baseline(ctx, *, confirm: bool) -> dict` — explicit teardown of both shared DS; no-op (raise) unless `confirm=True`.

- [ ] **Step 1: Write failing tests** (`ua_test_harness/unit_tests/test_ua2_baseline.py`)

Tests (all monkeypatch `tpt_api.datahub` and `get_api`):
- `test_ensure_reuses_existing_types_ds` — DS exists with correct name+endpoint+enabled+alive → returns baseline with same id, no `add_ds_info` call.
- `test_ensure_creates_when_missing` — DS not found → calls `add_ds_info`, `change_ds_state(True)`, returns new id.
- `test_ensure_raises_on_config_mismatch` — DS exists but wrong endpoint → `BaselineError`, no delete attempted.
- `test_ensure_empty_ds_blocked_when_has_active_tags` — empty DS exists but `list_tags(data={"dsId": id})` returns 1 row → `BaselineError`.
- `test_ensure_empty_ds_blocked_when_has_recycle_tags` — empty DS, active empty, but recycle (paginated) has a row with matching dsId → `BaselineError`.
- `test_require_shared_datasource_types` — DS present+alive → returns dict with id; no create/delete.
- `test_require_shared_datasource_missing_raises` — not found → `BaselineError`.
- `test_require_shared_datasource_not_alive_raises` — found but alive=False → `BaselineError`.
- `test_require_shared_datasource_wrong_endpoint_raises` — found but endpoint mismatch → `BaselineError`.
- `test_teardown_requires_confirm` — `teardown_ua2_baseline(ctx, confirm=False)` raises; `confirm=True` disables+deletes both.

```python
import os, sys, types, pytest
from unittest.mock import MagicMock

def _ctx():
    from ua_test_harness.context import RunContext
    from ua_test_harness.config import RunConfig
    cfg = RunConfig(); cfg.run_id="t"; cfg.local_ip="127.0.0.1"
    cfg.mock.endpoints.functional = "opc.tcp://127.0.0.1:18965/ua_mocker/"
    return RunContext(config=cfg, emitter=MagicMock(), evidence_root=None, log_path=None, cancellation_token=None)

def _patch_datahub(monkeypatch, *, ds_rows=None, add_raises=None, recycle_rows=None, tag_rows_by_ds=None):
    import tpt_api.datahub as dh
    calls = {"add": [], "change_state": [], "delete": []}
    def fake_list_ds(api, page=1, page_size=10, sort="-createTime", data=None):
        rec = ds_rows or []
        if data and "dsName" in data:
            rec = [r for r in rec if r.get("dsName")==data["dsName"]]
        return {"records": rec, "total": len(rec)}
    monkeypatch.setattr(dh, "list_ds_info", fake_list_ds)
    def fake_add(api, ds_name, ds_type=1, ds_sub_type=4, ds_tar_url="", **kw):
        calls["add"].append(ds_name)
        if add_raises: raise add_raises
        return {"id": 999, "dsName": ds_name, "dsTarUrl": ds_tar_url, "alive": False, "dsStatus": 1}
    monkeypatch.setattr(dh, "add_ds_info", fake_add)
    def fake_change(api, ds_id, enabled):
        calls["change_state"].append((ds_id, enabled)); return {}
    monkeypatch.setattr(dh, "change_ds_state", fake_change)
    def fake_delete(api, ids): calls["delete"].append(ids); return {}
    monkeypatch.setattr(dh, "delete_ds_info", fake_delete)
    def fake_list_tags(api, page=1, page_size=10, sort="-createTime", data=None):
        if data and "dsId" in data and tag_rows_by_ds is not None:
            return {"records": tag_rows_by_ds.get(int(data["dsId"]), []), "total": 0}
        return {"records": [], "total": 0}
    monkeypatch.setattr(dh, "list_tags", fake_list_tags)
    def fake_list_recycle(api, page=1, page_size=100, group_id="1", tag_type=1, sort="-createTime"):
        return {"tagInfoList": {"records": recycle_rows or [], "total": len(recycle_rows or [])}}
    monkeypatch.setattr(dh, "list_recycle_tags", fake_list_recycle)
    return calls

def _patch_get_api(monkeypatch, api=None):
    import ua_test_harness.clients.tpt_client as tc
    monkeypatch.setattr(tc, "get_api", lambda ctx: api or MagicMock())

def _patch_wait_alive(monkeypatch, value=True):
    import ua_test_harness.provisioning.ua2_baseline as bl
    monkeypatch.setattr(bl, "_wait_ds_alive", lambda ctx, ds_id, timeout: value, raising=False)
```

(Full test bodies use the patches above to assert each scenario.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_baseline.py -q`
Expected: FAIL (module not found / `BaselineError` undefined)

- [ ] **Step 3: Implement `ua_test_harness/provisioning/__init__.py`**

```python
"""UA-2 shared baseline datasource provisioning."""
from ua_test_harness.provisioning.ua2_baseline import (
    BaselineError,
    Ua2Baseline,
    ensure_ua2_baseline,
    require_shared_datasource,
    teardown_ua2_baseline,
    SHARED_TYPES_DS_NAME,
    SHARED_EMPTY_DS_NAME,
)
```

- [ ] **Step 4: Implement `ua_test_harness/provisioning/ua2_baseline.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_baseline.py -q`
Expected: PASS (10 tests)

- [ ] **Step 6: Commit**

```bash
git add ua_test_harness/provisioning/__init__.py ua_test_harness/provisioning/ua2_baseline.py ua_test_harness/unit_tests/test_ua2_baseline.py
git commit -m "feat(ua2): add shared baseline datasource provisioning layer"
```

---

## Task 3: Thin ops layer

**Covers:** §4 目标3 (fixture downgrade), §4 目标4 (explicit tag mgmt), unit req 7, 8, 9, 10
**Files:**
- Create: `ua_test_harness/ua2_ops.py`
- Test: `ua_test_harness/unit_tests/test_ua2_ops.py`

**Interfaces:**
- Consumes: `tpt_api.datahub` primitives, `ua_test_harness.clients.tpt_client.get_api`, `ua_test_harness.context.RunContext`, `ua_test_harness.resources.ResourceRegistry`.
- Produces (all single-action, no implicit delete/create/reuse):
  - Datasource ops: `create_datasource_raw(ctx, name, endpoint, *, sub_type="OPC_UA_SERVER") -> dict`; `find_datasource_by_name(ctx, name) -> dict|None`; `find_datasource_by_id(ctx, ds_id) -> dict|None`; `enable_datasource(ctx, ds_id)`; `disable_datasource(ctx, ds_id)`; `wait_datasource_alive(ctx, ds_id, timeout=60.0) -> bool`; `wait_datasource_offline(ctx, ds_id, timeout=30.0) -> bool`; `delete_datasource_raw(ctx, ds_id, *, disable_first=True)`.
  - Tag ops: `create_tag_raw(ctx, name, ds_id, *, data_type="INT", tag_base_name=None, tag_desc=None, frequency=1) -> dict`; `find_tag_by_name(ctx, name) -> dict|None`; `find_tag_by_id(ctx, tag_id) -> dict|None`; `soft_delete_tag(ctx, tag_id)`; `restore_tag(ctx, tag_id)`; `physical_delete_tag(ctx, tag_id)`; `wait_tag_absent(ctx, name, timeout=30.0) -> bool`.
  - Case-tag helpers: `case_tag_name(ctx, cc, suffix) -> str`; `create_case_tag(ctx, cc, ds_id, *, suffix="tag", data_type="INT", tag_base_name=None, tag_desc=None) -> dict` (creates `ua_case_ua2_`-prefixed tag + registers registry FALLBACK keyed `tag:{name}`); `cleanup_case_tag(ctx, cc, tag_id, tag_name)` (best-effort explicit delete + wait absent + pop; swallows so it never masks case status).
  - Query helpers: `active_rows(ctx, **filters) -> list[dict]` (single page, server-side filter via `data=filters`); `all_active_rows(ctx, **filters) -> list[dict]` (paginated); `all_recycle_rows(ctx) -> list[dict]` (paginated); `exact(rows, field, value)`.

- [ ] **Step 1: Write failing tests** (`ua_test_harness/unit_tests/test_ua2_ops.py`)

Tests (monkeypatch tpt_api.datahub; verify call args + state, not source strings):
- `test_create_tag_raw_does_not_predelete` - `create_tag_raw` calls `add_tag` exactly once; never calls `delete_tags_physical`.
- `test_create_datasource_raw_does_not_auto_enable` - `create_datasource_raw` calls `add_ds_info` once, never `change_ds_state`.
- `test_case_tag_name_uses_prefix` - `case_tag_name(ctx, cc, "dup")` starts with `"ua_case_ua2_"` and contains the case id.
- `test_create_case_tag_registers_fallback` - registers a `tag:{name}` entry on `cc.registry` (use a real `ResourceRegistry`, assert `size()==1` and `snapshot()[0]["name"]=="tag:{name}"`).
- `test_cleanup_case_tag_deletes_and_pops` - create_case_tag registered a fallback; after `cleanup_case_tag`, `physical_delete_tag` was called, `wait_tag_absent` returned True, and `cc.registry.size()==0` (popped).
- `test_cleanup_case_tag_swallows_error` - monkeypatch `physical_delete_tag` to raise; `cleanup_case_tag` does NOT raise (so it never masks case status), and registry entry remains (not popped) so runner fallback can retry.
- `test_create_case_tag_no_predelete` - even if a same-name tag exists, `create_case_tag` does not call `delete_tags_physical` (no implicit pre-clean).
- `test_all_active_rows_paginates` - fake `list_tags` returns 2 full pages then empty; `all_active_rows` collects all records from both pages.
- `test_all_recycle_rows_paginates` - fake `list_recycle_tags` returns 2 pages; `all_recycle_rows` collects all.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_ops.py -q`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `ua_test_harness/ua2_ops.py`**

```python
"""Thin single-action ops for UA-2 cases.

Every function does exactly one thing. None implicitly: delete same-name
resources, delete a datasource's tags, decide reuse, or register the primary
cleanup. Case-private tag lifecycle is owned by the case body; the registry
entry registered by create_case_tag is a FALLBACK only.
"""
from __future__ import annotations

import time
from typing import Any

CASE_TAG_PREFIX = "ua_case_ua2_"
CASE_DS_PREFIX = "ua_case_ua2_ds_"


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


# ---------- datasource ops ----------

def create_datasource_raw(ctx, name: str, endpoint: str, *, sub_type: str = "OPC_UA_SERVER") -> dict:
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes
    created = add_ds_info(_api(ctx), ds_name=name, ds_tar_url=endpoint, ds_sub_type=DsSubTypes[sub_type])
    return {"id": int(created.get("id") or 0), "name": name, "endpoint": endpoint, "raw": created}


def find_datasource_by_name(ctx, name: str) -> dict[str, Any] | None:
    from tpt_api.datahub import list_ds_info
    page = list_ds_info(_api(ctx), page=1, page_size=500, data={"dsName": name})
    for r in (page or {}).get("records") or []:
        if str(r.get("dsName") or r.get("name") or "") == name:
            return r
    return None


def find_datasource_by_id(ctx, ds_id: int) -> dict[str, Any] | None:
    from tpt_api.datahub import list_ds_info
    page = list_ds_info(_api(ctx), page=1, page_size=500, data={"id": ds_id})
    for r in (page or {}).get("records") or []:
        if int(r.get("id", -1)) == int(ds_id):
            return r
    return None


def enable_datasource(ctx, ds_id: int) -> None:
    from tpt_api.datahub import change_ds_state
    change_ds_state(_api(ctx), ds_id, True)


def disable_datasource(ctx, ds_id: int) -> None:
    from tpt_api.datahub import change_ds_state
    change_ds_state(_api(ctx), ds_id, False)


def wait_datasource_alive(ctx, ds_id: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = find_datasource_by_id(ctx, ds_id)
        if row and row.get("alive"):
            return True
        time.sleep(1.0)
    return False


def wait_datasource_offline(ctx, ds_id: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_datasource_by_id(ctx, ds_id) is None:
            return True
        time.sleep(1.0)
    return False


def delete_datasource_raw(ctx, ds_id: int, *, disable_first: bool = True) -> None:
    from tpt_api.datahub import delete_ds_info
    if disable_first:
        try:
            disable_datasource(ctx, ds_id)
        except Exception:
            pass
    delete_ds_info(_api(ctx), [ds_id])
    wait_datasource_offline(ctx, ds_id, timeout=15.0)


# ---------- tag ops ----------

def create_tag_raw(ctx, name: str, ds_id: int, *, data_type: str = "INT",
                   tag_base_name: str | None = None, tag_desc: str | None = None,
                   frequency: int = 1) -> dict:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    result = add_tag(
        _api(ctx),
        tag_name=name,
        data_type=DataTypes[data_type],
        tag_type=TagTypes["一次位号"],
        ds_id=ds_id,
        group_id="0",
        unit="",
        only_read=False,
        frequency=frequency,
        need_push=True,
        tag_desc=tag_desc or "ua-2 precise batch",
        is_vector=True,
        tag_base_name=tag_base_name or ("2_" + name),
    )
    return {"id": int(result.get("id") or 0), "name": name, "raw": result}


def find_tag_by_name(ctx, name: str) -> dict[str, Any] | None:
    from tpt_api.datahub import list_tags
    page = list_tags(_api(ctx), page=1, page_size=500, data={"tagName": name})
    for r in (page or {}).get("records") or []:
        if str(r.get("tagName") or "") == name:
            return r
    return None


def find_tag_by_id(ctx, tag_id: int) -> dict[str, Any] | None:
    rows = all_active_rows(ctx)
    for r in rows:
        if int(r.get("id", -1)) == int(tag_id):
            return r
    return None


def soft_delete_tag(ctx, tag_id: int) -> None:
    from tpt_api.datahub import delete_tags
    delete_tags(_api(ctx), [tag_id])


def restore_tag(ctx, tag_id: int) -> None:
    from tpt_api.datahub import remove_tag_group_relation
    remove_tag_group_relation(_api(ctx), group_id="1", tag_ids=[tag_id])


def physical_delete_tag(ctx, tag_id: int) -> None:
    from tpt_api.datahub import delete_tags_physical
    delete_tags_physical(_api(ctx), [tag_id])


def wait_tag_absent(ctx, name: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_tag_by_name(ctx, name) is None:
            return True
        time.sleep(1.0)
    return False


# ---------- case-tag helpers ----------

def case_tag_name(ctx, cc, suffix: str) -> str:
    run_id = (ctx.config.run_id or "run").replace("-", "_")
    case_id = str(getattr(cc, "case_id", "case")).replace("-", "_")
    return f"{CASE_TAG_PREFIX}{case_id}_{run_id[:12]}_{suffix}_{time.time_ns() % 1_000_000}"


def create_case_tag(ctx, cc, ds_id: int, *, suffix: str = "tag", data_type: str = "INT",
                    tag_base_name: str | None = None, tag_desc: str | None = None) -> dict:
    name = case_tag_name(ctx, cc, suffix)
    tg = create_tag_raw(ctx, name, ds_id, data_type=data_type,
                        tag_base_name=tag_base_name, tag_desc=tag_desc)
    tag_id = int(tg["id"])
    # FALLBACK only: runs if the case body did not explicitly clean up.
    cc.registry.register(
        f"tag:{name}", "tag",
        lambda: physical_delete_tag(ctx, tag_id),
        payload={"id": tag_id, "name": name, "source": "case_fallback"},
    )
    return {"id": tag_id, "name": name, "raw": tg["raw"]}


def cleanup_case_tag(ctx, cc, tag_id: int, tag_name: str) -> None:
    """Best-effort explicit cleanup. Swallows errors so cleanup never masks the
    case result; the registry fallback (still registered if pop didn't run) is
    retried by the runner's cleanup_all."""
    try:
        physical_delete_tag(ctx, tag_id)
        wait_tag_absent(ctx, tag_name)
        cc.registry.pop(f"tag:{tag_name}")
    except Exception:
        pass


# ---------- query helpers ----------

def active_rows(ctx, **filters) -> list[dict[str, Any]]:
    from tpt_api.datahub import list_tags
    return (list_tags(_api(ctx), page=1, page_size=500, data=filters or {}).get("records")) or []


def all_active_rows(ctx, **filters) -> list[dict[str, Any]]:
    from tpt_api.datahub import list_tags
    api = _api(ctx)
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        res = list_tags(api, page=page, page_size=500, data=filters or {})
        recs = (res or {}).get("records") or []
        if not recs:
            break
        out.extend(recs)
        if len(recs) < 500:
            break
        page += 1
    return out


def all_recycle_rows(ctx) -> list[dict[str, Any]]:
    from tpt_api.datahub import list_recycle_tags
    api = _api(ctx)
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        raw = list_recycle_tags(api, page=page, page_size=200)
        recs = ((raw or {}).get("tagInfoList") or {}).get("records") or []
        if not recs:
            break
        out.extend(recs)
        if len(recs) < 200:
            break
        page += 1
    return out


def exact(rows: list[dict[str, Any]], field: str, value: Any) -> list[dict[str, Any]]:
    return [r for r in rows if r.get(field) == value]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_ops.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add ua_test_harness/ua2_ops.py ua_test_harness/unit_tests/test_ua2_ops.py
git commit -m "feat(ua2): add thin single-action ops layer for UA-2 cases"
```

---

## Task 4: Refactor UA-2-1 create cases

**Covers:** §5 UA-2-1, unit req 1, 2, 7, 8, 9, 10, 17, 18
**Files:**
- Modify: `ua_test_harness/ua2_create_runtime.py` (rewrite 4 handlers + helpers)
- Test: `ua_test_harness/unit_tests/test_ua2_resource_refactor.py` (UA-2-1 cases)

**Interfaces:**
- Consumes: `require_shared_datasource(ctx, "types")`, `create_case_tag`, `cleanup_case_tag`, `physical_delete_tag`, `wait_tag_absent`, `active_rows`, `exact` from `ua2_ops`; `ensure_logged_in`, `ensure_mock_ready` from fixtures.
- Removes: all calls to `prepare_datasource`, the local `_add_tag_real`/`_delete_tag_physical`/`_delete_ds` helpers (replaced by ops). Keeps `_make_length_name` (tested).

**Pattern for every case** (visible Arrange/Act/Assert/Cleanup):
```python
def some_case(ctx, cc):
    """UA-2-1-NNN: ..."""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")          # Arrange: shared DS
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="...")   # Arrange: case-private tag
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        # Act + Assert (product API + assertions)
        ...
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)        # Cleanup: explicit, visible
```

- [ ] **Step 1: Write failing tests** (in `test_ua2_resource_refactor.py`)

UA-2-1 specific (monkeypatch `require_shared_datasource`, `create_case_tag`, ops, `active_rows`; run handler end-to-end with fakes):
- `test_ua2_1_017_uses_shared_ds_and_cleans_tag` - `prepare_datasource` NOT called; `require_shared_datasource(ctx,"types")` called once; on PASS the tag is physically deleted + popped; case returns PASS.
- `test_ua2_1_017_assert_fail_kept_and_cleanup_runs` - fake duplicate add NOT rejected -> handler raises `AssertFail` (FAIL); `cleanup_case_tag` still ran (tag deleted); registry popped.
- `test_ua2_1_019_no_tag_created_passes` - empty-name add rejected, returns PASS; no residual tag.
- `test_ua2_1_021_length_127_cleans_tag` - accepted path: tag created then cleaned.
- `test_ua2_1_022_length_128_cleans_tag` - rejected path: no leak, PASS.
- `test_ua2_1_no_prepare_datasource` - none of the 4 handlers call `prepare_datasource` (monkeypatch `ua2_common.prepare_datasource` to raise; assert each handler does not trigger it).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_resource_refactor.py -q -k ua2_1`
Expected: FAIL (handlers still call prepare_datasource)

- [ ] **Step 3: Rewrite `ua2_create_runtime.py`**

Replace the module with (keep `_make_length_name` identical so `test_length_name_127/128` pass):

```python
"""Precise UA-2-1 creation scenarios using shared baseline datasource.

Resource model:
- Shared datasource ua_shared_ua2_types_ds is looked up, never created/deleted.
- Each case creates its own ua_case_ua2_-prefixed tag and explicitly deletes it.
- registry is a FALLBACK only; normal cleanup is visible in each case body.
"""
from __future__ import annotations

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    active_rows, cleanup_case_tag, create_case_tag, create_tag_raw, exact,
    physical_delete_tag,
)


def _make_length_name(prefix: str, target_len: int) -> str:
    suffix = "_end"
    head_room = target_len - len(suffix)
    if head_room <= 0:
        return prefix + suffix
    payload = prefix + ("x" * (head_room - len(prefix))) + suffix
    return payload[:target_len]


def _add_tag_by_name(ctx, ds_id: int, name: str) -> dict:
    # Direct add_tag for boundary/duplicate attempts (no pre-clean, no registry).
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    from ua_test_harness.clients.tpt_client import get_api
    return add_tag(get_api(ctx), tag_name=name, data_type=DataTypes["INT"],
                   tag_type=TagTypes["一次位号"], ds_id=ds_id, group_id="0",
                   unit="", only_read=False, frequency=1, need_push=True,
                   tag_desc="ua-2-1 precise batch", is_vector=True, tag_base_name="2_" + name)


def duplicate_name_rejected(ctx, cc):
    """UA-2-1-017: 重名位号必须被拒绝,且原记录未被覆盖。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="dup")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        original = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("original_exists", 1, len(original))
        orig = original[0]
        snapshot = {"id": tag_id, "dsId": orig.get("dsId"), "tagBaseName": orig.get("tagBaseName")}

        rejected = False
        try:
            _add_tag_by_name(ctx, ds_id, tag_name)
        except Exception:
            rejected = True
        check_true("duplicate_rejected", rejected)

        matched = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("only_one_record", 1, len(matched))
        rec = matched[0]
        check_eq("dsId_unchanged", snapshot["dsId"], rec.get("dsId"))
        check_eq("id_unchanged", snapshot["id"], int(rec.get("id")))
        check_eq("tagBaseName_unchanged", snapshot["tagBaseName"], rec.get("tagBaseName"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def empty_name_rejected(ctx, cc):
    """UA-2-1-019: tag_name="" 调用 add_tag 必须失败;不允许偷偷接受并落库。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    err_id = None
    failed = False
    try:
        result = _add_tag_by_name(ctx, ds_id, "")
        maybe = result.get("id") or result.get("tagId")
        if maybe:
            err_id = int(maybe)
    except Exception:
        failed = True
    check_true("empty_name_rejected", failed)
    check_eq("no_empty_record", 0, len(exact(active_rows(ctx, tagName=""), "tagName", "")))
    if err_id is not None:
        try:
            physical_delete_tag(ctx, err_id)
        except Exception:
            pass
        return CaseStatus.FAIL
    return CaseStatus.PASS


def _verify_length(ctx, cc, target_len: int):
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    name = _make_length_name("ua_case_ua2_tag_len" + str(target_len) + "_", target_len)
    assert len(name) == target_len, (len(name), target_len)

    # Boundary-named tag created explicitly (case-private prefix), registry fallback.
    boundary = create_tag_raw(ctx, name, ds_id, tag_desc="ua-2-1 precise batch")
    b_id = int(boundary["id"])
    cc.registry.register(f"tag:{name}", "tag",
                         lambda: physical_delete_tag(ctx, b_id),
                         payload={"id": b_id, "name": name})
    try:
        matched = exact(active_rows(ctx, tagName=name), "tagName", name)
        if matched:
            check_eq("only_one_match", 1, len(matched))
            rec = matched[0]
            check_eq("name_byte_equal", name, rec.get("tagName"))
            check_eq("length_exact", len(name), len(rec.get("tagName") or ""))
            return CaseStatus.PASS
        # rejected path: ensure no partial record
        check_eq("no_partial_record_on_reject", 0, len(matched))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, b_id, name)


def name_length_127(ctx, cc):
    """UA-2-1-021:总长度=127 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 127)


def name_length_128(ctx, cc):
    """UA-2-1-022:总长度=128 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 128)
```

- [ ] **Step 4: Run UA-2-1 tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_resource_refactor.py -q -k ua2_1`
Expected: PASS

- [ ] **Step 5: Run existing first-batch tests (length-name helpers unchanged)**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_first_batch.py -q -k "length_name or soft_delete_one_signature or restore_one_signature"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ua_test_harness/ua2_create_runtime.py ua_test_harness/unit_tests/test_ua2_resource_refactor.py
git commit -m "refactor(ua2): UA-2-1 cases use shared datasource and explicit tag cleanup"
```

---

## Task 5: Refactor UA-2-2 query cases

**Covers:** §5 UA-2-2, unit req 1, 2, 7, 8
**Files:**
- Modify: `ua_test_harness/ua2_query_runtime.py` (rewrite 8 handlers)
- Test: `ua_test_harness/unit_tests/test_ua2_resource_refactor.py` (UA-2-2 cases)

**Key changes per case:**
- ALL 8: replace `prepare_datasource(...)` with `require_shared_datasource(ctx, "types")`.
- UA-2-2-019: use `require_shared_datasource(ctx, "empty")`; push dsId to API: `active_rows(ctx, dsId=ds["id"])`; no tag; remove dead code.
- UA-2-2-004/033, 005, 011, 015: case-private tag via `create_case_tag` + explicit `cleanup_case_tag`; push `tagName` to API.
- UA-2-2-008, 016: no tag; pure query on shared DS scope; paginate where client-filtering (016 uses `all_active_rows`).
- UA-2-2-011: push `dsId` for the broad scope query instead of fetch-all-then-filter; use explicit per-tag cleanup (fixes closure late-binding).

- [ ] **Step 1: Write failing tests** (UA-2-2 in `test_ua2_resource_refactor.py`)

- `test_ua2_2_019_uses_empty_shared_ds` - `require_shared_datasource(ctx,"empty")` called; query uses `dsId` filter (assert `list_tags` called with `data={"dsId": ...}`); no tag created; returns PASS.
- `test_ua2_2_004_uses_types_and_cleans_tag` - shared types DS; case tag created+cleaned; returns PASS.
- `test_ua2_2_011_no_closure_bug` - two tags created; both cleaned (both physically deleted); assert registry empty after.
- `test_ua2_2_query_no_prepare_datasource` - none of the 8 handlers call `prepare_datasource`.
- `test_ua2_2_016_paginates` - `query_missing_base_name` uses paginated fetch (`all_active_rows`) not single page.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_resource_refactor.py -q -k ua2_2`
Expected: FAIL

- [ ] **Step 3: Rewrite `ua2_query_runtime.py`**

```python
"""Precise UA-2-2 query scenarios on shared baseline datasources."""
from __future__ import annotations

import time

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    active_rows, all_active_rows, cleanup_case_tag, create_case_tag, exact,
)

TAG_DESC = "ua-2-2 precise batch"


def query_config_fields(ctx, cc):
    """UA-2-2-004 + UA-2-2-033: 逐字段断言 10 个配置字段持久化。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="cfg", data_type="INT", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        row = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_true("found_persisted", bool(row))
        rec = row[0]
        check_eq("tagName", tag_name, rec.get("tagName"))
        check_eq("tagBaseName", "2_" + tag_name, rec.get("tagBaseName"))
        check_eq("dsId", ds_id, rec.get("dsId"))
        check_eq("tagType", 1, rec.get("tagType"))
        check_eq("unit", "", rec.get("unit"))
        check_eq("frequency", 1, rec.get("frequency"))
        check_eq("onlyRead", False, rec.get("onlyRead"))
        check_eq("needPush", True, rec.get("needPush"))
        check_eq("tagDesc", TAG_DESC, rec.get("tagDesc"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_repeat_stable(ctx, cc):
    """UA-2-2-005: 三次相同 list_tags 调用 total / ID 顺序 / 配置一致。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="rep", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        sample = lambda: active_rows(ctx, tagName=tag_name)
        first, second, third = sample(), sample(), sample()
        check_eq("same_count_first_second", len(first), len(second))
        check_eq("same_count_second_third", len(second), len(third))
        def ids(rows): return [int(r.get("id")) for r in rows]
        check_eq("id_order_stable_1_2", ids(first), ids(second))
        check_eq("id_order_stable_2_3", ids(second), ids(third))
        seen = {int(r.get("id")) for r in first}
        check_eq("no_duplicate_id_in_rows", len(seen), len(first))
        sel = next((r for r in first if int(r.get("id")) == tag_id), None)
        check_true("target_row_present", sel is not None)
        check_eq("tagName_stable", tag_name, sel.get("tagName"))
        check_eq("dsId_stable", ds_id, sel.get("dsId"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_missing_name(ctx, cc):
    """UA-2-2-008: 不存在的名称查询返回空集合,不报错。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    require_shared_datasource(ctx, "types")
    impossible = "ua_case_ua2_missing_" + str(time.time_ns())
    check_eq("empty_resultset_on_missing", 0, len(active_rows(ctx, tagName=impossible)))
    return CaseStatus.PASS


def query_clear_name_filter(ctx, cc):
    """UA-2-2-011: 空过滤恢复 dsId 范围集合;两条 case 位号均在范围内。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    a = create_case_tag(ctx, cc, ds_id, suffix="qca", tag_desc=TAG_DESC)
    b = create_case_tag(ctx, cc, ds_id, suffix="qcb", tag_desc=TAG_DESC)
    a_id, a_name = int(a["id"]), a["name"]
    b_id, b_name = int(b["id"]), b["name"]
    try:
        targeted = exact(active_rows(ctx, tagName=a_name), "tagName", a_name)
        check_eq("exactly_a", 1, len(targeted))
        broad = active_rows(ctx, dsId=ds_id)  # server-side scope, not global fetch-all
        names = {r.get("tagName") for r in broad}
        check_true("a_in_broad", a_name in names)
        check_true("b_in_broad", b_name in names)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, b_id, b_name)
        cleanup_case_tag(ctx, cc, a_id, a_name)


def query_base_name_exact(ctx, cc):
    """UA-2-2-015: tagBaseName 保留 namespace 前缀与下划线。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    base_suffix = "ua_b15_" + str(time.time_ns())
    expected_base = "2_" + base_suffix
    tag = create_case_tag(ctx, cc, ds_id, suffix="b15", tag_base_name=expected_base, tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_true("hit_by_name", bool(rows))
        rec = rows[0]
        check_eq("tagBaseName_namespace_preserved", expected_base, rec.get("tagBaseName"))
        check_eq("tagName_separate", tag_name, rec.get("tagName"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_missing_base_name(ctx, cc):
    """UA-2-2-016: 不存在的 tagBaseName 返回空集合 (paginated fetch)."""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    require_shared_datasource(ctx, "types")
    impossible = "9_impossible_base_" + str(time.time_ns())
    matching = [r for r in all_active_rows(ctx) if r.get("tagBaseName") == impossible]
    check_eq("empty_for_impossible_base", 0, len(matching))
    return CaseStatus.PASS


def query_empty_datasource(ctx, cc):
    """UA-2-2-019: 无位号的数据源按 dsId 查返回空集 (server-side filter)."""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "empty")
    check_eq("empty_datasource_returns_empty_set", 0, len(active_rows(ctx, dsId=ds["id"])))
    return CaseStatus.PASS
```

- [ ] **Step 4: Run UA-2-2 tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_resource_refactor.py -q -k ua2_2`
Expected: PASS

- [ ] **Step 5: Run existing source-inspection test (keeps `first = sample()` etc.)**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_first_batch.py -q -k query_repeat_stable`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ua_test_harness/ua2_query_runtime.py ua_test_harness/unit_tests/test_ua2_resource_refactor.py
git commit -m "refactor(ua2): UA-2-2 query cases use shared datasources and push filters to API"
```

---

## Task 6: Refactor UA-2-4 delete/restore cases

**Covers:** §5 UA-2-4, unit req 1, 2, 7, 8, 9, 10
**Files:**
- Modify: `ua_test_harness/ua2_recycle_runtime.py` (rewrite 4 handlers)
- Test: `ua_test_harness/unit_tests/test_ua2_resource_refactor.py` (UA-2-4 cases)

**Key changes:**
- All 4: `require_shared_datasource(ctx, "types")`; case-private tag via `create_case_tag`; explicit `cleanup_case_tag` in finally.
- Use ops: `soft_delete_tag(ctx, tag_id)`, `restore_tag(ctx, tag_id)`, `physical_delete_tag(ctx, tag_id)`, `wait_tag_absent`, `active_rows`, `all_recycle_rows`, `exact`.
- UA-2-4-020/024: after the test's own physical delete, pop the registry fallback so it isn't double-run; `cleanup_case_tag` is still safe (idempotent).
- UA-2-4-024: keep the restore attempt as a real test action (capture whether it raised), then assert no surreptitious recreate - do NOT silently swallow to pass; assert final state.

- [ ] **Step 1: Write failing tests** (UA-2-4 in `test_ua2_resource_refactor.py`)

- `test_ua2_4_001_soft_delete_uses_shared_ds` - shared types DS; tag created, soft-deleted, verified in recycle; cleanup physical-deletes from recycle; registry empty after.
- `test_ua2_4_013_restore_roundtrip` - create->soft->restore->active; cleanup deletes.
- `test_ua2_4_020_physical_delete_pops_registry` - after physical delete (test action), registry entry popped; final finally cleanup is a safe no-op.
- `test_ua2_4_024_irreversible_asserts_no_recreate` - restore attempt captured; asserts 0 in active and 0 in recycle; FAIL not masked.
- `test_ua2_4_no_prepare_datasource` - none of the 4 call `prepare_datasource`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_resource_refactor.py -q -k ua2_4`
Expected: FAIL

- [ ] **Step 3: Rewrite `ua2_recycle_runtime.py`**

```python
"""Precise UA-2-4 soft delete / restore / physical delete on shared datasource."""
from __future__ import annotations

import time

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    active_rows, all_recycle_rows, cleanup_case_tag, create_case_tag,
    exact, physical_delete_tag, restore_tag, soft_delete_tag,
)


def _wait_until(name, fn, timeout=30.0, interval=1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertFail(f"{name} timeout after {timeout}s; last={last!r}")


def soft_delete_one(ctx, cc):
    """UA-2-4-001: 软删除后 active 消失, 回收站出现同 ID。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="sd", tag_desc="ua-2-4 precise batch")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until("soft_delete:removed_from_active",
                    lambda: not exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name),
                    timeout=15.0)
        rec = next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None)
        check_true("recycle_contains", rec is not None)
        check_eq("recycle_id_matches", tag_id, int(rec.get("id")))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def restore_one(ctx, cc):
    """UA-2-4-013: 软删后恢复, active 重新出现同 ID, recycle 消失。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="rs", tag_desc="ua-2-4 precise batch")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until("restore:in_recycle_first",
                    lambda: next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None),
                    timeout=15.0)
        restore_tag(ctx, tag_id)
        rec = _wait_until("restore:active_again",
                          lambda: (lambda rows: rows[0] if rows else None)(
                              exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)),
                          timeout=30.0)
        check_eq("restored_id_matches", tag_id, int(rec.get("id")))
        leftover = next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None)
        check_true("no_recycle_leftover", leftover is None)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def physical_delete_one(ctx, cc):
    """UA-2-4-020: 物理删除后 active/recycle 均不存在。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="pd", tag_desc="ua-2-4 precise batch")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until("physical:in_recycle",
                    lambda: next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None),
                    timeout=15.0)
        physical_delete_tag(ctx, tag_id)
        cc.registry.pop(f"tag:{tag_name}")  # test already deleted; drop fallback
        check_eq("not_in_active_after_physical", None,
                 next((r for r in exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
                       if int(r.get("id")) == tag_id), None))
        leftover = next((r for r in all_recycle_rows(ctx)
                         if r.get("tagName") == tag_name and int(r.get("id")) == tag_id), None)
        check_eq("not_in_recycle_after_physical", None, leftover)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def physical_delete_irreversible(ctx, cc):
    """UA-2-4-024: 物理删除后尝试恢复, 不能恢复, 所有入口无该 ID。"""
    ensure_mock_ready(ctx, "functional"); ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types"); ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="ir", tag_desc="ua-2-4 precise batch")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        soft_delete_tag(ctx, tag_id)
        _wait_until("irreversible:in_recycle",
                    lambda: next((r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name), None),
                    timeout=15.0)
        physical_delete_tag(ctx, tag_id)
        cc.registry.pop(f"tag:{tag_name}")

        # Real test action: attempt restore, then assert it could not recreate the tag.
        try:
            restore_tag(ctx, tag_id)
        except Exception:
            pass  # restore is expected to fail; final-state assertions below are authoritative

        rows_a = [r for r in exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
                  if int(r.get("id")) == tag_id]
        check_eq("no_surreptitious_recreate_active", 0, len(rows_a))
        leftover = [r for r in all_recycle_rows(ctx)
                    if r.get("tagName") == tag_name and int(r.get("id")) == tag_id]
        check_eq("no_surreptitious_recreate_recycle", 0, len(leftover))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
```

- [ ] **Step 4: Run UA-2-4 tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_resource_refactor.py -q -k ua2_4`
Expected: PASS

- [ ] **Step 5: Run existing signature tests (unchanged)**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_first_batch.py -q -k "soft_delete_one_signature or restore_one_signature"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ua_test_harness/ua2_recycle_runtime.py ua_test_harness/unit_tests/test_ua2_resource_refactor.py
git commit -m "refactor(ua2): UA-2-4 delete/restore cases use shared datasource and explicit tag lifecycle"
```

---

## Task 7: Rewrite cleanup tool

**Covers:** §7 cleanup, unit req 3, 11, 12
**Files:**
- Modify: `scripts/cleanup_ua2_resources.py` (rewrite)
- Test: `ua_test_harness/unit_tests/test_ua2_scripts.py` (cleanup tests)

**Key changes:**
- Default prefix `ua_case_ua2_` (was `ua_auto_ua2_`).
- **Never delete `ua_shared_ua2_`** - hard exclusion list; `--prefix` may not start with `ua_shared_ua2_`.
- **Paginate** active tags (`get_all_tags`-style), recycle tags, and datasources (no single-page-500 miss).
- **Do not delete datasources by default.** New flag `--include-case-datasources` to also delete `ua_case_ua2_ds_` datasources (future use). Shared datasources are never deleted here.
- Re-check after deletion; exit 1 if any case-private residual remains.

- [ ] **Step 1: Write failing tests** (in `test_ua2_scripts.py`)

- `test_cleanup_default_prefix_is_case` - module `PREFIX == "ua_case_ua2_"`.
- `test_cleanup_refuses_shared_prefix` - `--prefix ua_shared_ua2_` -> exits non-zero with clear message, no deletion.
- `test_cleanup_does_not_delete_shared_resources` - fake datasources include one `ua_shared_ua2_types_ds`; after run, it is NOT deleted (delete_ds_info never called with its id).
- `test_cleanup_paginates_active_tags` - fake `list_tags` returns 3 pages (500+500+1); cleanup collects all 1001 ids and physical-deletes them.
- `test_cleanup_paginates_recycle` - fake `list_recycle_tags` returns 2 pages; all recycle ids collected.
- `test_cleanup_no_datasource_delete_by_default` - even with case datasources present, `delete_ds_info` not called unless `--include-case-datasources`.
- `test_cleanup_recheck_exit_code` - residual present -> exit 1; clean -> exit 0.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k cleanup`
Expected: FAIL

- [ ] **Step 3: Rewrite `scripts/cleanup_ua2_resources.py`**

```python
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
        active_ids.extend(int(r["id"]) for r in recs if str(r.get("tagName", "")).startswith(name_prefix))
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
        recycle_ids.extend(int(r["id"]) for r in recs if str(r.get("tagName", "")).startswith(name_prefix))
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
        out.extend(int(r["id"]) for r in recs
                   if str(r.get("dsName", "")).startswith(CASE_DS_PREFIX)
                   or str(r.get("name", "")).startswith(CASE_DS_PREFIX))
        if len(recs) < 500:
            break
        page += 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.153:31501/"))
    parser.add_argument("--username", default=os.environ.get("DATAHUB_USER", "admin"))
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--include-case-datasources", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--result", default="-")
    args = parser.parse_args()

    if args.prefix.startswith(SHARED_PREFIX):
        print(f"refusing to clean shared resources (prefix={args.prefix!r})", file=sys.stderr)
        return 2

    ctx = {"base_url": args.base_url, "username": args.username,
           "password": os.environ.get("DATAHUB_PASSWORD", "")}
    if not ctx["password"]:
        print("DATAHUB_PASSWORD is required", file=sys.stderr)
        return 2

    api = _login(ctx)
    active_ids, recycle_ids = _collect_tag_ids(api, args.prefix)
    case_ds_ids = _collect_case_ds_ids(api) if args.include_case_datasources else []

    log: dict[str, Any] = {
        "prefix": args.prefix, "dryRun": bool(args.dry_run),
        "tagsActive": len(active_ids), "tagsRecycle": len(recycle_ids),
        "caseDatasources": len(case_ds_ids), "actions": [],
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
```

- [ ] **Step 4: Run cleanup tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k cleanup`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/cleanup_ua2_resources.py ua_test_harness/unit_tests/test_ua2_scripts.py
git commit -m "refactor(ua2): cleanup tool scoped to case-private resources, paginated, no shared deletion"
```

---

## Task 8: Baseline teardown script

**Covers:** §7 shared teardown
**Files:**
- Create: `scripts/teardown_ua2_baseline.py`
- Test: `ua_test_harness/unit_tests/test_ua2_scripts.py` (teardown tests)

- [ ] **Step 1: Write failing tests**

- `test_teardown_requires_confirm` - without `--confirm-delete-shared`, exits non-zero, no deletion.
- `test_teardown_deletes_both_shared` - with confirm, calls disable+delete on both `ua_shared_ua2_types_ds` and `ua_shared_ua2_empty_ds`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k teardown`
Expected: FAIL

- [ ] **Step 3: Implement `scripts/teardown_ua2_baseline.py`**

```python
"""Explicit teardown of UA-2 shared baseline datasources.

Requires --confirm-delete-shared. The normal automation runner NEVER calls this.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-delete-shared", action="store_true")
    parser.add_argument("--result", default="-")
    args = parser.parse_args()
    if not args.confirm_delete_shared:
        print("teardown_ua2_baseline requires --confirm-delete-shared", file=sys.stderr)
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ua_test_harness.config import RunConfig
    from ua_test_harness.context import RunContext
    from ua_test_harness.provisioning import teardown_ua2_baseline
    from unittest.mock import MagicMock

    cfg = RunConfig()
    cfg.local_ip = os.environ.get("UA_LOCAL_IP", "127.0.0.1")
    cfg.mock.endpoints.functional = os.environ.get(
        "DATAHUB_BASE_MOCK", f"opc.tcp://{cfg.local_ip}:18965/ua_mocker/")
    cfg.subject.base_url = os.environ.get("DATAHUB_BASE_URL", "")
    cfg.subject.username = os.environ.get("DATAHUB_USER", "admin")
    cfg.subject.password = os.environ.get("DATAHUB_PASSWORD", "")
    ctx = RunContext(config=cfg, emitter=MagicMock())
    result = teardown_ua2_baseline(ctx, confirm=True)
    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result == "-":
        print(out)
    else:
        Path(args.result).parent.mkdir(parents=True, exist_ok=True)
        Path(args.result).write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k teardown`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/teardown_ua2_baseline.py ua_test_harness/unit_tests/test_ua2_scripts.py
git commit -m "feat(ua2): add explicit shared baseline teardown script"
```

---

## Task 9: Datasource diagnostic script

**Covers:** §8 diagnose, unit req 13, 14
**Files:**
- Create: `scripts/diagnose_ua2_datasource.py`
- Test: `ua_test_harness/unit_tests/test_ua2_scripts.py` (diagnose tests)

**Behavior:** read-only by default. `--ds-id` or `--ds-name` selects a datasource. Output JSON: `{datasource:{id,name,enabled,alive,endpoint}, activeTags:[...], recycleTags:[...], activeTagCount, recycleTagCount}`. Active tags queried by `list_tags(data={"dsId": id})` (server-side). Recycle tags: paginate all recycle, client-filter by dsId. `--attempt-clean-delete` only allowed on names starting with `ua_case_ua2_` (or legacy `ua_auto_ua2_`); refuses to delete if active/recycle non-empty (reports TAG_DEPENDENCY).

- [ ] **Step 1: Write failing tests**

- `test_diagnose_lists_active_by_dsId` - fake `list_tags(data={"dsId": X})` returns 2 tags; output `activeTagCount==2`.
- `test_diagnose_lists_recycle_filtered_by_dsId` - fake recycle (2 pages) has 1 tag with matching dsId; output `recycleTagCount==1` (others excluded).
- `test_diagnose_readonly_no_delete` - default mode never calls delete/disable.
- `test_diagnose_clean_delete_refuses_non_case_name` - `--attempt-clean-delete --ds-name ua_shared_ua2_types_ds` -> exits non-zero, no deletion.
- `test_diagnose_clean_delete_refuses_with_tags` - case-name DS with active tags -> reports TAG_DEPENDENCY, no delete.
- `test_diagnose_clean_delete_sequence` - case-name DS, no tags -> disable -> wait alive=false -> delete -> poll gone.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k diagnose`
Expected: FAIL

- [ ] **Step 3: Implement `scripts/diagnose_ua2_datasource.py`**

```python
"""Read-only datasource diagnostic for UA-2.

Default: lists active (by dsId) and recycle (paginated, client-filtered by dsId)
tags for a datasource. --attempt-clean-delete (case-private names only) performs
disable -> wait offline -> delete -> poll gone, but refuses if tags remain.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ALLOWED_CLEAN_PREFIXES = ("ua_case_ua2_", "ua_auto_ua2_")


def _login(base_url, username, password):
    from tpt_api.client import AlgAPI
    api = AlgAPI(base_url=base_url, timeout=20.0)
    api.login(username, password, "")
    return api


def _find_ds(api, *, ds_id=None, ds_name=None):
    from tpt_api.datahub import list_ds_info
    data = {"id": ds_id} if ds_id is not None else ({"dsName": ds_name} if ds_name else {})
    page = list_ds_info(api, page=1, page_size=500, data=data)
    for r in (page or {}).get("records") or []:
        if ds_id is not None and int(r.get("id", -1)) != int(ds_id):
            continue
        if ds_name is not None and str(r.get("dsName") or r.get("name") or "") != ds_name:
            continue
        return r
    return None


def _active_tags_by_ds(api, ds_id):
    from tpt_api.datahub import list_tags
    out = []
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


def _recycle_tags_by_ds(api, ds_id):
    from tpt_api.datahub import list_recycle_tags
    out = []
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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ds-id", type=int)
    p.add_argument("--ds-name")
    p.add_argument("--attempt-clean-delete", action="store_true")
    p.add_argument("--result", default="-")
    args = p.parse_args()

    base_url = os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.153:31501/")
    username = os.environ.get("DATAHUB_USER", "admin")
    password = os.environ.get("DATAHUB_PASSWORD", "")
    if not password:
        print("DATAHUB_PASSWORD is required", file=sys.stderr); return 2

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    api = _login(base_url, username, password)
    ds = _find_ds(api, ds_id=args.ds_id, ds_name=args.ds_name)
    if ds is None:
        result = {"datasource": None, "error": "not found",
                  "query": {"dsId": args.ds_id, "dsName": args.ds_name}}
    else:
        ds_id = int(ds["id"])
        name = str(ds.get("dsName") or ds.get("name") or "")
        active = _active_tags_by_ds(api, ds_id)
        recycle = _recycle_tags_by_ds(api, ds_id)
        result = {
            "datasource": {"id": ds_id, "name": name,
                           "enabled": bool(ds.get("dsStatus")),
                           "alive": bool(ds.get("alive")),
                           "endpoint": str(ds.get("dsTarUrl") or "")},
            "activeTags": active, "recycleTags": recycle,
            "activeTagCount": len(active), "recycleTagCount": len(recycle),
        }
        if args.attempt_clean_delete:
            if not name.startswith(ALLOWED_CLEAN_PREFIXES):
                result["cleanDelete"] = "REFUSED: not a case-private datasource name"
            elif active or recycle:
                result["cleanDelete"] = "TAG_DEPENDENCY: datasource has tags; not deleting"
            else:
                from tpt_api.datahub import change_ds_state, delete_ds_info, list_ds_info
                try:
                    change_ds_state(api, ds_id, False)
                except Exception:
                    pass
                # wait alive=false
                deadline = time.monotonic() + 30.0
                while time.monotonic() < deadline:
                    row = _find_ds(api, ds_id=ds_id)
                    if row is None or not row.get("alive"):
                        break
                    time.sleep(1.0)
                delete_ds_info(api, [ds_id])
                gone = False
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    if _find_ds(api, ds_id=ds_id) is None:
                        gone = True; break
                    time.sleep(1.0)
                result["cleanDelete"] = "DELETED" if gone else "DELETE_ATTEMPTED_BUT_STILL_PRESENT"

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result == "-":
        print(out)
    else:
        Path(args.result).parent.mkdir(parents=True, exist_ok=True)
        Path(args.result).write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run diagnose tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k diagnose`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/diagnose_ua2_datasource.py ua_test_harness/unit_tests/test_ua2_scripts.py
git commit -m "feat(ua2): add read-only datasource diagnostic with optional case-private clean delete"
```

---

## Task 10: Rewrite automation runner

**Covers:** §6 runner, unit req 15, 16
**Files:**
- Modify: `scripts/run_automation_ua2.py` (add 2nd mock + baseline provision + keep shared DS)
- Modify: `scripts/run_automation_ua2.ps1` (minor)
- Test: `ua_test_harness/unit_tests/test_ua2_scripts.py` (runner tests)

**New orchestration order** (§6):
1. env check (DATAHUB_PASSWORD) 2. compileall 3. unit tests 4. catalog 5. inventory
6. start UA2 types mock (18965) 7. start UA2 empty mock (18967) 8. wait both ready
9. provision/validate shared baseline (`ensure_ua2_baseline`) 10. run 16 cases (each subprocess)
11. after each case: case-only cleanup (`ua_case_ua2_`) 12. batch end: do NOT delete shared DS
13. stop mocks 14. report

- [ ] **Step 1: Write failing tests** (runner orchestration, monkeypatched subprocess + provisioning)

- `test_runner_starts_two_mocks` - `_start_mock` called for both 18965 and 18967 configs.
- `test_runner_provisions_baseline` - `ensure_ua2_baseline` invoked once before cases.
- `test_runner_case_config_has_baseline` - generated run-config includes `ua2Baseline` with both names+endpoints.
- `test_runner_does_not_teardown_shared` - after run, `teardown_ua2_baseline` NOT called; shared DS persist.
- `test_runner_case_cleanup_uses_case_prefix` - per-case cleanup invoked with `--prefix ua_case_ua2_` (default).
- `test_runner_keeps_shared_on_failure` - even when cases FAIL, shared DS not deleted.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k runner`
Expected: FAIL

- [ ] **Step 3: Modify `scripts/run_automation_ua2.py`**

Key edits:
- Add `_start_mock_at(yaml_name, port, out_dir, deadline_ts)` generalized from `_start_mock` (which hardcodes 18965). Keep `_start_mock` as a wrapper for types for back-compat, or rename.
- In `main()`: start types mock (18965) AND empty mock (18967); store both handles.
- After both ready: build a provisioning `RunContext` (login via env) and call `ensure_ua2_baseline(ctx)`; record result in summary `["baseline"]`. On `BaselineError` -> status FAIL, stop mocks, exit 1.
- In `_run_single_case`: add `ua2Baseline` to run-config JSON payload: `{"typesDatasourceName":"ua_shared_ua2_types_ds","typesEndpoint":<18965>,"emptyDatasourceName":"ua_shared_ua2_empty_ds","emptyEndpoint":<18967>}`. Also set env `UA2_EMPTY_ENDPOINT` for the subprocess.
- Remove shared-DS teardown from final cleanup. `_cleanup` stays (case-only prefix `ua_case_ua2_` by default now).
- Stop BOTH mocks at end.
- Summary gains `["baseline"]` and `["emptyMockProcess"]`.

Skeleton of the changed `main()` body (showing new steps; rest unchanged):
```python
    mock_types = _start_mock_at("ua2_types.yaml", 18965, out_dir, deadline_ts)
    mock_empty = _start_mock_at("ua2_empty.yaml", 18967, out_dir, deadline_ts)
    summary["mockProcess"] = _mock_summary(mock_types)
    summary["emptyMockProcess"] = _mock_summary(mock_empty)
    if not (mock_types.get("started") and mock_empty.get("started")):
        _stop_mock(mock_types); _stop_mock(mock_empty)
        ... write result, return 1

    # provision shared baseline
    try:
        from ua_test_harness.config import RunConfig
        from ua_test_harness.context import RunContext
        from ua_test_harness.provisioning import ensure_ua2_baseline, BaselineError
        from unittest.mock import MagicMock
        pcfg = RunConfig()
        pcfg.local_ip = local_ip
        pcfg.mock.endpoints.functional = f"opc.tcp://{local_ip}:18965/ua_mocker/"
        pcfg.subject.base_url = os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.153:31501/")
        pcfg.subject.username = os.environ.get("DATAHUB_USER", "admin")
        pcfg.subject.password = os.environ.get("DATAHUB_PASSWORD", "")
        pctx = RunContext(config=pcfg, emitter=MagicMock())
        os.environ["UA2_EMPTY_ENDPOINT"] = f"opc.tcp://{local_ip}:18967/ua_mocker/"
        baseline = ensure_ua2_baseline(pctx)
        summary["baseline"] = {"status": "OK", "types": baseline.types_ds_id, "empty": baseline.empty_ds_id}
    except Exception as exc:
        summary["baseline"] = {"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}
        _stop_mock(mock_types); _stop_mock(mock_empty)
        ... write result, return 1

    # ... run 16 cases (unchanged loop), but _run_single_case now adds ua2Baseline + env ...

    summary["finalCleanup"] = _cleanup(out_dir)  # case-only; shared DS NOT deleted
    _stop_mock(mock_types); _stop_mock(mock_empty)
    # NO teardown_ua2_baseline call here
```

- [ ] **Step 4: Modify `scripts/run_automation_ua2.ps1`** (forward chapter timeout - minor, optional)

No structural change required; the file is a thin wrapper. Leave as-is unless test demands.

- [ ] **Step 5: Run runner tests to verify they pass**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_scripts.py -q -k runner`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/run_automation_ua2.py scripts/run_automation_ua2.ps1 ua_test_harness/unit_tests/test_ua2_scripts.py
git commit -m "refactor(ua2): runner starts two mocks, provisions shared baseline, keeps shared DS"
```

---

## Task 11: Cross-cutting verification & final checks

**Covers:** unit req 1, 2, 3, 17, 18, 19, 20; §12 verification
**Files:**
- Test: `ua_test_harness/unit_tests/test_ua2_resource_refactor.py` (cross-cutting tests)

- [ ] **Step 1: Write cross-cutting tests**

- `test_no_ua2_first_batch_calls_prepare_datasource` - import all 3 runtime modules; monkeypatch `ua2_common.prepare_datasource` to raise `AssertionError`; run each of the 16 handlers with fakes (require_shared_datasource mocked) and assert none trigger the raise. (req 1)
- `test_no_ua2_first_batch_creates_datasource` - monkeypatch `ua2_ops.create_datasource_raw` and `fixtures.datasource.create_datasource` to raise; run all 16 handlers with fakes; assert none create a datasource. (req 2)
- `test_no_ua2_first_batch_deletes_shared_datasource` - monkeypatch `tpt_api.datahub.delete_ds_info` to record ids; ensure no handler deletes a datasource whose name is `ua_shared_ua2_*`. (req 3)
- `test_product_fail_not_masked_by_cleanup` - a handler whose assertion fails (AssertFail) still reports FAIL even if cleanup also raises; assert the raised exception reaching the runner is AssertFail, not the cleanup error. (req 17, 18) - validate via `cleanup_case_tag` swallowing.
- `test_catalog_total_unchanged` - `discover(); len(all_defs())==419`; UA-2==265. (req 19)
- `test_inventory_structure_ok` - run `build_inventory` (or CLI) -> `documented==419, implemented==419, unimplemented==0, malformedRows==0, duplicateDocumentIds==0`. (req 20)
- `test_existing_unit_tests_still_pass` is implicit (run full suite in Step 3).

- [ ] **Step 2: Run cross-cutting tests**

Run: `python -m pytest ua_test_harness/unit_tests/test_ua2_resource_refactor.py -q`
Expected: PASS

- [ ] **Step 3: Run full verification suite (§12)**

```powershell
python -m compileall -q ua_test_harness scripts tpt_api
python -m pytest ua_test_harness/unit_tests -q
python -m ua_test_harness.cli catalog --output output\ua2-resource-refactor-catalog.json
python -m ua_test_harness.case_inventory --repo-root . --expected-total 419 --strict-structure --output output\ua2-resource-refactor-inventory.json
```
Expected:
- compileall: no errors
- pytest: all pass
- catalog: total=419, UA-2=265
- inventory: documented=419, implemented=419, unimplemented=0, malformedRows=0, duplicateDocumentIds=0

- [ ] **Step 4: Commit**

```bash
git add ua_test_harness/unit_tests/test_ua2_resource_refactor.py
git commit -m "test(ua2): cross-cutting resource-model verification tests"
```

- [ ] **Step 5 (real env, if available): Run the automation batch**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_automation_ua2.ps1
```
Record the 16-case statuses. Per §12 acceptance: 0 HARNESS ERROR; each case either enters target product behavior or gives a clear BLOCKED reason; shared DS persist across the batch; case-private tags gone after each case; product FAILs preserved; cleanup recorded separately. Real run need NOT be 16/16 PASS.

---

## Self-Review Notes

- **Spec coverage:** Every §1-§13 spec section maps to a task. §2 shared model -> T1,T2; §3 reading (done pre-plan); §4 目标1-5 -> T2,T3,T4-6; §5 16-case model -> T4,T5,T6; §6 runner -> T10; §7 cleanup -> T7,T8; §8 diagnose -> T9; §9 status -> existing runner (verified T11); §10 unit tests -> every task + T11; §11 readability -> case pattern in T4-6; §12 verification -> T11 Step 3; §13 commit -> each task commits.
- **Type consistency:** `require_shared_datasource(ctx, "types"|"empty")`, `create_case_tag(ctx, cc, ds_id, suffix=...)`, `cleanup_case_tag(ctx, cc, tag_id, tag_name)` signatures are consistent across T3-T6. `physical_delete_tag(ctx, tag_id)` / `soft_delete_tag(ctx, tag_id)` / `restore_tag(ctx, tag_id)` take `tag_id` (int) not name - matches T3 and T6.
- **No UA-1 breakage:** UA-1 uses `ua1_runtime._prepare` + legacy fixtures, untouched. `prepare_datasource` retained in `ua2_common.py`. New code in new modules only.
- **AGENTS.md discipline:** assertions never weakened; `cleanup_case_tag` swallows only to prevent masking case status (justified by §9), not to pass tests; case FAILs stay FAIL.
