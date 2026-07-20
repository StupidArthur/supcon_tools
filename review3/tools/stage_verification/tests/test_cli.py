"""CLI lifecycle smoke tests for verify_stage / verify_all."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.stage_verification import verify_all, verify_stage
from tools.stage_verification.verifier import (
    EXIT_CONFIGURATION,
    EXIT_OK,
    StageVerifier,
)


class CliLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[3]

    def test_verify_stage_help(self) -> None:
        # argparse --help exits via SystemExit; invoke parser directly instead.
        parser = verify_stage.build_parser()
        help_text = parser.format_help()
        self.assertIn("--record-baseline", help_text)
        self.assertIn("--finalize", help_text)
        self.assertIn("--verify-accepted", help_text)
        self.assertIn("--acceptance-mode", help_text)

    def test_verify_all_help_and_check_config(self) -> None:
        parser = verify_all.build_parser()
        help_text = parser.format_help()
        self.assertIn("--check-config", help_text)
        self.assertIn("--accepted-through", help_text)
        code = verify_all.main(
            ["--check-config", "--repo-root", str(self.project_root)]
        )
        self.assertEqual(EXIT_OK, code)

    def test_json_output_inside_project_outside_state_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            code = verify_stage.main(
                [
                    "0",
                    "--repo-root",
                    str(self.project_root),
                    "--json-output",
                    "pollution.json",
                ]
            )
        self.assertEqual(EXIT_CONFIGURATION, code)

    def test_record_verify_attest_finalize_roundtrip_in_temp_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "locked.txt").write_text("locked\n", encoding="utf-8")
            (root / "acceptance_test.py").write_text(
                "def test_contract():\n    assert True\n", encoding="utf-8"
            )
            (root / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "stage": 0,
                "name": "cli-roundtrip",
                "required_documents": ["locked.txt"],
                "allowed_paths": ["product.py"],
                "forbidden_paths": ["never/**"],
                "preserved_paths": ["locked.txt"],
                "required_paths": ["product.py"],
                "forbidden_symbols": [],
                "locked_paths": ["locked.txt", "manifest.json"],
                "locked_acceptance_paths": ["acceptance_test.py"],
                "commands": [
                    {
                        "id": "unit",
                        "cwd": ".",
                        "argv": ["{python}", "-c", "print('ok')"],
                        "timeout_seconds": 5,
                    }
                ],
                "git_diff_check": False,
                "gates": [
                    {
                        "id": "automated",
                        "mode": "automated",
                        "description": "auto",
                        "checks": [
                            "required_documents",
                            "required_paths",
                            "preserved_paths",
                            "manifest_locked",
                            "locked_files",
                            "locked_acceptance_files",
                            "changed_paths_allowed",
                            "forbidden_paths",
                            "forbidden_symbols",
                            "command:unit",
                        ],
                    },
                    {
                        "id": "visual",
                        "mode": "manual",
                        "description": "manual review",
                    },
                ],
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            subprocess.run(
                ["git", "add", "locked.txt", "acceptance_test.py", "product.py", "manifest.json"],
                cwd=root,
                check=True,
            )
            (root / "tools" / "stage_verification" / "accepted").mkdir(parents=True)
            verifier = StageVerifier(root, manifest, path)
            baseline = verifier.record_baseline(
                review_key="secret", acceptance_mode="retrospective"
            )
            self.assertEqual("retrospective", baseline["acceptance_mode"])
            self.assertEqual("NEEDS_MANUAL", verifier.verify().status)
            verifier.record_attestation("visual", "alice", "looks good", "secret")
            self.assertEqual("PASS", verifier.verify(review_key="secret").status)
            accepted = verifier.finalize(reviewer="alice", review_key="secret")
            self.assertEqual("retrospective", accepted["acceptance_mode"])
            self.assertTrue(verifier.accepted_path.is_file())
            again = verifier.verify_accepted(review_key="secret")
            self.assertEqual(accepted["signature"], again["signature"])


if __name__ == "__main__":
    unittest.main()
