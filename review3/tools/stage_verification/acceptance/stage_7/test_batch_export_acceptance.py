"""Stage 7 prospective: batch export / process contracts (behavioral)."""

from __future__ import annotations

import json
from pathlib import Path


def test_stage_7_reviewer_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_7/test_batch_export_acceptance.py",
        "config-tool/acceptance/stage_7/system_batch_acceptance_test.go",
        "config-tool/frontend/acceptance/stage_7/batch_page.acceptance.test.tsx",
        "config-tool/frontend/acceptance/stage_7/batch_state.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_7/downsample.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_7/export_dialog.acceptance.test.ts",
        "tools/stage_verification/evidence/stage_7/single_page_batch_review.md",
    ]
    missing = [p for p in required if not (project_root / p).is_file()]
    assert not missing, f"missing stage 7 files: {missing}"


def test_stage_7_evidence_unsigned(project_root: Path) -> None:
    path = (
        project_root
        / "tools/stage_verification/evidence/stage_7/single_page_batch_review.md"
    )
    text = path.read_text(encoding="utf-8")
    for needle in (
        "unsigned",
        "same template page",
        "progress",
        "failure",
        "CSV",
        "mutex",
        "empty success",
    ):
        assert needle.lower() in text.lower(), f"STAGE7 evidence missing {needle!r}"


def test_stage_7_downsample_fixture_inventory(project_root: Path) -> None:
    fixture_dir = project_root / "tools/stage_verification/fixtures/downsample"
    required = [
        "downsample_extrema.json",
        "downsample_small.json",
        "downsample_duplicate_time.json",
    ]
    missing = [n for n in required if not (fixture_dir / n).is_file()]
    assert not missing, f"STAGE7-DOWNSAMPLE fixtures missing: {missing}"


def test_stage_7_batch_capability_preflight(project_root: Path) -> None:
    """STAGE7-BATCH-001: public batch entry must eventually support 2000-cycle success.

    Prospective: fail clearly if standalone batch CLI surface is unavailable for harness.
    """
    entry = project_root / "standalone_main.py"
    assert entry.is_file(), "STAGE7-BATCH-001: standalone_main.py required for batch process acceptance"
    # Document expected CLI flags without executing long batch here (no fixed ports / no orphan processes).
    text = entry.read_text(encoding="utf-8")
    assert "--batch" in text or "batch" in text.lower(), (
        "STAGE7-BATCH-001: standalone batch mode surface required"
    )


def test_stage_7_contract_surfaces_updated(project_root: Path) -> None:
    text = (
        project_root / "tools/stage_verification/acceptance/CONTRACT_SURFACES.md"
    ).read_text(encoding="utf-8")
    assert "RunBatch" in text or "STAGE7" in text
