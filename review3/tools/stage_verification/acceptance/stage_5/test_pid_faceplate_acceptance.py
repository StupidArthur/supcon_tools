"""Stage 5 prospective: Faceplate vocabulary is UI-owned; Python only checks HTTP write status query surface.

Mode editability is enforced by frontend PidFaceplate behavioral tests.
This file keeps a thin cross-check that pending/applied/failed is queryable once /writes exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from datacenter import engine_api


def test_stage5_mode_write_status_query_surface_documented() -> None:
    """STAGE5-MODE-003: status vocabulary is part of /writes public response, not an internal enum name."""
    paths = {getattr(r, "path", "") for r in engine_api.app.routes}
    assert any("/writes" in p for p in paths), (
        "STAGE5-MODE-003: Faceplate pending/applied/failed requires public POST /writes "
        "(and batch status query); internal WRITE_STATUS_VALUES name is not required"
    )


def test_stage5_faceplate_fields_are_frontend_contract(project_root: Path) -> None:
    """STAGE5-MODE-001: fields locked via CONTRACT_SURFACES + frontend render tests."""
    text = (
        project_root / "tools/stage_verification/acceptance/CONTRACT_SURFACES.md"
    ).read_text(encoding="utf-8")
    for field in ("PV", "SV", "CSV", "MV", "PB", "TI", "TD", "KD", "MODE", "SWPN"):
        assert field in text, f"STAGE5-MODE-001: CONTRACT_SURFACES must mention {field}"
