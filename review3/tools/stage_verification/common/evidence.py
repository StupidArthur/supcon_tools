"""Evidence path helpers for manual gate attestations."""

from __future__ import annotations

from pathlib import Path

from .hashing import sha256_file

EVIDENCE_DIRNAME = "evidence"


def stage_evidence_dir(verifier_root: Path, stage: int) -> Path:
    """Return ``tools/stage_verification/evidence/stage_{N}``."""
    return verifier_root / EVIDENCE_DIRNAME / f"stage_{stage}"


def ensure_stage_evidence_dir(verifier_root: Path, stage: int) -> Path:
    """Create the stage evidence directory if needed and return it."""
    path = stage_evidence_dir(verifier_root, stage)
    path.mkdir(parents=True, exist_ok=True)
    return path


def evidence_file_digest(path: Path) -> str:
    """Return SHA-256 of an evidence file."""
    if not path.is_file():
        raise FileNotFoundError(path)
    return sha256_file(path)
