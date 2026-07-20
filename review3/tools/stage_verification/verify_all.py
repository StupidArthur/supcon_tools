"""CLI entry for multi-stage configuration checks and accepted-through verification."""

from __future__ import annotations

import argparse
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
    DEFAULT_REVIEW_KEY_ENV,
    EXIT_CONFIGURATION,
    EXIT_OK,
    StageVerifier,
    VerificationConfigurationError,
    check_all_manifest_configs,
    load_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check stage manifests or verify accepted checkpoints through a stage."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Project root (review3/), not the Git monorepo root.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate all nine stage manifests without running commands.",
    )
    parser.add_argument(
        "--accepted-through",
        type=int,
        choices=range(0, 9),
        metavar="STAGE",
        help="Verify accepted checkpoints for stages 0..STAGE inclusive.",
    )
    parser.add_argument("--state-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.check_config and args.accepted_through is None:
        build_parser().error("one of --check-config or --accepted-through is required")
    try:
        layout = discover_repository_layout(
            Path(__file__).resolve(),
            explicit_project_root=args.repo_root,
        )
        if args.check_config:
            for line in check_all_manifest_configs(layout):
                print(line)
            print(
                f"Project root: {layout.project_root}\n"
                f"Git root: {layout.git_root}\n"
                f"Verifier root: {layout.verifier_root}"
            )
        if args.accepted_through is not None:
            review_key = os.environ.get(DEFAULT_REVIEW_KEY_ENV)
            for stage in range(0, args.accepted_through + 1):
                manifest, path = load_manifest(
                    layout.project_root, stage, layout=layout
                )
                verifier = StageVerifier(
                    layout, manifest, path, state_dir=args.state_dir
                )
                record = verifier.verify_accepted(review_key=review_key)
                print(
                    f"OK accepted stage {stage}: {verifier.accepted_path} "
                    f"({record['acceptance_mode']})"
                )
        return EXIT_OK
    except (VerificationConfigurationError, LayoutError) as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION


if __name__ == "__main__":
    raise SystemExit(main())
