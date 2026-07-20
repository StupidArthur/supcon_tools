"""Repository layout discovery: Git root vs project root vs verifier root.

The monorepo may contain sibling projects under one Git root. Stage verification
always scopes paths, snapshots and command cwd checks to the *project* root
(``review3/``), never to the entire Git working tree.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .hashing import normalize_path

# Relative paths that must exist under a valid review3 project root.
PROJECT_MARKERS: tuple[str, ...] = (
    "tools/stage_verification/manifests",
    "todo/second_order_tank_implementation_playbook.md",
    "config-tool",
)

# A directory named ".git" is not enough: workspaces may contain a fake/partial
# `.git` folder (e.g. tooling metadata). Require a real Git repository.
_GIT_HEAD_NAMES: tuple[str, ...] = ("HEAD",)


class LayoutError(RuntimeError):
    """Raised when project/Git roots cannot be resolved reliably."""


@dataclass(frozen=True)
class RepositoryLayout:
    """Resolved roots for one verification session.

    Attributes:
        git_root: Result of ``git rev-parse --show-toplevel``.
        project_root: Directory containing stage_verification + playbook markers.
        verifier_root: ``project_root/tools/stage_verification``.
    """

    git_root: Path
    project_root: Path
    verifier_root: Path

    @property
    def project_prefix(self) -> str:
        """Git-relative prefix of the project (e.g. ``review3/``) or empty."""
        try:
            relative = self.project_root.resolve().relative_to(self.git_root.resolve())
        except ValueError as exc:
            raise LayoutError(
                f"Project root {self.project_root} is not inside Git root {self.git_root}"
            ) from exc
        text = normalize_path(relative)
        if text in ("", "."):
            return ""
        return text if text.endswith("/") else f"{text}/"

    def to_project_relative(self, git_relative_path: str) -> str | None:
        """Map a Git-root-relative path to a project-relative path, or None."""
        normalized = normalize_path(git_relative_path)
        prefix = self.project_prefix
        if not prefix:
            return normalized
        if not normalized.startswith(prefix):
            return None
        return normalized[len(prefix) :]


def has_project_markers(path: Path) -> bool:
    """Return True when *path* contains every required project marker."""
    root = path.resolve()
    for marker in PROJECT_MARKERS:
        candidate = root / marker
        if not candidate.exists():
            return False
    return True


def assert_project_markers(path: Path) -> None:
    """Raise LayoutError listing missing markers under *path*."""
    root = path.resolve()
    missing = [marker for marker in PROJECT_MARKERS if not (root / marker).exists()]
    if missing:
        raise LayoutError(
            "Explicit --repo-root must contain project markers; missing: "
            + ", ".join(missing)
        )


def is_real_git_dir(path: Path) -> bool:
    """Return True when *path* looks like a usable Git directory or gitfile."""
    if path.is_file():
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return content.startswith("gitdir:")
    if not path.is_dir():
        return False
    return any((path / name).exists() for name in _GIT_HEAD_NAMES)


def resolve_git_root(start: Path) -> Path:
    """Resolve the true Git toplevel via ``git rev-parse``, not directory walk.

    Falling back to walking for ``.git`` is unsafe when a non-repository
    ``.git`` directory exists under the project root.
    """
    start = start.resolve()
    process = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start if start.is_dir() else start.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        raise LayoutError(
            "Cannot resolve Git root via git rev-parse: "
            + (process.stderr or process.stdout or "unknown error").strip()
        )
    return Path(process.stdout.strip()).resolve()


def find_project_root(start: Path) -> Path:
    """Walk upward from *start* until project markers are found."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if has_project_markers(candidate):
            return candidate
    raise LayoutError(
        f"Cannot locate project root (markers {PROJECT_MARKERS}) from {start}"
    )


def discover_repository_layout(
    start: Path | None = None,
    *,
    explicit_project_root: Path | None = None,
) -> RepositoryLayout:
    """Discover Git / project / verifier roots.

    Args:
        start: Path used when searching upward for project markers.
        explicit_project_root: When set (``--repo-root``), must contain markers.
    """
    if explicit_project_root is not None:
        project_root = explicit_project_root.resolve()
        assert_project_markers(project_root)
    else:
        if start is None:
            raise LayoutError("start path is required when --repo-root is omitted")
        project_root = find_project_root(start)

    git_root = resolve_git_root(project_root)
    # Ensure project is inside the Git working tree (prefix filter depends on it).
    try:
        project_root.resolve().relative_to(git_root.resolve())
    except ValueError as exc:
        raise LayoutError(
            f"Project root {project_root} is outside Git root {git_root}"
        ) from exc

    verifier_root = project_root / "tools" / "stage_verification"
    if not verifier_root.is_dir():
        raise LayoutError(f"Verifier root missing: {verifier_root}")

    return RepositoryLayout(
        git_root=git_root,
        project_root=project_root,
        verifier_root=verifier_root,
    )


def layout_for_flat_workspace(root: Path) -> RepositoryLayout:
    """Build a layout where Git root equals project root (unit-test helper).

    Creates no files; caller must ensure *root* is a real Git working tree.
    """
    resolved = root.resolve()
    return RepositoryLayout(
        git_root=resolved,
        project_root=resolved,
        verifier_root=resolved / "tools" / "stage_verification",
    )
