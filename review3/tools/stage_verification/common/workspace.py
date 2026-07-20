"""Temporary workspace helpers for acceptance tests.

Tests must copy templates into tmp directories and must never write the built-in
``config/单阀门二阶水箱.yaml`` in place.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Built-in template that acceptance tests must not mutate in the worktree.
BUILTIN_SECOND_ORDER_TANK_YAML = "config/单阀门二阶水箱.yaml"
FIXTURE_TEMPLATES_DIRNAME = "templates"
DEFAULT_TEMPLATE_FIXTURE_NAME = "valid_second_order_tank.yaml"


class WorkspaceError(RuntimeError):
    """Raised when a temporary acceptance workspace cannot be prepared."""


def fixture_root(verifier_root: Path) -> Path:
    """Return ``tools/stage_verification/fixtures``."""
    return verifier_root / "fixtures"


def copy_template_fixture(
    destination_dir: Path,
    *,
    verifier_root: Path,
    fixture_name: str = DEFAULT_TEMPLATE_FIXTURE_NAME,
    destination_name: str | None = None,
) -> Path:
    """Copy a fixture YAML into *destination_dir* and return the new path."""
    source = fixture_root(verifier_root) / FIXTURE_TEMPLATES_DIRNAME / fixture_name
    if not source.is_file():
        raise WorkspaceError(f"Template fixture missing: {source}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / (destination_name or fixture_name)
    shutil.copy2(source, target)
    return target


def assert_not_builtin_template(path: Path, project_root: Path) -> None:
    """Refuse paths that resolve to the built-in template under *project_root*."""
    builtin = (project_root / BUILTIN_SECOND_ORDER_TANK_YAML).resolve()
    if path.resolve() == builtin:
        raise WorkspaceError(
            f"Acceptance tests must not write the built-in template: {builtin}"
        )


def assert_worktree_clean_of(
    project_root: Path,
    relative_paths: list[str],
) -> None:
    """Assert none of the relative paths exist under *project_root*."""
    leftovers = [
        relative
        for relative in relative_paths
        if (project_root / relative).exists()
    ]
    if leftovers:
        raise AssertionError(
            "Worktree pollution detected: " + ", ".join(leftovers)
        )
