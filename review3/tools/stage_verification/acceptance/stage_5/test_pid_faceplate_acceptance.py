"""Stage 5 prospective acceptance: PID Faceplate mode/edit contracts (Python markers).

Frontend owns UI behavior; this file locks shared Faceplate/write-status vocabulary
and backend confirmation semantics required by the Faceplate.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import datacenter.engine_api as engine_api


FACEPLATE_FIELDS = (
    "PV",
    "SV",
    "CSV",
    "MV",
    "PB",
    "TI",
    "TD",
    "KD",
    "MODE",
    "SWPN",
)


def test_stage_5_faceplate_field_vocabulary_exported() -> None:
    """STAGE5-MODE-001: Faceplate parameter vocabulary must be exported for UI/API."""
    vocab = getattr(engine_api, "PID_FACEPLATE_FIELDS", None)
    assert isinstance(vocab, (set, list, tuple)), (
        "STAGE5-MODE-001: PID_FACEPLATE_FIELDS export required "
        f"covering {FACEPLATE_FIELDS}"
    )
    assert set(FACEPLATE_FIELDS).issubset(set(vocab)), (
        f"STAGE5-MODE-001: missing fields {set(FACEPLATE_FIELDS) - set(vocab)}"
    )


def test_stage_5_mode_editability_policy() -> None:
    """STAGE5-MODE-002: AUTO/MAN/CAS editability matrix must be declared."""
    matrix = getattr(engine_api, "PID_MODE_EDITABILITY", None)
    assert isinstance(matrix, dict), (
        "STAGE5-MODE-002: PID_MODE_EDITABILITY dict required "
        "(AUTO: SV writable/MV locked; MAN: MV writable; CAS: CSV is effective setpoint)"
    )
    for mode in ("AUTO", "MAN", "CAS"):
        assert mode in matrix, f"STAGE5-MODE-002: missing mode policy for {mode}"


def test_stage_5_write_status_vocabulary() -> None:
    """STAGE5-MODE-003: pending/applied/failed status vocabulary required."""
    statuses = getattr(engine_api, "WRITE_STATUS_VALUES", None)
    assert isinstance(statuses, (set, list, tuple)), (
        "STAGE5-MODE-003: WRITE_STATUS_VALUES must include pending, applied, failed"
    )
    assert {"pending", "applied", "failed"}.issubset(set(statuses)), (
        f"STAGE5-MODE-003: got {statuses!r}"
    )


def test_stage_5_effective_setpoint_resolver() -> None:
    """STAGE5-MODE-004: effective setpoint must follow MODE (SV vs CSV)."""
    resolver = getattr(engine_api, "resolve_effective_setpoint", None)
    assert callable(resolver), (
        "STAGE5-MODE-004: resolve_effective_setpoint(mode, sv, csv) required; "
        "CAS must use CSV, not SV"
    )


def test_stage_5_faceplate_rest_pending_not_applied() -> None:
    """STAGE5-MODE-005: Faceplate REST ack is pending until snapshot confirmation."""
    tracker = getattr(engine_api, "WriteStatusTracker", None)
    assert tracker is not None, (
        "STAGE5-MODE-005: WriteStatusTracker required so Faceplate shows pending "
        "after REST success and applied only after snapshot confirmation"
    )
