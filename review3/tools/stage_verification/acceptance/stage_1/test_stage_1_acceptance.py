"""Stage 1 reviewer acceptance: YAML round-trip compatibility with Python DSLParser."""

from __future__ import annotations

import shutil
from pathlib import Path

from tools.stage_verification.common.workspace import copy_template_fixture


def test_fixture_yaml_parses_as_second_order_tank_topology(
    project_root: Path, verifier_root: Path, tmp_path: Path
) -> None:
    copied = copy_template_fixture(tmp_path, verifier_root=verifier_root)
    # Import inside test so collection stays healthy if DSL is unavailable in other suites.
    from controller.parser import DSLParser

    result = DSLParser().parse_file(str(copied))
    # DSLParser may reorder execute_first programs for runtime; topology membership is required.
    names = {prog.name for prog in result.program}
    assert names == {"source_flow", "valve_1", "tank_1", "tank_2", "pid2"}
    types = {prog.name: prog.type for prog in result.program}
    assert types["valve_1"] == "VALVE"
    assert types["tank_1"] == "CYLINDRICAL_TANK"
    assert types["tank_2"] == "CYLINDRICAL_TANK"
    assert types["pid2"] == "PID"
    # YAML source order must still list programs in declaration order.
    raw = copied.read_text(encoding="utf-8")
    positions = [raw.index(f"name: {name}") for name in ("source_flow", "valve_1", "tank_1", "tank_2", "pid2")]
    assert positions == sorted(positions)


def test_unicode_fixture_path_parses(
    project_root: Path, verifier_root: Path, tmp_path: Path
) -> None:
    unicode_dir = tmp_path / "验收目录"
    unicode_dir.mkdir()
    copied = copy_template_fixture(
        unicode_dir,
        verifier_root=verifier_root,
        fixture_name="unicode_二阶水箱.yaml",
        destination_name="二阶水箱.yaml",
    )
    from controller.parser import DSLParser

    result = DSLParser().parse_file(str(copied))
    assert any(prog.name == "tank_2" for prog in result.program)


def test_builtin_template_is_not_mutated_by_acceptance_copy(
    project_root: Path, verifier_root: Path, tmp_path: Path
) -> None:
    builtin = project_root / "config" / "单阀门二阶水箱.yaml"
    before = builtin.read_bytes()
    copied = copy_template_fixture(tmp_path, verifier_root=verifier_root)
    copied.write_text(copied.read_text(encoding="utf-8") + "\n# acceptance touch\n", encoding="utf-8")
    assert builtin.read_bytes() == before
    assert copied.resolve() != builtin.resolve()


def test_stage_1_reviewer_acceptance_files_exist(project_root: Path) -> None:
    required = [
        "tools/stage_verification/acceptance/stage_1/test_stage_1_acceptance.py",
        "config-tool/acceptance/stage_1/template_service_acceptance_test.go",
        "config-tool/frontend/acceptance/stage_1/template_store.acceptance.test.ts",
    ]
    missing = [path for path in required if not (project_root / path).is_file()]
    assert not missing, f"missing reviewer acceptance files: {missing}"
