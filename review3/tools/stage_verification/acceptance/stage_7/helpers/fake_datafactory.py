#!/usr/bin/env python3
"""Reviewer-owned fake DataFactory for stage 7 external-behavior acceptance.

Invoked as: python fake_datafactory.py -c <yaml> --batch <n> [--export <csv>]

Behavior is controlled by environment variables (not business code):

- FAKE_DF_MARKER: string written into every CSV data cell (default: config basename)
- FAKE_DF_EXIT: integer exit code (default 0)
- FAKE_DF_STDERR: optional stderr text
- FAKE_DF_EMPTY: if "1", write header-only / empty body (for STAGE7-BATCH-007)
- FAKE_DF_SLEEP_S: optional sleep before writing (for concurrency / Running tests)
- FAKE_DF_MODE: "batch" (default) or "realtime" (long-running until killed)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-c", dest="config")
    parser.add_argument("--batch", type=int, default=0)
    parser.add_argument("--export", default="")
    parser.add_argument("--mode", default="")
    parser.add_argument("--api", action="store_true")
    parser.add_argument("--api-port", type=int, default=0)
    parser.add_argument("--api-host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--name", default="")
    parser.add_argument("--cycle-time", type=float, default=0.0)
    args, _unknown = parser.parse_known_args(argv)

    stderr_text = os.environ.get("FAKE_DF_STDERR", "")
    if stderr_text:
        print(stderr_text, file=sys.stderr)

    sleep_s = float(os.environ.get("FAKE_DF_SLEEP_S", "0") or "0")
    if sleep_s > 0:
        time.sleep(sleep_s)

    mode = os.environ.get("FAKE_DF_MODE", "batch")
    if mode == "realtime" or args.api:
        # Stay alive until killed — used for SystemBinding.Start Running=true probes.
        while True:
            time.sleep(0.2)

    exit_code = int(os.environ.get("FAKE_DF_EXIT", "0") or "0")
    export_path = args.export
    if not export_path:
        print("fake_datafactory: missing --export", file=sys.stderr)
        return 2 if exit_code == 0 else exit_code

    marker = os.environ.get("FAKE_DF_MARKER")
    if not marker:
        marker = Path(args.config or "unknown").name

    empty = os.environ.get("FAKE_DF_EMPTY", "") == "1"
    cycles = max(0, int(args.batch or 0))
    Path(export_path).parent.mkdir(parents=True, exist_ok=True)
    with open(export_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["cycle", "sim_time", "marker", "pid2.SV"])
        if not empty:
            for i in range(cycles):
                writer.writerow([i, float(i) * 0.5, marker, 0.5])

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
