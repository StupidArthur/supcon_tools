"""Stage 0 reviewer acceptance: buildable baseline markers and legacy entry presence."""

from __future__ import annotations

from pathlib import Path


def test_stage_0_required_frontend_api_wrapper_exists(project_root: Path) -> None:
    api = project_root / "config-tool" / "frontend" / "src" / "lib" / "api.ts"
    text = api.read_text(encoding="utf-8")
    for symbol in (
        "componentApi",
        "configApi",
        "systemApi",
        "list:",
        "importYAML",
        "exportYAML",
        "validate",
        "loadCanvas",
        "saveCanvas",
        "getDataFactoryPath",
        "browseExe",
        "listConfigs",
        "start",
        "stop",
        "status",
        "openYAMLFile",
        "saveYAMLFile",
        "runBatch",
        "exportBatch",
    ):
        assert symbol in text, f"missing api wrapper surface: {symbol}"


def test_stage_0_legacy_entries_still_present(project_root: Path) -> None:
    app = (project_root / "config-tool" / "frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )
    toolbar = (
        project_root / "config-tool" / "frontend" / "src" / "components" / "Toolbar.tsx"
    ).read_text(encoding="utf-8")
    assert "SystemPanel" in app
    assert "SimulationPanel" in app
    assert "Palette" in app and "Canvas" in app and "PropertyPanel" in app
    assert "TemplateWorkspace" in app
    for label in ("二阶水箱模板", "系统管理", "仿真运行", "高级组态"):
        assert label in toolbar, f"missing toolbar entry: {label}"


def test_stage_0_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_0/test_stage_0_acceptance.py",
        "config-tool/frontend/acceptance/stage_0/api_wrapper.acceptance.test.ts",
        "config-tool/frontend/acceptance/stage_0/legacy_views.acceptance.test.tsx",
    ]
    missing = [path for path in required if not (project_root / path).is_file()]
    assert not missing, f"missing reviewer acceptance files: {missing}"
