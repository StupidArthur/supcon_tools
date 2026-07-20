"""Stage 6 prospective acceptance: trend buffer + control quality contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_probe():
    probe_path = Path(__file__).with_name("control_quality_probe.py")
    assert probe_path.is_file(), (
        "STAGE6-QUALITY-001: control_quality_probe.py required to lock metric vocabulary "
        "(error band, overshoot, steady-state error, settling time, MV saturation, "
        "level limit hits, 60s window, segment reset after parameter events)"
    )
    spec = importlib.util.spec_from_file_location("stage6_control_quality_probe", probe_path)
    assert spec is not None and spec.loader is not None, "STAGE6-QUALITY-001: cannot load probe"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_6_control_quality_module_probe() -> None:
    """STAGE6-QUALITY-001: acceptance probe locks metric vocabulary (not business impl)."""
    probe = _load_probe()
    assert getattr(probe, "QUALITY_METRIC_IDS", None), "STAGE6-QUALITY-001: QUALITY_METRIC_IDS required"


def test_stage_6_trend_visual_review_evidence_requirements(project_root: Path) -> None:
    """STAGE6-TREND-GATE-001: human gate requirements defined, not signed."""
    evidence = (
        project_root
        / "tools"
        / "stage_verification"
        / "evidence"
        / "stage_6"
        / "trend_visual_review.md"
    )
    assert evidence.is_file(), (
        "STAGE6-TREND-GATE-001: evidence/stage_6/trend_visual_review.md must define "
        "dual-axis, previous-run secondary style, series toggles, event states, "
        "PV←Tank2 binding note, and stale freeze requirements"
    )
    text = evidence.read_text(encoding="utf-8")
    for needle in (
        "dual-axis",
        "previous run",
        "series toggle",
        "pending",
        "applied",
        "failed",
        "pid2.PV",
        "tank_2.level",
        "stale",
        "unsigned",
    ):
        assert needle.lower() in text.lower(), (
            f"STAGE6-TREND-GATE-001: missing evidence requirement marker {needle!r}"
        )


def test_stage_6_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_6/test_trend_quality_acceptance.py",
        "config-tool/frontend/acceptance/stage_6/trend_buffer.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_6/control_quality.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_6/trend_events.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_6/trend_panel.acceptance.test.tsx",
        "tools/stage_verification/evidence/stage_6/trend_visual_review.md",
    ]
    missing = [p for p in required if not (project_root / p).is_file()]
    assert not missing, f"missing stage 6 reviewer acceptance files: {missing}"


def test_stage_6_quality_metric_ids_locked() -> None:
    """STAGE6-QUALITY-002: stable metric IDs for prospective baseline."""
    required_ids = {
        "error_band",
        "overshoot",
        "steady_state_error",
        "settling_time",
        "mv_saturation_time",
        "level_high_hits",
        "level_low_hits",
        "stable_window_60s",
    }
    probe = _load_probe()
    ids = set(getattr(probe, "QUALITY_METRIC_IDS", []) or [])
    assert required_ids.issubset(ids), (
        f"STAGE6-QUALITY-002: missing metric ids {required_ids - ids}"
    )
