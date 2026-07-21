"""Accepted checkpoint schema, finalize and verify-accepted tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.stage_verification.verifier import (
    StageVerifier,
    VerificationConfigurationError,
    validate_accepted_checkpoint,
)


class AcceptedCheckpointTests(unittest.TestCase):
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

    def _verifier(self, *, manual: bool = False) -> StageVerifier:
        gates = [
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
        ]
        if manual:
            gates.append({"id": "visual", "mode": "manual", "description": "visual"})
        manifest = {
            "schema_version": 1,
            "stage": 4,
            "name": "accepted",
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
            "gates": gates,
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "manifest.json"], cwd=self.root, check=True)
        # Accepted files are written under project tools/stage_verification/accepted.
        (self.root / "tools" / "stage_verification" / "accepted").mkdir(parents=True)
        return StageVerifier(self.root, manifest, path)

    def test_finalize_requires_manual_gates_when_present(self) -> None:
        verifier = self._verifier(manual=True)
        verifier.record_baseline(review_key="secret", acceptance_mode="retrospective")
        with self.assertRaises(VerificationConfigurationError):
            verifier.finalize(reviewer="alice", review_key="secret")
        verifier.record_attestation("visual", "alice", "ok", "secret")
        record = verifier.finalize(reviewer="alice", review_key="secret")
        validate_accepted_checkpoint(
            record,
            expected_stage=4,
            verifier_root=Path(__file__).resolve().parents[1],
        )
        self.assertEqual("retrospective", record["acceptance_mode"])

    def test_finalize_rejects_prospective_baseline(self) -> None:
        verifier = self._verifier(manual=False)
        verifier.record_baseline(review_key="secret", acceptance_mode="prospective")
        with self.assertRaises(VerificationConfigurationError) as ctx:
            verifier.finalize(reviewer="alice", review_key="secret")
        self.assertIn("prospective", str(ctx.exception).lower())

    def test_verify_accepted_detects_worktree_drift(self) -> None:
        verifier = self._verifier(manual=False)
        verifier.record_baseline(review_key="secret", acceptance_mode="retrospective")
        verifier.finalize(reviewer="alice", review_key="secret")
        verifier.verify_accepted(review_key="secret")
        (self.root / "product.py").write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaises(VerificationConfigurationError):
            verifier.verify_accepted(review_key="secret")

    def test_wrong_signature_rejected_when_key_provided(self) -> None:
        verifier = self._verifier(manual=False)
        verifier.record_baseline(review_key="secret")
        verifier.finalize(reviewer="alice", review_key="secret")
        with self.assertRaises(VerificationConfigurationError):
            verifier.verify_accepted(review_key="wrong-key")


if __name__ == "__main__":
    unittest.main()
