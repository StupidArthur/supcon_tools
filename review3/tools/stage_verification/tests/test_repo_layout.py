"""Tests for Git-root vs project-root layout discovery."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.stage_verification.common.repo_layout import (
    LayoutError,
    discover_repository_layout,
    has_project_markers,
)
from tools.stage_verification.verifier import (
    capture_snapshot,
    load_manifest,
    manifest_path,
)


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)


def _write_project_markers(project: Path) -> None:
    manifests = project / "tools" / "stage_verification" / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (project / "todo").mkdir(parents=True, exist_ok=True)
    (project / "todo" / "second_order_tank_implementation_playbook.md").write_text(
        "# playbook\n", encoding="utf-8"
    )
    (project / "config-tool").mkdir(parents=True, exist_ok=True)
    (project / "config-tool" / ".keep").write_text("x\n", encoding="utf-8")


class RepoLayoutTests(unittest.TestCase):
    def test_project_root_can_be_below_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            git_root = Path(tmp)
            _init_git(git_root)
            project = git_root / "review3"
            project.mkdir()
            _write_project_markers(project)
            (git_root / "sibling").mkdir()
            (git_root / "sibling" / "other.txt").write_text("sibling\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "review3", "sibling"],
                cwd=git_root,
                check=True,
            )
            layout = discover_repository_layout(
                project / "tools" / "stage_verification",
            )
            self.assertEqual(git_root.resolve(), layout.git_root)
            self.assertEqual(project.resolve(), layout.project_root)
            self.assertEqual("review3/", layout.project_prefix)

    def test_explicit_repo_root_must_contain_project_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp)
            _init_git(bad)
            with self.assertRaises(LayoutError):
                discover_repository_layout(explicit_project_root=bad)

    def test_manifest_path_is_resolved_from_project_root(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        layout = discover_repository_layout(explicit_project_root=project_root)
        path = manifest_path(layout.project_root, 0)
        self.assertTrue(str(path).replace("\\", "/").endswith(
            "tools/stage_verification/manifests/stage_0.json"
        ))
        self.assertTrue(path.is_file())
        data, loaded = load_manifest(layout.project_root, 0, layout=layout)
        self.assertEqual(0, data["stage"])
        self.assertEqual(path.resolve(), loaded.resolve())

    def test_snapshot_does_not_include_sibling_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            git_root = Path(tmp)
            _init_git(git_root)
            project = git_root / "review3"
            project.mkdir()
            _write_project_markers(project)
            (project / "inside.txt").write_text("in\n", encoding="utf-8")
            (git_root / "sibling").mkdir()
            (git_root / "sibling" / "secret.txt").write_text("out\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=git_root, check=True)
            layout = discover_repository_layout(explicit_project_root=project)
            snapshot = capture_snapshot(layout)
            self.assertIn("inside.txt", snapshot)
            self.assertTrue(
                any(path.startswith("todo/") for path in snapshot),
                msg=sorted(snapshot),
            )
            self.assertFalse(any("sibling" in path for path in snapshot))
            self.assertFalse(any(path.endswith("secret.txt") for path in snapshot))

    def test_windows_backslash_paths(self) -> None:
        from tools.stage_verification.common.hashing import normalize_path

        self.assertEqual("tools/stage_verification/x", normalize_path(r"tools\stage_verification\x"))
        self.assertEqual(".gitignore", normalize_path(".gitignore"))

    def test_unicode_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            git_root = Path(tmp) / "工程根"
            git_root.mkdir()
            _init_git(git_root)
            project = git_root / "二阶水箱项目"
            project.mkdir()
            _write_project_markers(project)
            (project / "unicode_文件.txt").write_text("ok\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=git_root, check=True)
            layout = discover_repository_layout(explicit_project_root=project)
            snapshot = capture_snapshot(layout)
            self.assertIn("unicode_文件.txt", snapshot)
            self.assertEqual(project.resolve(), layout.project_root)

    def test_fake_dot_git_directory_does_not_become_git_root(self) -> None:
        """A non-repository `.git` folder under the project must not win discovery."""
        project_root = Path(__file__).resolve().parents[3]
        fake_git = project_root / ".git"
        self.assertTrue(fake_git.exists())
        # Not a real git dir (no HEAD); discovery must still use git rev-parse.
        layout = discover_repository_layout(explicit_project_root=project_root)
        self.assertEqual(project_root.resolve(), layout.project_root)
        self.assertNotEqual(layout.git_root, layout.project_root)
        self.assertTrue(has_project_markers(layout.project_root))


if __name__ == "__main__":
    unittest.main()
