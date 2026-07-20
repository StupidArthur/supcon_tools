"""Stage 6 prospective: evidence gate + quality fixture inventory (behavioral, not internal names)."""

from __future__ import annotations

from pathlib import Path


def test_stage_6_trend_visual_review_evidence_requirements(project_root: Path) -> None:
    evidence = (
        project_root
        / "tools"
        / "stage_verification"
        / "evidence"
        / "stage_6"
        / "trend_visual_review.md"
    )
    assert evidence.is_file(), "STAGE6-TREND-GATE-001: trend_visual_review.md required (unsigned)"
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
        assert needle.lower() in text.lower(), f"STAGE6-TREND-GATE-001: missing {needle!r}"


def test_stage_6_quality_fixtures_exist(project_root: Path) -> None:
    fixture_dir = project_root / "tools" / "stage_verification" / "fixtures" / "quality"
    required = [
        "quality_perfect_tracking.json",
        "quality_overshoot.json",
        "quality_settles_at_60s.json",
        "quality_not_settled_at_59s.json",
        "quality_irregular_sampling.json",
        "quality_missing_nonfinite.json",
        "quality_parameter_event.json",
        "quality_level_limit_hits.json",
    ]
    missing = [name for name in required if not (fixture_dir / name).is_file()]
    assert not missing, f"STAGE6-QUALITY-001: missing fixtures {missing}"


def test_stage_6_contract_surfaces_lists_compute_control_quality(project_root: Path) -> None:
    text = (
        project_root / "tools/stage_verification/acceptance/CONTRACT_SURFACES.md"
    ).read_text(encoding="utf-8")
    assert "computeControlQuality" in text
    assert "RuntimeTrendPanel" in text


def test_stage_6_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_6/test_trend_quality_acceptance.py",
        "config-tool/frontend/acceptance/stage_6/trend_buffer.acceptance.test.tsx",
        "config-tool/frontend/acceptance/stage_6/control_quality.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_6/trend_events.acceptance.test.tsx",
        "config-tool/frontend/acceptance/stage_6/trend_panel.acceptance.test.tsx",
    ]
    missing = [p for p in required if not (project_root / p).is_file()]
    assert not missing, f"missing stage 6 files: {missing}"
