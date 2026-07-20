"""Stage 2 reviewer acceptance: fixed SVG P&ID markers and no React-Flow template drawing."""

from __future__ import annotations

from pathlib import Path


def test_diagram_is_fixed_svg_not_react_flow(project_root: Path) -> None:
    diagram = (
        project_root
        / "config-tool"
        / "frontend"
        / "src"
        / "features"
        / "templates"
        / "secondOrderTank"
        / "SecondOrderTankDiagram.tsx"
    )
    text = diagram.read_text(encoding="utf-8")
    assert "data-testid=\"pid-diagram\"" in text or "data-testid='pid-diagram'" in text
    for test_id in ("source-flow", "valve-1", "lt-201", "pid2", "tank-2-sv-line"):
        assert test_id in text, f"missing diagram test id: {test_id}"
    assert 'label="Tank 1"' in text
    assert 'label="Tank 2"' in text
    assert "toLowerCase().replace(' ', '-')" in text or 'toLowerCase().replace(" ", "-")' in text
    assert "ReactFlow" not in text
    assert "@xyflow/react" not in text
    assert "当前为组态预览，不是实时值" in text


def test_stage_2_evidence_directory_exists(project_root: Path) -> None:
    evidence = project_root / "tools" / "stage_verification" / "evidence" / "stage_2"
    assert evidence.is_dir()


def test_stage_2_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_2/test_stage_2_acceptance.py",
        "config-tool/frontend/acceptance/stage_2/pid_diagram.acceptance.test.tsx",
        "config-tool/frontend/acceptance/stage_2/inspector.acceptance.test.tsx",
    ]
    missing = [path for path in required if not (project_root / path).is_file()]
    assert not missing, f"missing reviewer acceptance files: {missing}"
