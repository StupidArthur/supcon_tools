"""Attestation integrity tests (HMAC, evidence, final-tree binding)."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.stage_verification.common.hashing import canonical_json, sha256_bytes
from tools.stage_verification.verifier import (
    StageVerifier,
    VerificationConfigurationError,
)


class AttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "locked.txt").write_text("locked\n", encoding="utf-8")
        (self.root / "acceptance_test.py").write_text(
            "def test_contract():\n    assert True\n", encoding="utf-8"
        )
        (self.root / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "evidence.txt").write_text("screenshot\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "locked.txt", "acceptance_test.py", "product.py", "evidence.txt"],
            cwd=self.root,
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _verifier(self) -> StageVerifier:
        manifest = {
            "schema_version": 1,
            "stage": 2,
            "name": "attest",
            "required_documents": ["locked.txt"],
            "allowed_paths": ["product.py", "evidence.txt"],
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
                {"id": "visual", "mode": "manual", "description": "visual"},
            ],
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        subprocess.run(["git", "add", "manifest.json"], cwd=self.root, check=True)
        return StageVerifier(self.root, manifest, path)

    def test_evidence_file_tamper_invalidates_attestation(self) -> None:
        verifier = self._verifier()
        verifier.record_baseline(review_key="secret")
        verifier.record_attestation("visual", "rev", "evidence.txt", "secret")
        self.assertEqual("PASS", verifier.verify(review_key="secret").status)
        (self.root / "evidence.txt").write_text("tampered\n", encoding="utf-8")
        self.assertEqual("NEEDS_MANUAL", verifier.verify(review_key="secret").status)

    def test_plain_sha_rehash_cannot_replace_hmac_signature(self) -> None:
        verifier = self._verifier()
        verifier.record_baseline(review_key="secret")
        verifier.record_attestation("visual", "rev", "notes", "secret")
        doc = json.loads(verifier.attestation_path.read_text(encoding="utf-8"))
        record = doc["attestations"][0]
        payload = {key: value for key, value in record.items() if key != "signature"}
        payload["reviewer"] = "attacker"
        # Attacker recomputes a plain SHA over the payload instead of HMAC.
        fake_sig = sha256_bytes(canonical_json(payload))
        record.update(payload)
        record["signature"] = fake_sig
        doc["attestations"] = [record]
        verifier.attestation_path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual("NEEDS_MANUAL", verifier.verify(review_key="secret").status)

    def test_wrong_key_cannot_attest(self) -> None:
        verifier = self._verifier()
        verifier.record_baseline(review_key="secret")
        with self.assertRaises(VerificationConfigurationError):
            verifier.record_attestation("visual", "rev", "notes", "wrong")


if __name__ == "__main__":
    unittest.main()
