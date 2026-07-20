"""Stage 3 reviewer acceptance: managed process entry points and reviewer file presence."""

from __future__ import annotations

from pathlib import Path


def test_stage_3_system_binding_source_exists(project_root: Path) -> None:
    system_go = project_root / "config-tool" / "internal" / "bindings" / "system.go"
    text = system_go.read_text(encoding="utf-8")
    for symbol in (
        "func (b *SystemBinding) Start",
        "func (b *SystemBinding) Stop",
        "func (b *SystemBinding) Cleanup",
        "func BuildArgs",
        "APIReady",
        "RuntimeName",
        "ConfigHash",
    ):
        assert symbol in text, f"missing system binding surface: {symbol}"


def test_stage_3_runtime_toolbar_state_machine_markers(project_root: Path) -> None:
    toolbar = (
        project_root
        / "config-tool"
        / "frontend"
        / "src"
        / "features"
        / "templates"
        / "RuntimeToolbar.tsx"
    )
    text = toolbar.read_text(encoding="utf-8")
    for state in ("STARTING", "STOPPING", "SIMULATION_RUNNING", "STOPPED_EDITING", "ERROR"):
        assert state in text, f"missing runtime state: {state}"
    assert "setRunningIdentity" in text
    assert "configHash" in text or "contentHash" in text
    assert "startedAt" in text


def test_stage_3_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_3/test_stage_3_acceptance.py",
        "config-tool/acceptance/stage_3/system_binding_acceptance_test.go",
        "config-tool/frontend/acceptance/stage_3/runtime_toolbar_state.acceptance.test.tsx",
    ]
    missing = [path for path in required if not (project_root / path).is_file()]
    assert not missing, f"missing reviewer acceptance files: {missing}"
