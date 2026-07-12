"""Run one subprocess with a hard timeout and durable stdout/stderr logs."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

TIMEOUT_EXIT_CODE = 124


def _terminate_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.kill()


def run(command: list[str], timeout_sec: float, stdout_path: Path, stderr_path: Path) -> dict:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout_sec)
            return {"exitCode": code, "timeout": False, "durationSec": round(time.time() - started, 3)}
        except subprocess.TimeoutExpired:
            _terminate_tree(proc)
            return {"exitCode": TIMEOUT_EXIT_CODE, "timeout": True, "durationSec": round(time.time() - started, 3)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    result = run(args.command, args.timeout, Path(args.stdout), Path(args.stderr))
    print(json.dumps(result, ensure_ascii=False))
    return int(result["exitCode"])


if __name__ == "__main__":
    raise SystemExit(main())
