"""Stage 5 prospective acceptance: atomic online write batch contracts.

Business implementation is not required yet. Failures must be explicit contract
assertions with stable IDs (STAGE5-ATOMIC-*). No skip/xfail.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import datacenter.engine_api as engine_api


def _route_paths() -> set[str]:
    paths: set[str] = set()
    for route in getattr(engine_api, "app", None).routes:  # type: ignore[union-attr]
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
    return paths


def _require_attr(obj: Any, name: str, contract_id: str) -> Any:
    value = getattr(obj, name, None)
    assert value is not None, f"{contract_id}: missing attribute {name!r} on {type(obj).__name__}"
    return value


def test_stage_5_atomic_writes_route_exists() -> None:
    """STAGE5-ATOMIC-001: new atomic write interface must use /writes."""
    paths = _route_paths()
    assert any("/writes" in p for p in paths), (
        "STAGE5-ATOMIC-001: POST /api/instances/{name}/writes is required; "
        f"current routes={sorted(paths)}"
    )


def test_stage_5_legacy_params_is_not_the_atomic_contract() -> None:
    """STAGE5-ATOMIC-014: old /params must not be treated as the new atomic API."""
    paths = _route_paths()
    assert any(p.endswith("/params") for p in paths), (
        "STAGE5-ATOMIC-014: legacy /params must still exist for compatibility probe"
    )
    # The atomic contract is /writes; presence of /params alone is not enough.
    assert any("/writes" in p for p in paths), (
        "STAGE5-ATOMIC-014: acceptance must not treat legacy /params as the atomic write API; "
        "/writes is required"
    )


def test_stage_5_atomic_batch_validate_all_or_reject() -> None:
    """STAGE5-ATOMIC-002/003/004: whole-batch validation; no partial enqueue."""
    submit = getattr(engine_api, "submit_atomic_writes", None)
    assert callable(submit), (
        "STAGE5-ATOMIC-002: submit_atomic_writes(runtime_name, writes) required for "
        "whole-batch validation before enqueue"
    )
    # Capability shape probe — implementation must reject invalid field without enqueue.
    sig = inspect.signature(submit)
    assert len(sig.parameters) >= 2, (
        "STAGE5-ATOMIC-003: submit_atomic_writes must accept runtime name and write batch"
    )


def test_stage_5_atomic_batch_same_cycle_boundary() -> None:
    """STAGE5-ATOMIC-005/006: batch applied on one Engine cycle; confirmed together."""
    apply_fn = getattr(engine_api, "apply_pending_write_batches", None)
    assert callable(apply_fn), (
        "STAGE5-ATOMIC-005: apply_pending_write_batches must apply an entire batch "
        "on a single Engine cycle boundary"
    )
    confirm_fn = getattr(engine_api, "confirm_write_batch_from_snapshot", None)
    assert callable(confirm_fn), (
        "STAGE5-ATOMIC-006: confirm_write_batch_from_snapshot must require all target "
        "values to appear in the same cycle_count"
    )


def test_stage_5_rejects_unknown_and_readonly_tags() -> None:
    """STAGE5-ATOMIC-007/008: unknown and read-only tags rejected."""
    validate = getattr(engine_api, "validate_atomic_write_batch", None)
    assert callable(validate), (
        "STAGE5-ATOMIC-007: validate_atomic_write_batch required to reject unknown tags"
    )
    # Probe expected policy surface without inventing business behavior.
    policy = getattr(engine_api, "ATOMIC_WRITE_POLICY", None)
    assert isinstance(policy, dict), (
        "STAGE5-ATOMIC-008: ATOMIC_WRITE_POLICY dict required (readonly tags include PV)"
    )
    readonly = policy.get("readonly_tags") if isinstance(policy, dict) else None
    assert isinstance(readonly, (set, list, tuple)) and "PV" in set(readonly), (
        "STAGE5-ATOMIC-008: PV must be listed as a readonly rejected tag"
    )


def test_stage_5_rejects_derived_auto_cas_state_fields() -> None:
    """STAGE5-ATOMIC-009: AUTO/CAS derived state must not be ordinary write fields."""
    policy = getattr(engine_api, "ATOMIC_WRITE_POLICY", None)
    assert isinstance(policy, dict), (
        "STAGE5-ATOMIC-009: ATOMIC_WRITE_POLICY required"
    )
    forbidden = set(policy.get("forbidden_derived_fields") or [])
    assert {"AUTO", "CAS"}.issubset(forbidden) or "derived_mode_state" in policy, (
        "STAGE5-ATOMIC-009: derived AUTO/CAS state fields must be rejected as writes"
    )


def test_stage_5_runtime_name_distinct_from_pid_program_name() -> None:
    """STAGE5-ATOMIC-010: runtimeName ≠ PID programName (pid2)."""
    helper = getattr(engine_api, "resolve_write_target", None)
    assert callable(helper), (
        "STAGE5-ATOMIC-010: resolve_write_target(runtime_name, program_name, tag) required "
        "so runtimeName is never confused with pid2"
    )


def test_stage_5_rest_success_is_pending_until_snapshot() -> None:
    """STAGE5-ATOMIC-011/012: REST success = pending; snapshot confirm = applied."""
    batch_cls = getattr(engine_api, "AtomicWriteBatch", None)
    assert batch_cls is not None, (
        "STAGE5-ATOMIC-011: AtomicWriteBatch type required with status pending|applied|failed"
    )
    status_field = getattr(batch_cls, "status", None)
    # Class attribute or annotated model — presence is enough for prospective probe.
    assert status_field is not None or hasattr(batch_cls, "__annotations__"), (
        "STAGE5-ATOMIC-011: AtomicWriteBatch must expose status lifecycle"
    )
    annotations = getattr(batch_cls, "__annotations__", {})
    if annotations:
        assert "status" in annotations, (
            "STAGE5-ATOMIC-012: AtomicWriteBatch.status required (pending→applied via snapshot)"
        )


def test_stage_5_timeout_becomes_failed() -> None:
    """STAGE5-ATOMIC-013: timeout without snapshot confirmation → failed."""
    expire = getattr(engine_api, "expire_stale_write_batches", None)
    assert callable(expire), (
        "STAGE5-ATOMIC-013: expire_stale_write_batches required to mark timed-out batches failed"
    )


def test_stage_5_concurrent_batches_keep_boundaries() -> None:
    """STAGE5-ATOMIC-015: concurrent batches must not cross-contaminate."""
    manager = getattr(engine_api, "WriteBatchManager", None)
    assert manager is not None, (
        "STAGE5-ATOMIC-015: WriteBatchManager required to isolate concurrent batch boundaries"
    )


def test_stage_5_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_5/test_atomic_writes_acceptance.py",
        "tools/stage_verification/acceptance/stage_5/test_pid_faceplate_acceptance.py",
        "config-tool/frontend/acceptance/stage_5/pid_faceplate.acceptance.test.tsx",
        "config-tool/frontend/acceptance/stage_5/runtime_writes.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_5/writeback.acceptance.test.ts",
        "config-tool/acceptance/stage_5/template_writeback_acceptance_test.go",
    ]
    missing = [p for p in required if not (project_root / p).is_file()]
    assert not missing, f"missing stage 5 reviewer acceptance files: {missing}"
