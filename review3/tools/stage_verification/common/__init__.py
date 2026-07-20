"""Shared primitives for the stage verification infrastructure.

Public API surface for other verifier modules:
- RepositoryLayout / discover_repository_layout / PROJECT_MARKERS
- hashing helpers (sha256_*, canonical_json, normalize_path)
- terminate_process_tree / ManagedProcess
- reserve_tcp_port / wait_http_ready / wait_port_released
- result dataclasses and exit codes
- workspace / fixture / evidence helpers
"""

from .evidence import ensure_stage_evidence_dir, evidence_file_digest, stage_evidence_dir
from .fixtures import (
    assert_runtime_v1_snapshot_contract,
    assert_runtime_v1_status_contract,
    load_runtime_v1_fixture,
)
from .hashing import (
    canonical_json,
    normalize_path,
    path_matches,
    sha256_bytes,
    sha256_file,
)
from .ports import PortTimeoutError, reserve_tcp_port, wait_http_ready, wait_port_released
from .process import ManagedProcess, terminate_process_tree
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
from .workspace import (
    BUILTIN_SECOND_ORDER_TANK_YAML,
    assert_not_builtin_template,
    copy_template_fixture,
    fixture_root,
)

__all__ = [
    "BUILTIN_SECOND_ORDER_TANK_YAML",
    "PROJECT_MARKERS",
    "RepositoryLayout",
    "EXIT_CONFIGURATION",
    "EXIT_FAILED",
    "EXIT_NEEDS_MANUAL",
    "EXIT_OK",
    "CheckResult",
    "GateResult",
    "ManagedProcess",
    "PortTimeoutError",
    "VerificationResult",
    "assert_not_builtin_template",
    "assert_runtime_v1_snapshot_contract",
    "assert_runtime_v1_status_contract",
    "canonical_json",
    "copy_template_fixture",
    "discover_repository_layout",
    "ensure_stage_evidence_dir",
    "evidence_file_digest",
    "fixture_root",
    "load_runtime_v1_fixture",
    "normalize_path",
    "path_matches",
    "reserve_tcp_port",
    "resolve_git_root",
    "sha256_bytes",
    "sha256_file",
    "stage_evidence_dir",
    "terminate_process_tree",
    "wait_http_ready",
    "wait_port_released",
]
