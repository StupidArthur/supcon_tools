"""Run one subprocess with hard timeout, durable stdout/stderr, JSON result.

Windows-specific:
  uses subprocess.CREATE_NEW_PROCESS_GROUP so taskkill /T /F can stop the
  entire tree (including cmd.exe / python.exe / child OS processes).
Posix-specific:
  uses start_new_session=True so a process group kill reaches all descendants.

Result JSON shape is fixed and consumed by run_automation_ua2.py.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


TIMEOUT_EXIT_CODE = 124


def _run_windows(command: list[str], timeout_sec: float, stdout_path: Path, stderr_path: Path) -> dict:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            command,
            stdout=out,
            stderr=err,
            creationflags=creationflags,
        )
        started = time.time()
        try:
            code = proc.wait(timeout=timeout_sec)
            return _finish(code, started, timeout_sec, stdout_path, stderr_path, timed_out=False)
        except subprocess.TimeoutExpired:
            _terminate_windows_tree(proc)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            return _finish(TIMEOUT_EXIT_CODE, started, timeout_sec, stdout_path, stderr_path, timed_out=True)


def _run_posix(command: list[str], timeout_sec: float, stdout_path: Path, stderr_path: Path) -> dict:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            command,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
        started = time.time()
        try:
            code = proc.wait(timeout=timeout_sec)
            return _finish(code, started, timeout_sec, stdout_path, stderr_path, timed_out=False)
        except subprocess.TimeoutExpired:
            _terminate_posix_tree(proc)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            return _finish(TIMEOUT_EXIT_CODE, started, timeout_sec, stdout_path, stderr_path, timed_out=True)


def _terminate_windows_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _terminate_posix_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    import signal
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _finish(code: int, started: float, timeout_sec: float, stdout_path: Path, stderr_path: Path, *, timed_out: bool) -> dict:
    duration = max(0.0, time.time() - started)
    return {
        "exitCode": int(code),
        "timedOut": bool(timed_out),
        "timeoutSec": float(timeout_sec),
        "durationSec": round(duration, 3),
    }


def run(command: list[str], timeout_sec: float, stdout_path: Path, stderr_path: Path) -> dict:
    started = time.time()
    if os.name == "nt":
        result = _run_windows(command, timeout_sec, stdout_path, stderr_path)
    else:
        result = _run_posix(command, timeout_sec, stdout_path, stderr_path)
    result["command"] = list(command)
    result["startedAtEpochMs"] = int(started * 1000)
    result["durationMs"] = int(result["durationSec"] * 1000)
    result["stdoutPath"] = str(stdout_path)
    result["stderrPath"] = str(stderr_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-sec", type=float, required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--", action="store_true", dest="sep")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        print("-- <command...> required", file=sys.stderr)
        return 2

    started_epoch_ms = int(time.time() * 1000)
    result = run(args.command, args.timeout_sec, Path(args.stdout), Path(args.stderr))
    result["startedAtEpochMs"] = started_epoch_ms

    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return int(result["exitCode"])


if __name__ == "__main__":
    raise SystemExit(main())
