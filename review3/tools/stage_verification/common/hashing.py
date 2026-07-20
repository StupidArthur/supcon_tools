"""Hashing and path-normalization helpers shared by verifier modules."""

from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file, streamed in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Mapping[str, Any]) -> bytes:
    """Serialize a mapping to a stable UTF-8 JSON payload for hashing/HMAC."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def normalize_path(path: str | Path) -> str:
    """Normalize path separators to '/' and strip a leading './' only.

    Dot-prefixed names such as `.gitignore` must not be mangled.
    """
    normalized = str(path).replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def path_matches(path: str, patterns: Iterable[str]) -> bool:
    """Return True when *path* matches any fnmatch pattern (case-sensitive)."""
    normalized = normalize_path(path)
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)
