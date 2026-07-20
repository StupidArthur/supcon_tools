"""CLI entry for verifying one second-order-tank implementation stage."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stage_verification.common.repo_layout import (  # noqa: E402
    LayoutError,
    discover_repository_layout,
)
from tools.stage_verification.verifier import (  # noqa: E402
    ACCEPTANCE_MODES,
    DEFAULT_REVIEW_KEY_ENV,
    EXIT_CONFIGURATION,
    StageVerifier,
    VerificationConfigurationError,
    load_manifest,
    render_human,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify one second-order-tank implementation stage."
    )
    parser.add_argument("stage", type=int, choices=range(0, 9))
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Project root (review3/), not the Git monorepo root.",
    )
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument(
        "--acceptance-mode",
        choices=sorted(ACCEPTANCE_MODES),
        default="retrospective",
        help="Used with --record-baseline. Stages 0-4: retrospective; 5-8: prospective.",
    )
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--force-baseline", action="store_true")
    parser.add_argument("--attest", metavar="GATE_ID")
    parser.add_argument("--reviewer")
    parser.add_argument("--evidence")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--verify-accepted", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--output-limit", type=int, default=12000)
    return parser


def _guard_json_output(
    output_path: Path, project_root: Path, state_dir: Path
) -> Path:
    if not output_path.is_absolute():
        output_path = project_root / output_path
    output_path = output_path.resolve()
    try:
        output_path.relative_to(project_root.resolve())
        inside_project = True
    except ValueError:
        inside_project = False
    try:
        output_path.relative_to(state_dir.resolve())
        inside_state = True
    except ValueError:
        inside_state = False
    if inside_project and not inside_state:
        raise VerificationConfigurationError(
            "--json-output inside the project must be under the verifier state directory "
            f"({state_dir}) to avoid changing the next scope check"
        )
    return output_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        layout = discover_repository_layout(
            Path(__file__).resolve(),
            explicit_project_root=args.repo_root,
        )
        manifest, path = load_manifest(layout.project_root, args.stage, layout=layout)
        verifier = StageVerifier(
            layout,
            manifest,
            path,
            state_dir=args.state_dir,
            output_limit=args.output_limit,
        )
        if args.json_output:
            args.json_output = _guard_json_output(
                args.json_output, layout.project_root, verifier.state_dir
            )
        review_key = os.environ.get(DEFAULT_REVIEW_KEY_ENV)

        if args.record_baseline:
            baseline = verifier.record_baseline(
                force=args.force_baseline,
                review_key=review_key,
                acceptance_mode=args.acceptance_mode,
            )
            print(
                f"Recorded reviewer baseline for stage {args.stage}: {verifier.baseline_path}\n"
                f"Acceptance mode: {baseline['acceptance_mode']}\n"
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

        if args.finalize:
            record = verifier.finalize(reviewer=args.reviewer or "", review_key=review_key)
            print(
                f"Finalized accepted checkpoint for stage {args.stage}: "
                f"{verifier.accepted_path}\n"
                f"Acceptance mode: {record['acceptance_mode']}"
            )
            return 0

        if args.verify_accepted:
            record = verifier.verify_accepted(review_key=review_key)
            print(
                f"Accepted checkpoint verified for stage {args.stage}: "
                f"{verifier.accepted_path}\n"
                f"Acceptance mode: {record['acceptance_mode']}"
            )
            return 0

        result = verifier.verify(review_key=review_key, fail_fast=args.fail_fast)
        result_json = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        print(result_json if args.format == "json" else render_human(result))
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(result_json + "\n", encoding="utf-8")
        return result.exit_code
    except (VerificationConfigurationError, LayoutError) as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION


if __name__ == "__main__":
    raise SystemExit(main())
