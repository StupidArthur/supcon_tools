"""Stage 5 prospective acceptance: behavioral atomic /writes contracts.

See SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md §2.1 and CONTRACT_SURFACES.md.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

# STAGE5-ATOMIC-013: poll GET /writes/{batchId} until failed (monotonic clock, short interval).
_CONFIRM_TIMEOUT_POLL_INTERVAL_S = 0.01
_CONFIRM_TIMEOUT_WAIT_BUDGET_S = 0.5

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import components.programs  # noqa: F401
from controller.clock import ClockMode
from controller.engine import UnifiedEngine
from controller.parser import DSLParser
from datacenter import engine_api
from fastapi.testclient import TestClient
from tools.stage_verification.common.workspace import copy_template_fixture


def _writes_route_exists() -> bool:
    for route in engine_api.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if isinstance(path, str) and path.rstrip("/").endswith("/writes") and (
            not methods or "POST" in methods
        ):
            return True
        if isinstance(path, str) and "/writes" in path and (
            not methods or "POST" in methods
        ):
            return True
    return False


def _build_engine(yaml_path: str, cycle_time: float = 0.5) -> UnifiedEngine:
    config = DSLParser().parse_file(yaml_path)
    config.clock.cycle_time = cycle_time
    engine = UnifiedEngine.from_program_config(config)
    engine.clock.config.mode = ClockMode.GENERATOR
    return engine


def _make_binding(yaml_path: str, instance_name: str = "acceptance_runtime") -> engine_api.EngineBinding:
    engine = _build_engine(yaml_path)
    shared: Dict[str, float] = {}
    binding = engine_api.EngineBinding(
        instance_name=instance_name, engine=engine, shared_data=shared
    )

    def drive(n: int = 1) -> None:
        engine.clock.start()
        for _ in range(n):
            snap = engine.step()
            binding.push_snapshot(snap)
        engine.clock.stop()

    drive(2)
    binding._drive_test = drive  # type: ignore[attr-defined]
    return binding


@pytest.fixture
def api_client(
    tmp_path: Path, verifier_root: Path
) -> Iterator[tuple[TestClient, engine_api.EngineBinding]]:
    yaml_path = copy_template_fixture(tmp_path, verifier_root=verifier_root)
    binding = _make_binding(str(yaml_path), instance_name="acceptance_runtime")
    engine_api.set_binding(binding)
    client = TestClient(engine_api.app)
    try:
        yield client, binding
    finally:
        engine_api.set_binding(None)  # type: ignore[arg-type]


def _require_writes() -> None:
    assert _writes_route_exists(), (
        "STAGE5-ATOMIC-001: POST /api/instances/{runtimeName}/writes is required; "
        "do not treat /params as the atomic write API"
    )


def _write_tags(writes: List[Dict[str, Any]]) -> set[str]:
    return {str(item.get("tag")) for item in writes}


def test_stage5_atomic_001_writes_route_not_params() -> None:
    paths = {getattr(r, "path", "") for r in engine_api.app.routes}
    assert any("/params" in p for p in paths), (
        "STAGE5-ATOMIC-014: legacy /params should remain for compatibility probe"
    )
    assert any("/writes" in p for p in paths), (
        "STAGE5-ATOMIC-001: POST /writes must exist; /params must not substitute"
    )


def test_stage5_atomic_002_004_invalid_batch_rejects_entirely(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    """Invalid mixed batch: 4xx, no batch_id, drive cycle, legal field unchanged, no pending."""
    _require_writes()
    client, binding = api_client
    before = dict(binding.get_latest_snapshot() or {})
    sv_before = before.get("pid2.SV")
    pb_before = before.get("pid2.PB")
    cycle_before = before.get("cycle_count")

    resp = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={
            "writes": [
                {"tag": "pid2.SV", "value": 0.8},
                {"tag": "unknown.tag", "value": 1},
            ]
        },
    )
    assert 400 <= resp.status_code < 500, (
        f"STAGE5-ATOMIC-002: invalid batch must return 4xx, got {resp.status_code}"
    )
    body: Dict[str, Any] = {}
    if resp.content:
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {}
    assert not body.get("ok"), "STAGE5-ATOMIC-003: reject must not set ok=true"
    assert not body.get("batch_id"), (
        "STAGE5-ATOMIC-003: reject must not return a successful batch_id"
    )
    text = str(body).lower() + resp.text.lower()
    assert "unknown" in text or "tag" in text or "fail" in text, (
        "STAGE5-ATOMIC-003: error must identify the failing field or reason"
    )

    binding._drive_test(1)  # type: ignore[attr-defined]
    after = binding.get_latest_snapshot() or {}
    assert after.get("pid2.SV") == sv_before, (
        "STAGE5-ATOMIC-004: after an Engine cycle, legal SV must still be unchanged "
        "(no partial enqueue)"
    )
    if pb_before is not None:
        assert after.get("pid2.PB") == pb_before, "STAGE5-ATOMIC-004: PB must be unchanged"
    assert cycle_before is not None, (
        "STAGE5-ATOMIC-004: before snapshot must expose cycle_count"
    )
    cycle_after = after.get("cycle_count")
    assert cycle_after is not None, (
        "STAGE5-ATOMIC-004: after snapshot must expose cycle_count"
    )
    assert cycle_after > cycle_before, (
        "STAGE5-ATOMIC-004: after Engine drive, cycle_count must advance "
        f"(before={cycle_before}, after={cycle_after})"
    )

    # No pending batch from the rejected POST.
    list_resp = client.get("/api/instances/acceptance_runtime/writes")
    if list_resp.status_code < 300:
        payload = list_resp.json()
        items = payload if isinstance(payload, list) else payload.get("batches") or payload.get("items") or []
        pending = [b for b in items if isinstance(b, dict) and b.get("status") == "pending"]
        assert not pending, (
            "STAGE5-ATOMIC-004: rejected request must leave no pending batch"
        )


def test_stage5_atomic_005_006_same_cycle_application(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    """Legal batch: pending, not applied pre-cycle, same cycle_count confirm, applied."""
    _require_writes()
    client, binding = api_client
    before = dict(binding.get_latest_snapshot() or {})
    cycle_before = before.get("cycle_count")
    targets = {"pid2.SV": 0.42, "pid2.PB": 25.0}

    resp = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": k, "value": v} for k, v in targets.items()]},
    )
    assert resp.status_code < 300, f"STAGE5-ATOMIC-005: expected accept, got {resp.status_code}"
    payload = resp.json()
    assert payload.get("status") == "pending", (
        "STAGE5-ATOMIC-011: REST success must be pending before snapshot confirm"
    )
    batch_id = payload.get("batch_id")
    assert batch_id, "STAGE5-ATOMIC-011: batch_id required"

    # Pre-cycle: snapshot must be unchanged for all targets (no early apply).
    mid = binding.get_latest_snapshot() or {}
    assert mid.get("cycle_count") == cycle_before, (
        "STAGE5-ATOMIC-005: cycle_count must not advance before the driven Engine cycle"
    )
    for tag in targets:
        assert mid.get(tag) == before.get(tag), (
            f"STAGE5-ATOMIC-005: {tag} must not change before the next Engine cycle"
        )

    binding._drive_test(1)  # type: ignore[attr-defined]
    snap = binding.get_latest_snapshot() or {}
    confirm_cycle = snap.get("cycle_count")
    assert confirm_cycle is not None and confirm_cycle != cycle_before, (
        "STAGE5-ATOMIC-006: Engine must advance a cycle"
    )
    for tag, value in targets.items():
        assert snap.get(tag) == pytest.approx(value), (
            f"STAGE5-ATOMIC-006: {tag} missing on confirm cycle {confirm_cycle}"
        )

    status = client.get(f"/api/instances/acceptance_runtime/writes/{batch_id}")
    assert status.status_code < 300, "STAGE5-ATOMIC-012: batch status query required"
    st = status.json()
    assert st.get("status") == "applied", "STAGE5-ATOMIC-012: status must be applied"
    assert st.get("batch_id", batch_id) == batch_id
    if st.get("confirmed_cycle_count") is not None:
        assert st.get("confirmed_cycle_count") == confirm_cycle, (
            "STAGE5-ATOMIC-012: confirmed_cycle_count must equal snapshot cycle_count"
        )


def test_stage5_atomic_007_009_reject_readonly_and_derived(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    _require_writes()
    client, binding = api_client
    before = dict(binding.get_latest_snapshot() or {})
    cases = [
        ("STAGE5-ATOMIC-007", [{"tag": "no_such_tag", "value": 1}]),
        ("STAGE5-ATOMIC-008", [{"tag": "pid2.PV", "value": 0.5}]),
        ("STAGE5-ATOMIC-009", [{"tag": "AUTO", "value": 1}]),
        ("STAGE5-ATOMIC-009", [{"tag": "CAS", "value": 1}]),
    ]
    for contract_id, writes in cases:
        resp = client.post(
            "/api/instances/acceptance_runtime/writes",
            json={"writes": writes},
        )
        assert 400 <= resp.status_code < 500, f"{contract_id}: must reject {writes}"
        assert not (resp.json() if resp.content else {}).get("batch_id"), (
            f"{contract_id}: must not return batch_id"
        )
        after = binding.get_latest_snapshot() or {}
        for key in ("pid2.SV", "pid2.MV", "pid2.PB"):
            if key in before:
                assert after.get(key) == before.get(key), (
                    f"{contract_id}: Engine state must be unchanged after reject"
                )


def test_stage5_atomic_010_runtime_then_program(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    _require_writes()
    client, _binding = api_client
    resp = client.post(
        "/api/instances/pid2/writes",
        json={"writes": [{"tag": "pid2.SV", "value": 0.7}]},
    )
    assert resp.status_code == 404, (
        "STAGE5-ATOMIC-010: route selects runtimeName first; pid2 is programName not runtime"
    )
    ok = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "pid2.SV", "value": 0.7}]},
    )
    assert ok.status_code != 404, (
        "STAGE5-ATOMIC-010: acceptance_runtime + tag pid2.SV must address PID program inside instance"
    )


def test_stage5_atomic_011_013_pending_applied_failed_lifecycle(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    _require_writes()
    client, binding = api_client
    resp = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "pid2.SV", "value": 0.33}]},
    )
    assert resp.status_code < 300, "STAGE5-ATOMIC-011: REST accept required"
    data = resp.json()
    assert data.get("status") == "pending", "STAGE5-ATOMIC-011: status must be pending"
    batch_id = data.get("batch_id")
    assert batch_id, "STAGE5-ATOMIC-011: batch_id required for status query"

    binding._drive_test(1)  # type: ignore[attr-defined]
    confirmed = client.get(f"/api/instances/acceptance_runtime/writes/{batch_id}")
    assert confirmed.status_code < 300, "STAGE5-ATOMIC-012: batch status query required"
    assert confirmed.json().get("status") == "applied", "STAGE5-ATOMIC-012"

    timed = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "pid2.TI", "value": 100.0}], "confirm_timeout_s": 0.001},
    )
    assert timed.status_code < 300, (
        "STAGE5-ATOMIC-013: timeout batch must still be accepted as pending first"
    )
    tid = timed.json().get("batch_id")
    assert tid, "STAGE5-ATOMIC-013: batch_id required"
    # Do not drive cycles — confirmation must time out via confirm_timeout_s alone.
    # Poll GET /writes/{batchId} with monotonic clock; do not call /expire.
    deadline = time.monotonic() + _CONFIRM_TIMEOUT_WAIT_BUDGET_S
    last_status: Any = None
    last_code = None
    while time.monotonic() < deadline:
        expired = client.get(f"/api/instances/acceptance_runtime/writes/{tid}")
        last_code = expired.status_code
        if expired.status_code < 300:
            last_status = expired.json().get("status")
            if last_status == "failed":
                return
        time.sleep(_CONFIRM_TIMEOUT_POLL_INTERVAL_S)
    assert last_status == "failed", (
        "STAGE5-ATOMIC-013: within bounded wait after confirm_timeout_s, "
        f"GET /writes/{{batchId}} must reach status=failed "
        f"(last_code={last_code}, last_status={last_status}); "
        "do not require /writes/{{batchId}}/expire"
    )


def test_stage5_atomic_015_concurrent_batches_isolated(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    """Strong isolation: IDs, ownership, writes content, independent confirm/fail."""
    _require_writes()
    client, binding = api_client
    writes_a = [{"tag": "pid2.SV", "value": 0.11}]
    writes_b = [{"tag": "pid2.PB", "value": 40.0}]
    a = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": writes_a},
    )
    b = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": writes_b},
    )
    assert a.status_code < 300 and b.status_code < 300, "STAGE5-ATOMIC-015: both batches accept"
    id_a, id_b = a.json().get("batch_id"), b.json().get("batch_id")
    assert id_a and id_b, "STAGE5-ATOMIC-015: both batch_ids required"
    assert id_a != id_b, "STAGE5-ATOMIC-015: A.id != B.id"

    # Before confirm: query each batch.
    qa = client.get(f"/api/instances/acceptance_runtime/writes/{id_a}")
    qb = client.get(f"/api/instances/acceptance_runtime/writes/{id_b}")
    assert qa.status_code < 300 and qb.status_code < 300, "STAGE5-ATOMIC-015: status queries required"
    sa, sb = qa.json(), qb.json()
    assert sa.get("batch_id") == id_a, "STAGE5-ATOMIC-015: A query result belongs to A"
    assert sb.get("batch_id") == id_b, "STAGE5-ATOMIC-015: B query result belongs to B"
    assert _write_tags(sa.get("writes") or a.json().get("writes") or []) == {"pid2.SV"}, (
        "STAGE5-ATOMIC-015: A.writes must only contain A content"
    )
    assert _write_tags(sb.get("writes") or b.json().get("writes") or []) == {"pid2.PB"}, (
        "STAGE5-ATOMIC-015: B.writes must only contain B content"
    )
    assert sa.get("status") == "pending" and sb.get("status") == "pending"

    binding._drive_test(1)  # type: ignore[attr-defined]
    sa2 = client.get(f"/api/instances/acceptance_runtime/writes/{id_a}").json()
    sb2 = client.get(f"/api/instances/acceptance_runtime/writes/{id_b}").json()
    assert sa2.get("batch_id") == id_a
    assert sb2.get("batch_id") == id_b
    assert sa2.get("status") == "applied", "STAGE5-ATOMIC-015: A confirmed applied"
    assert sb2.get("status") == "applied", "STAGE5-ATOMIC-015: confirming A must not fail B"
    assert _write_tags(sa2.get("writes") or writes_a) == {"pid2.SV"}
    assert _write_tags(sb2.get("writes") or writes_b) == {"pid2.PB"}

    # A failure must not fail B: submit bad A' while B' pending then confirm B'.
    bad = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "unknown.tag", "value": 1}]},
    )
    assert 400 <= bad.status_code < 500, "STAGE5-ATOMIC-015 setup: bad batch rejected"
    good = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "pid2.TI", "value": 88.0}]},
    )
    assert good.status_code < 300, "STAGE5-ATOMIC-015: B-like batch still accepted after A failure"
    gid = good.json().get("batch_id")
    binding._drive_test(1)  # type: ignore[attr-defined]
    gst = client.get(f"/api/instances/acceptance_runtime/writes/{gid}").json()
    assert gst.get("status") == "applied", (
        "STAGE5-ATOMIC-015: A failure must not prevent a subsequent batch B from applying"
    )


def test_stage_5_reviewer_files_and_contract_surfaces(project_root: Path) -> None:
    surfaces = project_root / "tools/stage_verification/acceptance/CONTRACT_SURFACES.md"
    spec = project_root / "tools/stage_verification/acceptance/SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md"
    assert surfaces.is_file() and spec.is_file()
    text = surfaces.read_text(encoding="utf-8")
    assert "SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md" in text
    assert "second_order_tank_repository_contracts.md" in text or "repository contracts" in text.lower()
    assert "POST /api/instances/{runtimeName}/writes" in text
    assert "ApplyRuntimeOverrides" in text
    assert "ApplyRuntimeOverridesRequest" in text or "ExpectedHash" in text
