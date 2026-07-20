"""Verification result dataclasses and process exit codes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIGURATION = 2
EXIT_NEEDS_MANUAL = 3


@dataclass
class CheckResult:
    """One automated check outcome produced by StageVerifier.verify()."""

    check_id: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0


@dataclass
class GateResult:
    """One automated or manual gate outcome."""

    gate_id: str
    mode: str
    status: str
    description: str
    evidence: str | None = None


@dataclass
class VerificationResult:
    """Aggregate stage verification report returned to CLI and callers."""

    stage: int
    stage_name: str
    status: str
    checks: list[CheckResult]
    gates: list[GateResult]
    baseline_path: str
    started_at: str
    duration_seconds: float
    acceptance_mode: str | None = None

    @property
    def exit_code(self) -> int:
        if self.status == "PASS":
            return EXIT_OK
        if self.status == "NEEDS_MANUAL":
            return EXIT_NEEDS_MANUAL
        return EXIT_FAILED

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["exit_code"] = self.exit_code
        return result
