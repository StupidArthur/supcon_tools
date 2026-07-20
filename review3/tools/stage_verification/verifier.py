from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIGURATION = 2
EXIT_NEEDS_MANUAL = 3
DEFAULT_REVIEW_KEY_ENV = "STAGE_VERIFICATION_REVIEW_KEY"
GENERATED_BASELINE_GLOB = "tools/stage_verification/baselines/*.baseline.json"


class VerificationConfigurationError(RuntimeError):
    pass


@dataclass
class CheckResult:
    check_id: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0


@dataclass
class GateResult:
    gate_id: str
    mode: str
    status: str
    description: str
    evidence: str | None = None


@dataclass
class VerificationResult:
    stage: int
    stage_name: str
    status: str
    checks: list[CheckResult]
    gates: list[GateResult]
    baseline_path: str
    started_at: str
    duration_seconds: float

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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def normalize_path(path: str | Path) -> str:
    normalized = str(path).replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def path_matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def discover_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise VerificationConfigurationError(
        f"Cannot locate repository root from {start}"
    )


def manifest_path(repo_root: Path, stage: int) -> Path:
    return (
        repo_root
        / "tools"
        / "stage_verification"
        / "manifests"
        / f"stage_{stage}.json"
    )


def load_manifest(repo_root: Path, stage: int) -> tuple[dict[str, Any], Path]:
    path = manifest_path(repo_root, stage)
    if not path.is_file():
        raise VerificationConfigurationError(f"Manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationConfigurationError(f"Invalid manifest {path}: {exc}") from exc
    validate_manifest(data, expected_stage=stage)
    return data, path


def validate_manifest(data: Mapping[str, Any], expected_stage: int | None = None) -> None:
    required = {
        "schema_version",
        "stage",
        "name",
        "required_documents",
        "allowed_paths",
        "forbidden_paths",
        "preserved_paths",
        "required_paths",
        "forbidden_symbols",
        "locked_paths",
        "locked_acceptance_paths",
        "commands",
        "git_diff_check",
        "gates",
    }
    missing = sorted(required - set(data))
    if missing:
        raise VerificationConfigurationError(
            f"Manifest missing required keys: {', '.join(missing)}"
        )
    if data["schema_version"] != SCHEMA_VERSION:
        raise VerificationConfigurationError(
            f"Unsupported manifest schema_version {data['schema_version']}"
        )
    if expected_stage is not None and data["stage"] != expected_stage:
        raise VerificationConfigurationError(
            f"Manifest stage {data['stage']} does not match requested stage {expected_stage}"
        )
    if not isinstance(data["stage"], int) or not 0 <= data["stage"] <= 8:
        raise VerificationConfigurationError("stage must be an integer from 0 through 8")
    for key in (
        "required_documents",
        "allowed_paths",
        "forbidden_paths",
        "preserved_paths",
        "required_paths",
        "forbidden_symbols",
        "locked_paths",
        "locked_acceptance_paths",
        "commands",
        "gates",
    ):
        if not isinstance(data[key], list):
            raise VerificationConfigurationError(f"{key} must be a list")
    command_ids: set[str] = set()
    for command in data["commands"]:
        if not isinstance(command, dict) or not all(
            key in command for key in ("id", "cwd", "argv", "timeout_seconds")
        ):
            raise VerificationConfigurationError("Every command requires id/cwd/argv/timeout_seconds")
        if command["id"] in command_ids:
            raise VerificationConfigurationError(f"Duplicate command id: {command['id']}")
        command_ids.add(command["id"])
        if not isinstance(command["argv"], list) or not command["argv"]:
            raise VerificationConfigurationError(f"Command {command['id']} argv must be non-empty")
    gate_ids: set[str] = set()
    for gate in data["gates"]:
        if not isinstance(gate, dict) or not all(
            key in gate for key in ("id", "mode", "description")
        ):
            raise VerificationConfigurationError("Every gate requires id/mode/description")
        if gate["mode"] not in ("automated", "manual"):
            raise VerificationConfigurationError(f"Invalid gate mode: {gate['mode']}")
        if gate["id"] in gate_ids:
            raise VerificationConfigurationError(f"Duplicate gate id: {gate['id']}")
        gate_ids.add(gate["id"])
        if gate["mode"] == "automated" and not gate.get("checks"):
            raise VerificationConfigurationError(
                f"Automated gate {gate['id']} requires checks"
            )


def _git_file_list(repo_root: Path) -> list[str]:
    process = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise VerificationConfigurationError(
            "git ls-files failed: " + process.stderr.decode("utf-8", errors="replace")
        )
    return [normalize_path(item) for item in process.stdout.decode("utf-8").split("\0") if item]


def capture_snapshot(repo_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in _git_file_list(repo_root):
        if path_matches(relative, [GENERATED_BASELINE_GLOB]):
            continue
        path = repo_root / relative
        if path.is_file():
            result[relative] = sha256_file(path)
    return result


def snapshot_changes(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def snapshot_fingerprint(files: Mapping[str, str]) -> str:
    return sha256_bytes(canonical_json({"files": dict(sorted(files.items()))}))


def text_hygiene_issues(path: Path) -> Counter[str]:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        return Counter()
    data = path.read_bytes()
    if b"\0" in data:
        return Counter()
    text = data.decode("utf-8", errors="replace")
    issues: Counter[str] = Counter()
    for line in text.splitlines():
        if line.endswith((" ", "\t")):
            issues[f"trailing-whitespace:{line}"] += 1
        if re.match(r"^(<<<<<<<|=======|>>>>>>>)", line):
            issues[f"conflict-marker:{line}"] += 1
    return issues


def automated_checks_fingerprint(checks: Sequence[CheckResult]) -> str:
    stable = [
        {"check_id": check.check_id, "status": check.status}
        for check in checks
    ]
    return sha256_bytes(canonical_json({"checks": stable}))


def expand_snapshot_globs(files: Mapping[str, str], patterns: Sequence[str]) -> dict[str, str]:
    return {
        path: digest
        for path, digest in files.items()
        if path_matches(path, patterns)
    }


def baseline_fingerprint(baseline: Mapping[str, Any]) -> str:
    # Cover every persisted field except the digest itself. This detects direct
    # or accidental edits; it is not a signature against an actor who can rewrite
    # both the baseline and this digest.
    stable = {key: value for key, value in baseline.items() if key != "fingerprint"}
    return sha256_bytes(canonical_json(stable))


class StageVerifier:
    def __init__(
        self,
        repo_root: Path,
        manifest: Mapping[str, Any],
        manifest_file: Path,
        state_dir: Path | None = None,
        output_limit: int = 12000,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.manifest = dict(manifest)
        self.manifest_file = manifest_file.resolve()
        self.stage = int(manifest["stage"])
        self.output_limit = max(1000, output_limit)
        self.uses_default_state = state_dir is None
        self.state_dir = (
            state_dir.resolve()
            if state_dir is not None
            else self.repo_root / ".git" / "stage_verification"
        )

    @property
    def baseline_path(self) -> Path:
        return self.state_dir / f"second_order_tank_stage_{self.stage}.baseline.json"

    @property
    def attestation_path(self) -> Path:
        return self.state_dir / f"second_order_tank_stage_{self.stage}.attestations.json"

    def _git_head(self) -> str | None:
        process = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return process.stdout.strip() if process.returncode == 0 else None

    def record_baseline(
        self,
        force: bool = False,
        review_key: str | None = None,
    ) -> dict[str, Any]:
        if not review_key:
            raise VerificationConfigurationError(
                "Set STAGE_VERIFICATION_REVIEW_KEY while the reviewer records the baseline."
            )
        if self.baseline_path.exists() and not force:
            raise VerificationConfigurationError(
                f"Baseline already exists: {self.baseline_path}; use --force-baseline only as reviewer"
            )
        files = capture_snapshot(self.repo_root)
        locked = expand_snapshot_globs(files, self.manifest["locked_paths"])
        if not locked:
            raise VerificationConfigurationError("locked_paths matched no repository files")
        acceptance_missing = [
            pattern
            for pattern in self.manifest["locked_acceptance_paths"]
            if not any(path_matches(path, [pattern]) for path in files)
        ]
        if acceptance_missing:
            raise VerificationConfigurationError(
                "Reviewer-authored acceptance tests are missing: "
                + ", ".join(acceptance_missing)
            )
        locked_acceptance = expand_snapshot_globs(
            files, self.manifest["locked_acceptance_paths"]
        )
        symbol_counts: dict[str, dict[str, int]] = {}
        for rule in self.manifest["forbidden_symbols"]:
            regex = re.compile(rule["pattern"], re.MULTILINE)
            counts: dict[str, int] = {}
            for relative in files:
                if not path_matches(relative, rule["path_globs"]):
                    continue
                candidate = self.repo_root / relative
                if candidate.is_file() and candidate.stat().st_size <= int(
                    rule.get("max_bytes", 2_000_000)
                ):
                    count = len(regex.findall(candidate.read_text(encoding="utf-8", errors="replace")))
                    if count:
                        counts[relative] = count
            symbol_counts[rule["id"]] = counts
        hygiene_issues = {
            relative: dict(text_hygiene_issues(self.repo_root / relative))
            for relative in files
            if text_hygiene_issues(self.repo_root / relative)
        }
        baseline: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "stage_name": self.manifest["name"],
            "created_at": utc_now(),
            "git_head": self._git_head(),
            "manifest_path": normalize_path(self.manifest_file.relative_to(self.repo_root)),
            "manifest_hash": sha256_file(self.manifest_file),
            "files": files,
            "locked_files": locked,
            "locked_acceptance_files": locked_acceptance,
            "forbidden_symbol_counts": symbol_counts,
            "hygiene_issues": hygiene_issues,
            "review_key_sha256": sha256_bytes(review_key.encode("utf-8")) if review_key else None,
            "storage_mode": self._storage_mode(),
        }
        baseline["fingerprint"] = baseline_fingerprint(baseline)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_path.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return baseline

    def _storage_mode(self) -> str:
        try:
            relative = self.state_dir.relative_to(self.repo_root)
        except ValueError:
            return "external"
        return "external" if relative.parts and relative.parts[0] == ".git" else "tracked"

    def _assert_tracked_baseline_matches_head(self) -> None:
        if self._storage_mode() != "tracked":
            return
        try:
            relative = normalize_path(self.baseline_path.relative_to(self.repo_root))
        except ValueError as exc:
            raise VerificationConfigurationError("Tracked baseline is outside repository") from exc
        process = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            raise VerificationConfigurationError(
                "Default baseline must be reviewed and committed before implementation, "
                f"or use reviewer-owned external --state-dir: {relative}"
            )
        if not hmac.compare_digest(sha256_bytes(process.stdout), sha256_file(self.baseline_path)):
            raise VerificationConfigurationError(
                "Baseline differs from the reviewed HEAD version; refusing to execute commands"
            )

    def _load_baseline(self) -> dict[str, Any]:
        if not self.baseline_path.is_file():
            raise VerificationConfigurationError(
                f"Missing stage baseline: {self.baseline_path}. The reviewer must record it before implementation."
            )
        self._assert_tracked_baseline_matches_head()
        try:
            baseline = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VerificationConfigurationError(f"Invalid baseline: {exc}") from exc
        if baseline.get("stage") != self.stage:
            raise VerificationConfigurationError("Baseline stage does not match manifest")
        if baseline.get("fingerprint") != baseline_fingerprint(baseline):
            raise VerificationConfigurationError("Baseline fingerprint is invalid")
        if baseline.get("storage_mode") != self._storage_mode():
            raise VerificationConfigurationError("Baseline storage mode does not match its location")
        return baseline

    def record_attestation(
        self,
        gate_id: str,
        reviewer: str,
        evidence: str,
        review_key: str | None,
    ) -> dict[str, Any]:
        baseline = self._load_baseline()
        gate = next(
            (g for g in self.manifest["gates"] if g["id"] == gate_id and g["mode"] == "manual"),
            None,
        )
        if gate is None:
            raise VerificationConfigurationError(f"Unknown manual gate: {gate_id}")
        if not review_key:
            raise VerificationConfigurationError(
                f"Set {DEFAULT_REVIEW_KEY_ENV}; only the acceptance reviewer may attest gates"
            )
        key_hash = sha256_bytes(review_key.encode("utf-8"))
        if not baseline.get("review_key_sha256") or not hmac.compare_digest(
            key_hash, baseline["review_key_sha256"]
        ):
            raise VerificationConfigurationError("Review key does not match the baseline trust anchor")
        verification = self.verify(review_key=review_key)
        failed = [check.check_id for check in verification.checks if check.status == "FAIL"]
        if failed:
            raise VerificationConfigurationError(
                "Cannot attest while automated checks fail: " + ", ".join(failed)
            )
        final_files = capture_snapshot(self.repo_root)
        evidence_file: str | None = None
        evidence_hash: str | None = None
        evidence_candidate = Path(evidence)
        if not evidence_candidate.is_absolute():
            evidence_candidate = self.repo_root / evidence_candidate
        if evidence_candidate.is_file():
            try:
                evidence_file = normalize_path(evidence_candidate.resolve().relative_to(self.repo_root))
            except ValueError:
                evidence_file = str(evidence_candidate.resolve())
            evidence_hash = sha256_file(evidence_candidate)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "gate_id": gate_id,
            "baseline_fingerprint": baseline["fingerprint"],
            "manifest_hash": baseline["manifest_hash"],
            "reviewer": reviewer,
            "evidence": evidence,
            "evidence_file": evidence_file,
            "evidence_sha256": evidence_hash,
            "final_tree_hash": snapshot_fingerprint(final_files),
            "automated_checks_hash": automated_checks_fingerprint(verification.checks),
            "attested_at": utc_now(),
        }
        signature = hmac.new(
            review_key.encode("utf-8"), canonical_json(payload), hashlib.sha256
        ).hexdigest()
        record = {**payload, "signature": signature}
        attestations: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "attestations": []}
        if self.attestation_path.is_file():
            attestations = json.loads(self.attestation_path.read_text(encoding="utf-8"))
        existing = [a for a in attestations.get("attestations", []) if a.get("gate_id") != gate_id]
        attestations["attestations"] = [*existing, record]
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.attestation_path.write_text(
            json.dumps(attestations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return record

    def _check(self, check_id: str, passed: bool, summary: str, **details: Any) -> CheckResult:
        return CheckResult(
            check_id=check_id,
            status="PASS" if passed else "FAIL",
            summary=summary,
            details=details,
        )

    def _run_command(self, spec: Mapping[str, Any]) -> CheckResult:
        started = time.monotonic()
        argv = spec.get("windows_argv") if platform.system() == "Windows" else None
        argv = list(argv or spec["argv"])
        argv = [sys.executable if value == "{python}" else str(value) for value in argv]
        cwd = (self.repo_root / spec["cwd"]).resolve()
        if not cwd.is_dir():
            return CheckResult(
                check_id=f"command:{spec['id']}",
                status="FAIL",
                summary=f"Working directory does not exist: {spec['cwd']}",
            )
        environment = os.environ.copy()
        # Reviewer credentials belong to the verifier process only. Product tests,
        # build tools and implementation-controlled scripts must never inherit them.
        environment.pop(DEFAULT_REVIEW_KEY_ENV, None)
        substitutions = {"repo": str(self.repo_root), "temp": tempfile.gettempdir()}
        for key, value in spec.get("env", {}).items():
            environment[key] = str(value).format(**substitutions)
        try:
            popen_kwargs: dict[str, Any] = {}
            if platform.system() == "Windows":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
            try:
                output, _ = process.communicate(timeout=float(spec["timeout_seconds"]))
            except subprocess.TimeoutExpired:
                if platform.system() == "Windows":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    if process.poll() is None:
                        process.kill()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                output, _ = process.communicate()
                return CheckResult(
                    check_id=f"command:{spec['id']}",
                    status="FAIL",
                    summary=f"timeout after {spec['timeout_seconds']}s: {' '.join(argv)}",
                    details={"output_tail": (output or "")[-self.output_limit :]},
                    duration_seconds=time.monotonic() - started,
                )
            output = output or ""
            passed = process.returncode == 0
            summary = f"exit {process.returncode}: {' '.join(argv)}"
            return CheckResult(
                check_id=f"command:{spec['id']}",
                status="PASS" if passed else "FAIL",
                summary=summary,
                details={
                    "argv": argv,
                    "cwd": normalize_path(spec["cwd"]),
                    "exit_code": process.returncode,
                    "output_tail": output[-self.output_limit :],
                    "output_truncated": len(output) > self.output_limit,
                },
                duration_seconds=time.monotonic() - started,
            )
        except OSError as exc:
            return CheckResult(
                check_id=f"command:{spec['id']}",
                status="FAIL",
                summary=f"could not execute {' '.join(argv)}: {exc}",
                duration_seconds=time.monotonic() - started,
            )

    def _run_git_diff_check(
        self,
        changed: Sequence[str],
        current: Mapping[str, str],
        baseline: Mapping[str, Any],
    ) -> CheckResult:
        started = time.monotonic()
        process = subprocess.run(
            ["git", "diff", "HEAD", "--check", "--"],
            cwd=self.repo_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if process.returncode == 128:
            process = subprocess.run(
                ["git", "diff", "--check", "--"],
                cwd=self.repo_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        baseline_issues = baseline.get("hygiene_issues", {})
        new_issues: list[dict[str, Any]] = []
        for relative in changed:
            if relative not in current:
                continue
            current_counts = text_hygiene_issues(self.repo_root / relative)
            previous_counts = Counter(baseline_issues.get(relative, {}))
            for issue, count in (current_counts - previous_counts).items():
                new_issues.append({"path": relative, "issue": issue, "count": count})
        return CheckResult(
            check_id="git_diff_check",
            status="PASS" if not new_issues else "FAIL",
            summary=(
                "baseline-scoped whitespace/conflict-marker check passed"
                if not new_issues
                else "new trailing whitespace or conflict markers found in stage changes"
            ),
            details={
                "new_issues": new_issues,
                "auxiliary_git_diff_head_exit": process.returncode,
                "auxiliary_git_diff_head_output_tail": (process.stdout or "")[-self.output_limit :],
            },
            duration_seconds=time.monotonic() - started,
        )

    def _attestation_gate_results(
        self,
        baseline: Mapping[str, Any],
        review_key: str | None,
        final_tree_hash: str,
        automated_checks_hash: str,
    ) -> list[GateResult]:
        records: list[Mapping[str, Any]] = []
        if self.attestation_path.is_file():
            try:
                records = json.loads(self.attestation_path.read_text(encoding="utf-8")).get(
                    "attestations", []
                )
            except (OSError, json.JSONDecodeError):
                records = []
        trusted_key = False
        if review_key and baseline.get("review_key_sha256"):
            trusted_key = hmac.compare_digest(
                sha256_bytes(review_key.encode("utf-8")), baseline["review_key_sha256"]
            )
        results: list[GateResult] = []
        for gate in self.manifest["gates"]:
            if gate["mode"] != "manual":
                continue
            record = next((r for r in records if r.get("gate_id") == gate["id"]), None)
            valid = False
            if record and trusted_key:
                payload = {key: value for key, value in record.items() if key != "signature"}
                expected = hmac.new(
                    review_key.encode("utf-8"), canonical_json(payload), hashlib.sha256
                ).hexdigest()
                valid = (
                    hmac.compare_digest(str(record.get("signature", "")), expected)
                    and record.get("baseline_fingerprint") == baseline["fingerprint"]
                    and record.get("manifest_hash") == baseline["manifest_hash"]
                    and record.get("stage") == self.stage
                    and record.get("final_tree_hash") == final_tree_hash
                    and record.get("automated_checks_hash") == automated_checks_hash
                )
                evidence_file = record.get("evidence_file")
                evidence_hash = record.get("evidence_sha256")
                if valid and evidence_file:
                    evidence_path = Path(str(evidence_file))
                    if not evidence_path.is_absolute():
                        evidence_path = self.repo_root / evidence_path
                    valid = (
                        evidence_path.is_file()
                        and bool(evidence_hash)
                        and hmac.compare_digest(sha256_file(evidence_path), str(evidence_hash))
                    )
            results.append(
                GateResult(
                    gate_id=gate["id"],
                    mode="manual",
                    status="PASS" if valid else "NEEDS_MANUAL",
                    description=gate["description"],
                    evidence=str(record.get("evidence")) if valid and record else None,
                )
            )
        return results

    def verify(self, review_key: str | None = None, fail_fast: bool = False) -> VerificationResult:
        started_monotonic = time.monotonic()
        started_at = utc_now()
        baseline = self._load_baseline()
        if not self.uses_default_state:
            supplied = sha256_bytes(review_key.encode("utf-8")) if review_key else ""
            if not baseline.get("review_key_sha256") or not hmac.compare_digest(
                supplied, baseline["review_key_sha256"]
            ):
                raise VerificationConfigurationError(
                    "Non-default --state-dir is reviewer-only and requires the baseline review key"
                )
        checks: list[CheckResult] = []

        manifest_unchanged = sha256_file(self.manifest_file) == baseline["manifest_hash"]
        if not manifest_unchanged:
            raise VerificationConfigurationError(
                "Manifest changed after the reviewed baseline; refusing to execute manifest commands"
            )
        checks.append(
            self._check(
                "manifest_locked",
                manifest_unchanged,
                "manifest matches reviewer baseline" if manifest_unchanged else "manifest changed after baseline",
            )
        )
        documents = list(self.manifest["required_documents"])
        missing_documents = [path for path in documents if not (self.repo_root / path).is_file()]
        checks.append(
            self._check(
                "required_documents",
                not missing_documents,
                "all required documents exist" if not missing_documents else "required documents missing",
                missing=missing_documents,
            )
        )
        initial_files = capture_snapshot(self.repo_root)
        required_missing = [
            pattern
            for pattern in self.manifest["required_paths"]
            if not any(path_matches(path, [pattern]) for path in initial_files)
        ]
        checks.append(
            self._check(
                "required_paths",
                not required_missing,
                "all required deliverables exist" if not required_missing else "required deliverables missing",
                missing_patterns=required_missing,
            )
        )
        preserved_missing = [
            path for path in self.manifest["preserved_paths"] if not (self.repo_root / path).is_file()
        ]
        checks.append(
            self._check(
                "preserved_paths",
                not preserved_missing,
                "preserved files remain present" if not preserved_missing else "preserved files were deleted",
                missing=preserved_missing,
            )
        )

        if not fail_fast or all(check.status == "PASS" for check in checks):
            for spec in self.manifest["commands"]:
                command_result = self._run_command(spec)
                checks.append(command_result)
                if fail_fast and command_result.status == "FAIL":
                    break

        current = capture_snapshot(self.repo_root)
        changed = snapshot_changes(baseline["files"], current)
        disallowed = [
            path for path in changed if not path_matches(path, self.manifest["allowed_paths"])
        ]
        forbidden = [
            path for path in changed if path_matches(path, self.manifest["forbidden_paths"])
        ]
        checks.append(
            self._check(
                "changed_paths_allowed",
                not disallowed,
                "all changes are in the stage allowlist" if not disallowed else "out-of-stage paths changed",
                changed=changed,
                disallowed=disallowed,
            )
        )
        checks.append(
            self._check(
                "forbidden_paths",
                not forbidden,
                "no forbidden path changed" if not forbidden else "forbidden paths changed",
                forbidden=forbidden,
            )
        )
        locked_mismatches = [
            path
            for path, digest in baseline["locked_files"].items()
            if current.get(path) != digest
        ]
        checks.append(
            self._check(
                "locked_files",
                not locked_mismatches,
                "locked verification assets are unchanged"
                if not locked_mismatches
                else "locked verification assets changed",
                mismatches=locked_mismatches,
            )
        )
        acceptance_mismatches = [
            path
            for path, digest in baseline.get("locked_acceptance_files", {}).items()
            if current.get(path) != digest
        ]
        checks.append(
            self._check(
                "locked_acceptance_files",
                not acceptance_mismatches,
                "reviewer-authored acceptance tests are unchanged"
                if not acceptance_mismatches
                else "reviewer-authored acceptance tests changed",
                mismatches=acceptance_mismatches,
            )
        )

        symbol_hits: list[dict[str, Any]] = []
        for rule in self.manifest["forbidden_symbols"]:
            regex = re.compile(rule["pattern"], re.MULTILINE)
            scope_paths = changed if rule.get("scope", "changed") == "changed" else sorted(current)
            baseline_counts = baseline.get("forbidden_symbol_counts", {}).get(rule["id"], {})
            for relative in scope_paths:
                if not path_matches(relative, rule["path_globs"]):
                    continue
                path = self.repo_root / relative
                if not path.is_file() or path.stat().st_size > int(rule.get("max_bytes", 2_000_000)):
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
                matches = list(regex.finditer(content))
                previous_count = int(baseline_counts.get(relative, 0))
                if len(matches) > previous_count:
                    match = matches[min(previous_count, len(matches) - 1)]
                    line = content.count("\n", 0, match.start()) + 1
                    symbol_hits.append(
                        {
                            "rule": rule["id"],
                            "path": relative,
                            "line": line,
                            "match": match.group(0)[:160],
                            "baseline_count": previous_count,
                            "current_count": len(matches),
                        }
                    )
        checks.append(
            self._check(
                "forbidden_symbols",
                not symbol_hits,
                "no next-stage symbols introduced"
                if not symbol_hits
                else "next-stage or prohibited symbols found",
                hits=symbol_hits,
            )
        )
        if self.manifest["git_diff_check"]:
            checks.append(self._run_git_diff_check(changed, current, baseline))

        check_by_id = {check.check_id: check for check in checks}
        gates: list[GateResult] = []
        for gate in self.manifest["gates"]:
            if gate["mode"] != "automated":
                continue
            referenced = [check_by_id.get(check_id) for check_id in gate["checks"]]
            passed = all(item is not None and item.status == "PASS" for item in referenced)
            missing = [gate["checks"][index] for index, item in enumerate(referenced) if item is None]
            gates.append(
                GateResult(
                    gate_id=gate["id"],
                    mode="automated",
                    status="PASS" if passed else "FAIL",
                    description=gate["description"],
                    evidence=("missing checks: " + ", ".join(missing)) if missing else None,
                )
            )
        gates.extend(
            self._attestation_gate_results(
                baseline,
                review_key,
                snapshot_fingerprint(current),
                automated_checks_fingerprint(checks),
            )
        )
        any_failed = any(check.status == "FAIL" for check in checks) or any(
            gate.status == "FAIL" for gate in gates
        )
        needs_manual = any(gate.status == "NEEDS_MANUAL" for gate in gates)
        status = "FAIL" if any_failed else ("NEEDS_MANUAL" if needs_manual else "PASS")
        return VerificationResult(
            stage=self.stage,
            stage_name=self.manifest["name"],
            status=status,
            checks=checks,
            gates=gates,
            baseline_path=str(self.baseline_path),
            started_at=started_at,
            duration_seconds=time.monotonic() - started_monotonic,
        )


def render_human(result: VerificationResult) -> str:
    lines = [
        f"Stage {result.stage}: {result.stage_name}",
        f"RESULT: {result.status}",
        "",
        "Checks:",
    ]
    for check in result.checks:
        lines.append(f"  [{check.status}] {check.check_id}: {check.summary}")
        if check.status == "FAIL":
            for key, value in check.details.items():
                if value:
                    lines.append(f"      {key}: {value}")
    lines.append("")
    lines.append("Gates:")
    for gate in result.gates:
        lines.append(f"  [{gate.status}] {gate.gate_id} ({gate.mode}): {gate.description}")
        if gate.evidence:
            lines.append(f"      evidence: {gate.evidence}")
    lines.extend(
        [
            "",
            f"Baseline: {result.baseline_path}",
            f"Duration: {result.duration_seconds:.2f}s",
        ]
    )
    return "\n".join(lines)
