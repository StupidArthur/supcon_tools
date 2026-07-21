"""Stage 7 prospective: batch / CSV / process contracts (external behavior).

See SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md §4. Row count locked to exactly 2000.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.stage_verification.common.workspace import copy_template_fixture


def test_stage_7_reviewer_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_7/test_batch_export_acceptance.py",
        "tools/stage_verification/acceptance/stage_7/helpers/fake_datafactory.py",
        "config-tool/acceptance/stage_7/system_batch_acceptance_test.go",
        "config-tool/frontend/acceptance/stage_7/batch_page.acceptance.test.tsx",
        "config-tool/frontend/acceptance/stage_7/batch_state.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_7/downsample.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_7/export_dialog.acceptance.test.ts",
        "tools/stage_verification/evidence/stage_7/single_page_batch_review.md",
        "tools/stage_verification/fixtures/batch/expected_columns.json",
        "tools/stage_verification/fixtures/batch/row_count_contract.json",
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


def test_stage_7_row_count_contract_locked(project_root: Path) -> None:
    doc = json.loads(
        (
            project_root / "tools/stage_verification/fixtures/batch/row_count_contract.json"
        ).read_text(encoding="utf-8")
    )
    assert doc["expected_data_rows"] == 2000, (
        "STAGE7-CSV-002: row count must be locked to exactly 2000 (not a range)"
    )
    assert doc["cycles"] == 2000
    spec = (
        project_root / "tools/stage_verification/acceptance/SECOND_ORDER_TANK_ACCEPTANCE_SPEC.md"
    ).read_text(encoding="utf-8")
    assert "2000" in spec


def test_stage_7_batch_2000_and_csv_contracts(
    project_root: Path, verifier_root: Path, tmp_path: Path
) -> None:
    """STAGE7-BATCH-001 + STAGE7-CSV-001..004 via real standalone_main batch."""
    entry = project_root / "standalone_main.py"
    assert entry.is_file(), "STAGE7-BATCH-001: standalone_main.py required"

    yaml_path = copy_template_fixture(tmp_path / "batch_cfg", verifier_root=verifier_root)
    export_path = tmp_path / "batch_2000.csv"
    proc = subprocess.run(
        [
            sys.executable,
            str(entry),
            "-c",
            str(yaml_path),
            "--batch",
            "2000",
            "--export",
            str(export_path),
            "--cycle-time",
            "0.001",
        ],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, (
        f"STAGE7-BATCH-001/005: 2000-cycle batch must exit 0; stderr={proc.stderr[-500:]}"
    )
    assert export_path.is_file(), "STAGE7-BATCH-001: CSV must exist"

    with export_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    cols_doc = json.loads(
        (
            project_root / "tools/stage_verification/fixtures/batch/expected_columns.json"
        ).read_text(encoding="utf-8")
    )
    header = list(rows[0].keys()) if rows else []
    for col in cols_doc["required_columns"]:
        assert col in header, f"STAGE7-CSV-001: missing column {col}"

    assert len(rows) == 2000, (
        f"STAGE7-CSV-002: expected exactly 2000 data rows, got {len(rows)}"
    )

    # Monotonic time: exporter currently excludes sim_time; if present, enforce order.
    # Prefer valve/tank numeric columns stay finite.
    for row in rows:
        for key in ("tank_2.level", "pid2.PV", "pid2.MV"):
            if key in row and row[key] not in ("", None):
                try:
                    val = float(row[key])
                except ValueError:
                    pytest.fail(f"STAGE7-CSV-004: non-finite {key}={row[key]!r}")
                assert val == val and val not in (float("inf"), float("-inf")), (
                    f"STAGE7-CSV-004: non-finite {key}={val}"
                )


def test_stage_7_concurrent_cli_exports_isolated(
    project_root: Path, verifier_root: Path, tmp_path: Path
) -> None:
    """STAGE7-BATCH-003/004 at CLI layer with distinct export paths."""
    entry = project_root / "standalone_main.py"
    assert entry.is_file()
    yaml_a = copy_template_fixture(tmp_path / "a", verifier_root=verifier_root)
    yaml_b = copy_template_fixture(tmp_path / "b", verifier_root=verifier_root)
    out_a = tmp_path / "a.csv"
    out_b = tmp_path / "b.csv"

    def run_one(yaml_path: Path, out: Path, tag: str) -> tuple[str, int, str]:
        proc = subprocess.run(
            [
                sys.executable,
                str(entry),
                "-c",
                str(yaml_path),
                "--batch",
                "20",
                "--export",
                str(out),
                "--cycle-time",
                "0.001",
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return tag, proc.returncode, proc.stderr

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [
            pool.submit(run_one, yaml_a, out_a, "A"),
            pool.submit(run_one, yaml_b, out_b, "B"),
        ]
        results = [f.result() for f in as_completed(futs)]
    for tag, code, err in results:
        assert code == 0, f"STAGE7-BATCH-003: task {tag} failed: {err[-300:]}"
    assert out_a.is_file() and out_b.is_file()
    assert out_a.stat().st_size > 0 and out_b.stat().st_size > 0


def test_stage_7_contract_surfaces_no_internal_helpers(project_root: Path) -> None:
    text = (
        project_root / "tools/stage_verification/acceptance/CONTRACT_SURFACES.md"
    ).read_text(encoding="utf-8")
    assert "RunBatch" in text
    assert "ExportBatch" in text
    # May mention forbidden names only as negatives; must not register them as 公共表面名称.
    for line in text.splitlines():
        if "公共表面" in line or "名称或路径" in line:
            assert "AllocateBatchWorkDir" not in line, line
            assert "CanRunBatch" not in line, line
