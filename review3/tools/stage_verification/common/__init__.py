"""Shared primitives for the stage verification infrastructure.

Public API surface for other verifier modules:
- RepositoryLayout / discover_repository_layout / PROJECT_MARKERS
- hashing helpers (sha256_*, canonical_json, normalize_path)
- terminate_process_tree
- result dataclasses and exit codes
"""

from .hashing import (
    canonical_json,
    normalize_path,
    path_matches,
    sha256_bytes,
    sha256_file,
)
from .process import terminate_process_tree
from .repo_layout import (
    PROJECT_MARKERS,
    RepositoryLayout,
    discover_repository_layout,
    resolve_git_root,
)
from .result import (
    EXIT_CONFIGURATION,
    EXIT_FAILED,
    EXIT_NEEDS_MANUAL,
    EXIT_OK,
    CheckResult,
    GateResult,
    VerificationResult,
)

__all__ = [
    "PROJECT_MARKERS",
    "RepositoryLayout",
    "EXIT_CONFIGURATION",
    "EXIT_FAILED",
    "EXIT_NEEDS_MANUAL",
    "EXIT_OK",
    "CheckResult",
    "GateResult",
    "VerificationResult",
    "canonical_json",
    "discover_repository_layout",
    "normalize_path",
    "path_matches",
    "resolve_git_root",
    "sha256_bytes",
    "sha256_file",
    "terminate_process_tree",
]
