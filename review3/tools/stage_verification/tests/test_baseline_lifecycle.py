"""Baseline record / tamper / acceptance-mode tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.stage_verification.verifier import (
    StageVerifier,
    VerificationConfigurationError,
)


class BaselineLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "locked.txt").write_text("locked\n", encoding="utf-8")
        (self.root / "acceptance_test.py").write_text(
            "def test_contract():\n    assert True\n", encoding="utf-8"
        )
        (self.root / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "locked.txt", "acceptance_test.py", "product.py"],
            cwd=self.root,
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _manifest(self) -> dict:
        return {
            "schema_version": 1,
            "stage": 4,
            "name": "baseline-lifecycle",
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
                }
            ],
        }

    def _verifier(self) -> StageVerifier:
        manifest = self._manifest()
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "manifest.json"], cwd=self.root, check=True)
        return StageVerifier(self.root, manifest, path)

    def test_retrospective_and_prospective_modes_are_persisted(self) -> None:
        verifier = self._verifier()
        baseline = verifier.record_baseline(
            review_key="secret", acceptance_mode="prospective"
        )
        self.assertEqual("prospective", baseline["acceptance_mode"])
        loaded = json.loads(verifier.baseline_path.read_text(encoding="utf-8"))
        self.assertEqual("prospective", loaded["acceptance_mode"])
        result = verifier.verify()
        self.assertEqual("prospective", result.acceptance_mode)

    def test_invalid_acceptance_mode_rejected(self) -> None:
        verifier = self._verifier()
        with self.assertRaises(VerificationConfigurationError):
            verifier.record_baseline(review_key="secret", acceptance_mode="fake")

    def test_manifest_modified_after_baseline_rejected_before_command_execution(self) -> None:
        marker = self.root / "command-ran.txt"
        manifest = self._manifest()
        manifest["commands"][0]["argv"] = [
            "{python}",
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
        ]
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "manifest.json"], cwd=self.root, check=True)
        verifier = StageVerifier(self.root, manifest, path)
        verifier.record_baseline(review_key="secret", acceptance_mode="retrospective")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["name"] = "tampered"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(VerificationConfigurationError):
            verifier.verify()
        self.assertFalse(marker.exists())

    def test_baseline_fingerprint_tamper_detected(self) -> None:
        verifier = self._verifier()
        verifier.record_baseline(review_key="secret")
        baseline = json.loads(verifier.baseline_path.read_text(encoding="utf-8"))
        baseline["stage_name"] = "tampered"
        # Intentionally leave fingerprint stale.
        verifier.baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        with self.assertRaises(VerificationConfigurationError):
            verifier.verify()

    def test_recomputed_fingerprint_on_locked_digest_still_fails_verify(self) -> None:
        """Rewriting fingerprint after tampering locked digests does not hide drift."""
        verifier = self._verifier()
        verifier.record_baseline(review_key="secret")
        baseline = json.loads(verifier.baseline_path.read_text(encoding="utf-8"))
        baseline["locked_files"]["locked.txt"] = "0" * 64
        baseline["files"]["locked.txt"] = "0" * 64
        from tools.stage_verification.verifier import baseline_fingerprint

        baseline["fingerprint"] = baseline_fingerprint(baseline)
        verifier.baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        result = verifier.verify()
        self.assertEqual("FAIL", result.status)
        locked = next(c for c in result.checks if c.check_id == "locked_files")
        self.assertEqual("FAIL", locked.status)


if __name__ == "__main__":
    unittest.main()
