from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stage_verification.verifier import (  # noqa: E402
    DEFAULT_REVIEW_KEY_ENV,
    EXIT_CONFIGURATION,
    StageVerifier,
    VerificationConfigurationError,
    discover_repo_root,
    load_manifest,
    render_human,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify one second-order-tank implementation stage."
    )
    parser.add_argument("stage", type=int, choices=range(0, 9))
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--force-baseline", action="store_true")
    parser.add_argument("--attest", metavar="MANUAL_GATE_ID")
    parser.add_argument("--reviewer")
    parser.add_argument("--evidence")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--output-limit", type=int, default=12000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = (
            args.repo_root.resolve()
            if args.repo_root
            else discover_repo_root(Path(__file__).resolve())
        )
        manifest, path = load_manifest(root, args.stage)
        verifier = StageVerifier(
            root,
            manifest,
            path,
            state_dir=args.state_dir,
            output_limit=args.output_limit,
        )
        if args.json_output:
            output_path = args.json_output
            if not output_path.is_absolute():
                output_path = root / output_path
            output_path = output_path.resolve()
            try:
                output_path.relative_to(root)
                inside_repo = True
            except ValueError:
                inside_repo = False
            try:
                output_path.relative_to(verifier.state_dir)
                inside_state = True
            except ValueError:
                inside_state = False
            if inside_repo and not inside_state:
                raise VerificationConfigurationError(
                    "--json-output inside the repository must be under the verifier state directory "
                    f"({verifier.state_dir}) to avoid changing the next scope check"
                )
            args.json_output = output_path
        review_key = os.environ.get(DEFAULT_REVIEW_KEY_ENV)
        if args.record_baseline:
            baseline = verifier.record_baseline(
                force=args.force_baseline, review_key=review_key
            )
            print(
                f"Recorded reviewer baseline for stage {args.stage}: {verifier.baseline_path}\n"
                f"Fingerprint: {baseline['fingerprint']}"
            )
            return 0
        if args.attest:
            if not args.reviewer or not args.evidence:
                raise VerificationConfigurationError(
                    "--attest requires --reviewer and --evidence"
                )
            record = verifier.record_attestation(
                args.attest, args.reviewer, args.evidence, review_key
            )
            print(
                f"Recorded reviewer attestation for {record['gate_id']}: "
                f"{verifier.attestation_path}"
            )
            return 0
        result = verifier.verify(review_key=review_key, fail_fast=args.fail_fast)
        result_json = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        print(result_json if args.format == "json" else render_human(result))
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(result_json + "\n", encoding="utf-8")
        return result.exit_code
    except VerificationConfigurationError as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION


if __name__ == "__main__":
    raise SystemExit(main())
