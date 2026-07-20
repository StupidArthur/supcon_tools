"""Shared fixtures for reviewer-owned Python acceptance suites."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.stage_verification.common.repo_layout import discover_repository_layout
from tools.stage_verification.verifier import PACKAGE_ROOT


@pytest.fixture(scope="session")
def project_root() -> Path:
    return discover_repository_layout(PACKAGE_ROOT).project_root


@pytest.fixture(scope="session")
def verifier_root() -> Path:
    return PACKAGE_ROOT
