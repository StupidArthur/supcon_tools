"""Stage 5 prospective acceptance: behavioral atomic /writes contracts.

Locks HTTP behavior only. Does NOT require internal helper/class names.
See CONTRACT_SURFACES.md → STAGE5-ATOMIC.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest

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
def api_client(tmp_path: Path, verifier_root: Path) -> Iterator[tuple[TestClient, engine_api.EngineBinding]]:
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
    _require_writes()
    client, binding = api_client
    before = binding.get_latest_snapshot() or {}
    sv_before = before.get("pid2.SV")
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
    body = resp.json() if resp.content else {}
    text = str(body).lower() + resp.text.lower()
    assert "unknown" in text or "tag" in text, (
        "STAGE5-ATOMIC-003: error must identify the failing field"
    )
    after = binding.get_latest_snapshot() or {}
    assert after.get("pid2.SV") == sv_before, (
        "STAGE5-ATOMIC-004: no partial enqueue — valid fields must not apply when batch fails"
    )


def test_stage5_atomic_005_006_same_cycle_application(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    _require_writes()
    client, binding = api_client
    resp = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={
            "writes": [
                {"tag": "pid2.SV", "value": 0.42},
                {"tag": "pid2.PB", "value": 25.0},
            ]
        },
    )
    assert resp.status_code < 300, f"STAGE5-ATOMIC-005: expected accept, got {resp.status_code}"
    payload = resp.json()
    assert payload.get("status") == "pending", (
        "STAGE5-ATOMIC-011: REST success must be pending before snapshot confirm"
    )
    binding._drive_test(1)  # type: ignore[attr-defined]
    snap = binding.get_latest_snapshot() or {}
    # Both targets must appear together on the confirming cycle.
    assert snap.get("pid2.SV") == pytest.approx(0.42), "STAGE5-ATOMIC-006: SV missing on confirm cycle"
    assert snap.get("pid2.PB") == pytest.approx(25.0), "STAGE5-ATOMIC-006: PB missing on confirm cycle"
    status = client.get(
        f"/api/instances/acceptance_runtime/writes/{payload.get('batch_id')}"
    )
    if status.status_code < 300:
        assert status.json().get("status") == "applied", (
            "STAGE5-ATOMIC-012: snapshot same-cycle confirm → applied"
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
    # Wrong runtimeName → 404 even if programName pid2 is in the body tags.
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

    # Timeout path: accept a batch then expire without driving cycles (public expire/query).
    timed = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "pid2.TI", "value": 100.0}], "confirm_timeout_s": 0},
    )
    if timed.status_code < 300:
        tid = timed.json().get("batch_id")
        # Implementation may expose expire via query after timeout_s=0 or dedicated endpoint.
        expired = client.get(f"/api/instances/acceptance_runtime/writes/{tid}")
        if expired.status_code < 300 and expired.json().get("status") == "failed":
            return
        expire = client.post(f"/api/instances/acceptance_runtime/writes/{tid}/expire")
        if expire.status_code < 300:
            assert expire.json().get("status") == "failed", "STAGE5-ATOMIC-013"
            return
    assert False, (
        "STAGE5-ATOMIC-013: public surface must allow timed-out batches to become failed"
    )


def test_stage5_atomic_015_concurrent_batches_isolated(
    api_client: tuple[TestClient, engine_api.EngineBinding],
) -> None:
    _require_writes()
    client, binding = api_client
    a = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "pid2.SV", "value": 0.11}]},
    )
    b = client.post(
        "/api/instances/acceptance_runtime/writes",
        json={"writes": [{"tag": "pid2.PB", "value": 40.0}]},
    )
    assert a.status_code < 300 and b.status_code < 300, "STAGE5-ATOMIC-015: both batches accept"
    id_a, id_b = a.json().get("batch_id"), b.json().get("batch_id")
    assert id_a and id_b and id_a != id_b, "STAGE5-ATOMIC-015: independent batch IDs"
    binding._drive_test(1)  # type: ignore[attr-defined]
    sa = client.get(f"/api/instances/acceptance_runtime/writes/{id_a}").json()
    sb = client.get(f"/api/instances/acceptance_runtime/writes/{id_b}").json()
    # Confirming one batch must not steal the other's identity.
    assert sa.get("batch_id", id_a) != id_b or sa.get("writes") != sb.get("writes"), (
        "STAGE5-ATOMIC-015: batch contents must not cross"
    )


def test_stage_5_reviewer_files_and_contract_surfaces(project_root: Path) -> None:
    surfaces = project_root / "tools/stage_verification/acceptance/CONTRACT_SURFACES.md"
    assert surfaces.is_file(), "CONTRACT_SURFACES.md must list public acceptance seams"
    text = surfaces.read_text(encoding="utf-8")
    assert "POST /api/instances/{runtimeName}/writes" in text
    assert "ApplyRuntimeOverrides" in text
