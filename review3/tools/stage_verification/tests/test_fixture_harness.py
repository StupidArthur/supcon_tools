"""Tests for shared fixtures and temporary workspace helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.stage_verification.common.fixtures import (
    assert_runtime_v1_snapshot_contract,
    assert_runtime_v1_status_contract,
    load_runtime_v1_fixture,
)
from tools.stage_verification.common.workspace import (
    BUILTIN_SECOND_ORDER_TANK_YAML,
    WorkspaceError,
    assert_not_builtin_template,
    assert_worktree_clean_of,
    copy_template_fixture,
)
from tools.stage_verification.verifier import PACKAGE_ROOT


class FixtureHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier_root = PACKAGE_ROOT
        cls.project_root = PACKAGE_ROOT.parents[1]

    def test_runtime_v1_status_and_snapshot_contracts(self) -> None:
        status = load_runtime_v1_fixture(self.verifier_root, "status.json")
        snapshot = load_runtime_v1_fixture(self.verifier_root, "snapshot.json")
        assert_runtime_v1_status_contract(status)
        assert_runtime_v1_snapshot_contract(snapshot)
        heartbeat = load_runtime_v1_fixture(self.verifier_root, "heartbeat.json")
        self.assertEqual("heartbeat", heartbeat["type"])
        empty = load_runtime_v1_fixture(self.verifier_root, "empty_snapshot.json")
        self.assertEqual({}, empty)

    def test_copy_template_to_tmp_and_refuse_builtin_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            copied = copy_template_fixture(
                destination,
                verifier_root=self.verifier_root,
                destination_name="unicode_二阶水箱.yaml",
            )
            self.assertTrue(copied.is_file())
            self.assertIn("二阶水箱", copied.name)
            builtin = self.project_root / BUILTIN_SECOND_ORDER_TANK_YAML
            with self.assertRaises(WorkspaceError):
                assert_not_builtin_template(builtin, self.project_root)
            assert_not_builtin_template(copied, self.project_root)
            assert_worktree_clean_of(
                self.project_root,
                ["tools/stage_verification/fixtures/_should_not_exist.yaml"],
            )


if __name__ == "__main__":
    unittest.main()
