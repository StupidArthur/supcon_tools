from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.stage_verification.verifier import (
    StageVerifier,
    VerificationConfigurationError,
    load_manifest,
    normalize_path,
)


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[3]

    def test_all_stage_manifests_are_valid(self) -> None:
        for stage in range(9):
            manifest, path = load_manifest(self.repo_root, stage)
            self.assertEqual(stage, manifest["stage"])
            self.assertTrue(path.is_file())
            self.assertTrue(manifest["commands"])
            self.assertTrue(manifest["gates"])

    def test_dot_prefixed_paths_are_not_mangled(self) -> None:
        self.assertEqual(".gitignore", normalize_path(".gitignore"))
        self.assertEqual("a/b", normalize_path("./a\\b"))


class StageVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "locked.txt").write_text("locked\n", encoding="utf-8")
        (self.root / "acceptance_test.py").write_text("def test_contract():\n    assert True\n", encoding="utf-8")
        (self.root / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "locked.txt", "acceptance_test.py", "product.py"],
            cwd=self.root,
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _manifest(self, *, manual: bool = False, command: list[str] | None = None) -> dict:
        gates = [
            {
                "id": "automated",
                "mode": "automated",
                "description": "automated gate",
                "checks": [
                    "required_documents",
                    "required_paths",
                    "preserved_paths",
                    "manifest_locked",
                    "locked_files",
                    "changed_paths_allowed",
                    "forbidden_paths",
                    "forbidden_symbols",
                    "command:unit",
                ],
            }
        ]
        if manual:
            gates.append({"id": "visual", "mode": "manual", "description": "visual review"})
        return {
            "schema_version": 1,
            "stage": 0,
            "name": "test",
            "required_documents": ["locked.txt"],
            "allowed_paths": ["product.py"],
            "forbidden_paths": ["never/**"],
            "preserved_paths": ["locked.txt"],
            "required_paths": ["product.py"],
            "forbidden_symbols": [
                {
                    "id": "next_stage",
                    "path_globs": ["*.py"],
                    "pattern": "NEXT_STAGE",
                }
            ],
            "locked_paths": ["locked.txt", "manifest.json"],
            "locked_acceptance_paths": ["acceptance_test.py"],
            "commands": [
                {
                    "id": "unit",
                    "cwd": ".",
                    "argv": command or ["{python}", "-c", "print('ok')"],
                    "timeout_seconds": 5,
                }
            ],
            "git_diff_check": False,
            "gates": gates,
        }

    def _verifier(self, manifest: dict) -> StageVerifier:
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "manifest.json"], cwd=self.root, check=True)
        return StageVerifier(self.root, manifest, path)

    def test_baseline_allows_only_current_stage_changes(self) -> None:
        verifier = self._verifier(self._manifest())
        verifier.record_baseline(review_key="review-secret")
        (self.root / "product.py").write_text("VALUE = 2\n", encoding="utf-8")
        result = verifier.verify()
        self.assertEqual("PASS", result.status)
        changed = next(c for c in result.checks if c.check_id == "changed_paths_allowed")
        self.assertEqual(["product.py"], changed.details["changed"])

    def test_locked_file_change_fails(self) -> None:
        verifier = self._verifier(self._manifest())
        verifier.record_baseline(review_key="review-secret")
        (self.root / "locked.txt").write_text("tampered\n", encoding="utf-8")
        result = verifier.verify()
        self.assertEqual("FAIL", result.status)
        locked = next(c for c in result.checks if c.check_id == "locked_files")
        self.assertEqual("FAIL", locked.status)

    def test_only_new_forbidden_symbol_occurrences_fail(self) -> None:
        (self.root / "product.py").write_text("NEXT_STAGE = 'legacy'\n", encoding="utf-8")
        verifier = self._verifier(self._manifest())
        verifier.record_baseline(review_key="review-secret")
        (self.root / "product.py").write_text(
            "NEXT_STAGE = 'legacy'\nNEXT_STAGE = 'new'\n", encoding="utf-8"
        )
        result = verifier.verify()
        symbols = next(c for c in result.checks if c.check_id == "forbidden_symbols")
        self.assertEqual("FAIL", symbols.status)
        self.assertEqual(1, symbols.details["hits"][0]["baseline_count"])
        self.assertEqual(2, symbols.details["hits"][0]["current_count"])

    def test_manual_gate_needs_trusted_reviewer_attestation(self) -> None:
        verifier = self._verifier(self._manifest(manual=True))
        verifier.record_baseline(review_key="review-secret")
        self.assertEqual("NEEDS_MANUAL", verifier.verify().status)
        with self.assertRaises(VerificationConfigurationError):
            verifier.record_attestation("visual", "agent", "claim", "wrong-secret")
        verifier.record_attestation("visual", "reviewer", "screenshot.png", "review-secret")
        self.assertEqual("NEEDS_MANUAL", verifier.verify().status)
        self.assertEqual("PASS", verifier.verify(review_key="review-secret").status)

    def test_command_timeout_is_a_failure(self) -> None:
        command = ["{python}", "-c", "import time; time.sleep(0.2)"]
        manifest = self._manifest(command=command)
        manifest["commands"][0]["timeout_seconds"] = 0.01
        verifier = self._verifier(manifest)
        verifier.record_baseline(review_key="review-secret")
        result = verifier.verify()
        command_result = next(c for c in result.checks if c.check_id == "command:unit")
        self.assertEqual("FAIL", command_result.status)
        self.assertIn("timeout", command_result.summary)

    def test_missing_baseline_is_configuration_error(self) -> None:
        verifier = self._verifier(self._manifest())
        with self.assertRaises(VerificationConfigurationError):
            verifier.verify()

    def test_direct_baseline_tamper_is_detected(self) -> None:
        verifier = self._verifier(self._manifest())
        verifier.record_baseline(review_key="review-secret")
        baseline = json.loads(verifier.baseline_path.read_text(encoding="utf-8"))
        baseline["stage_name"] = "tampered"
        verifier.baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        with self.assertRaises(VerificationConfigurationError):
            verifier.verify()

    def test_reviewer_key_is_not_inherited_by_commands(self) -> None:
        command = [
            "{python}",
            "-c",
            "import os,sys; sys.exit(9 if os.getenv('STAGE_VERIFICATION_REVIEW_KEY') else 0)",
        ]
        verifier = self._verifier(self._manifest(command=command))
        verifier.record_baseline(review_key="review-secret")
        with patch.dict(os.environ, {"STAGE_VERIFICATION_REVIEW_KEY": "review-secret"}):
            result = verifier.verify(review_key="review-secret")
        command_result = next(c for c in result.checks if c.check_id == "command:unit")
        self.assertEqual("PASS", command_result.status)

    def test_manifest_tamper_fails_before_running_commands(self) -> None:
        marker = self.root / "command-ran.txt"
        command = [
            "{python}",
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
        ]
        verifier = self._verifier(self._manifest(command=command))
        verifier.record_baseline(review_key="review-secret")
        manifest_data = json.loads(verifier.manifest_file.read_text(encoding="utf-8"))
        manifest_data["name"] = "tampered manifest"
        verifier.manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")
        with self.assertRaises(VerificationConfigurationError):
            verifier.verify()
        self.assertFalse(marker.exists())

    def test_locked_acceptance_test_change_fails(self) -> None:
        verifier = self._verifier(self._manifest())
        verifier.record_baseline(review_key="review-secret")
        (self.root / "acceptance_test.py").write_text(
            "def test_contract():\n    assert False\n", encoding="utf-8"
        )
        result = verifier.verify()
        acceptance = next(
            c for c in result.checks if c.check_id == "locked_acceptance_files"
        )
        self.assertEqual("FAIL", acceptance.status)

    def test_required_path_must_exist_in_worktree(self) -> None:
        verifier = self._verifier(self._manifest())
        verifier.record_baseline(review_key="review-secret")
        (self.root / "product.py").unlink()
        result = verifier.verify()
        required = next(c for c in result.checks if c.check_id == "required_paths")
        self.assertEqual("FAIL", required.status)

    def test_untracked_file_whitespace_is_checked_against_baseline(self) -> None:
        manifest = self._manifest()
        manifest["allowed_paths"] = ["*.py"]
        manifest["git_diff_check"] = True
        verifier = self._verifier(manifest)
        verifier.record_baseline(review_key="review-secret")
        (self.root / "new_test.py").write_text("VALUE = 1   \n", encoding="utf-8")
        result = verifier.verify()
        hygiene = next(c for c in result.checks if c.check_id == "git_diff_check")
        self.assertEqual("FAIL", hygiene.status)
        self.assertEqual("new_test.py", hygiene.details["new_issues"][0]["path"])

    def test_attestation_expires_when_final_tree_changes(self) -> None:
        verifier = self._verifier(self._manifest(manual=True))
        verifier.record_baseline(review_key="review-secret")
        verifier.record_attestation("visual", "reviewer", "reviewed", "review-secret")
        self.assertEqual("PASS", verifier.verify(review_key="review-secret").status)
        (self.root / "product.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertEqual(
            "NEEDS_MANUAL", verifier.verify(review_key="review-secret").status
        )


if __name__ == "__main__":
    unittest.main()
