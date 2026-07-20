"""Negative and positive tests for manifest JSON Schema + cross-field rules."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.stage_verification.verifier import (
    VerificationConfigurationError,
    load_manifest,
    validate_manifest,
)


class ManifestSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[3]
        cls.base, _ = load_manifest(cls.project_root, 0)

    def _validate(self, data: dict) -> None:
        validate_manifest(
            data,
            expected_stage=data.get("stage", 0),
            project_root=self.project_root,
        )

    def test_all_stage_manifests_validate_against_schema(self) -> None:
        for stage in range(9):
            data, path = load_manifest(self.project_root, stage)
            self.assertEqual(stage, data["stage"])
            self.assertTrue(path.is_file())

    def test_unknown_manifest_property_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["unexpected_field"] = True
        with self.assertRaises(VerificationConfigurationError):
            self._validate(data)

    def test_duplicate_command_id_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["commands"] = [
            data["commands"][0],
            {**data["commands"][0], "id": data["commands"][0]["id"]},
        ]
        with self.assertRaises(VerificationConfigurationError) as ctx:
            self._validate(data)
        self.assertIn("Duplicate command id", str(ctx.exception))

    def test_duplicate_gate_id_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        first = data["gates"][0]
        data["gates"] = [first, {**first}]
        with self.assertRaises(VerificationConfigurationError) as ctx:
            self._validate(data)
        self.assertIn("Duplicate gate id", str(ctx.exception))

    def test_missing_locked_acceptance_paths_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["locked_acceptance_paths"] = []
        with self.assertRaises(VerificationConfigurationError):
            self._validate(data)

    def test_invalid_stage_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["stage"] = 99
        with self.assertRaises(VerificationConfigurationError):
            self._validate(data)

    def test_unknown_gate_check_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["gates"][0]["checks"] = ["not_a_real_check"]
        with self.assertRaises(VerificationConfigurationError) as ctx:
            self._validate(data)
        self.assertIn("unknown checks", str(ctx.exception))

    def test_cwd_path_traversal_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["commands"][0]["cwd"] = "../"
        with self.assertRaises(VerificationConfigurationError) as ctx:
            self._validate(data)
        self.assertIn("escapes project root", str(ctx.exception))

    def test_manual_gate_rejects_checks_field(self) -> None:
        data = copy.deepcopy(self.base)
        data["gates"].append(
            {
                "id": "visual",
                "mode": "manual",
                "description": "manual",
                "checks": ["required_documents"],
            }
        )
        with self.assertRaises(VerificationConfigurationError) as ctx:
            self._validate(data)
        self.assertIn("automated-only", str(ctx.exception))

    def test_allowed_forbidden_overlap_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["allowed_paths"] = ["shared/**"]
        data["forbidden_paths"] = ["shared/**", "other/**"]
        with self.assertRaises(VerificationConfigurationError) as ctx:
            self._validate(data)
        self.assertIn("conflict", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
