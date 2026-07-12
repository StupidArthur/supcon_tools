"""UA-2 自动化 runner (Python 版)。

不走 PowerShell pipeline;每条 Case 用独立进程 + 超时 + 强制 cleanup。

阶段:
  1. 预检 DATAHUB_PASSWORD
  2. compileall ua_test_harness (180s)
  3. unit tests (300s)
  4. catalog export (180s)
  5. inventory strict (180s)
  6. 启动 ua_mocker/ua2_types.yaml (端口 18965)
  7. 16 条 Case 各跑独立子进程(普通 180s / 删除恢复 240s)
  8. 强制残留清理(每条之后 + 全部跑完后)
  9. 汇总 ua2-result.json
  10. pass/fail/所有 PASS + 无 cleanup-failed 才 exit 0
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
SRC_DIRS = ["ua_test_harness", "scripts", "ua_mocker"]
CASE_TIMEOUTS = {
    "default": 180.0,
    "delete": 240.0,
    "recycle": 240.0,
}
CHAPTER_TOTAL_TIMEOUT = 2700.0

CASES_UA2 = [
    "UA-2-1-017", "UA-2-1-019", "UA-2-1-021", "UA-2-1-022",
    "UA-2-2-004", "UA-2-2-005", "UA-2-2-008", "UA-2-2-011",
    "UA-2-2-015", "UA-2-2-016", "UA-2-2-019", "UA-2-2-033",
    "UA-2-4-001", "UA-2-4-013", "UA-2-4-020", "UA-2-4-024",
]


def _run_capture(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def phase_compile(deadline_ts: float) -> dict[str, Any]:
    return _phase("compileall", [sys.executable, "-m", "compileall", "-q"] + SRC_DIRS, 180.0, deadline_ts)


def phase_unit_tests(deadline_ts: float) -> dict[str, Any]:
    return _phase("unit_tests", [sys.executable, "-m", "pytest", "ua_test_harness/unit_tests", "-q"], 300.0, deadline_ts)


def phase_catalog(out_path: Path, deadline_ts: float) -> dict[str, Any]:
    return _phase(
        "catalog_export",
        [sys.executable, "-m", "ua_test_harness.cli", "catalog", "--output", str(out_path)],
        180.0,
        deadline_ts,
    )


def phase_inventory(out_path: Path, deadline_ts: float) -> dict[str, Any]:
    return _phase(
        "case_inventory",
        [
            sys.executable, "-m", "ua_test_harness.case_inventory",
            "--repo-root", str(REPO_ROOT),
            "--expected-total", "419",
            "--strict-structure",
            "--output", str(out_path),
        ],
        180.0,
        deadline_ts,
    )


def _phase(name: str, cmd: list[str], timeout: float, deadline_ts: float) -> dict[str, Any]:
    remaining = max(0.0, deadline_ts - time.monotonic())
    if remaining <= 0:
        return {"name": name, "status": "TIMEOUT", "elapsedMs": 0, "error": "chapter deadline already elapsed"}
    effective_timeout = min(timeout, remaining)
    started = time.monotonic()
    try:
        rc, out, err = _run_capture(cmd, effective_timeout)
        return {
            "name": name,
            "status": "PASS" if rc == 0 else "FAIL",
            "elapsedMs": int((time.monotonic() - started) * 1000),
            "exitCode": rc,
            "stdoutTail": out[-2000:] if out else "",
            "stderrTail": err[-2000:] if err else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "status": "TIMEOUT",
            "elapsedMs": int((time.monotonic() - started) * 1000),
            "error": f"subprocess exceeded {effective_timeout}s",
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "ERROR",
            "elapsedMs": int((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _start_mock(out_dir: Path, deadline_ts: float) -> dict[str, Any]:
    yaml_path = REPO_ROOT / "ua_mocker" / "ua2_types.yaml"
    stdout_path = out_dir / "mock.stdout.log"
    stderr_path = out_dir / "mock.stderr.log"
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "main.py", str(yaml_path)],
        cwd=str(REPO_ROOT / "ua_mocker"),
        stdout=stdout_path.open("w"),
        stderr=stderr_path.open("w"),
    )
    ready_deadline = started + 60.0
    while time.monotonic() < ready_deadline and time.monotonic() < deadline_ts:
        if proc.poll() is not None:
            break
        try:
            import socket
            sock = socket.socket()
            sock.settimeout(0.5)
            sock.connect(("127.0.0.1", 18965))
            sock.close()
            return {
                "started": True,
                "readyInSec": round(time.monotonic() - started, 2),
                "pid": proc.pid,
                "stdoutPath": str(stdout_path),
                "stderrPath": str(stderr_path),
                "_proc": proc,
            }
        except Exception:
            time.sleep(0.5)
    proc.kill()
    return {"started": False, "readyInSec": round(time.monotonic() - started, 2), "error": "mock did not become ready"}


def _stop_mock(handle: dict[str, Any]) -> None:
    proc = handle.get("_proc") if handle else None
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def _case_timeout(case_id: str) -> float:
    if case_id.startswith("UA-2-4-"):
        return CASE_TIMEOUTS["delete"]
    return CASE_TIMEOUTS["default"]


def _run_single_case(out_dir: Path, case_id: str) -> dict[str, Any]:
    case_dir = out_dir / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = case_dir / "run-config.json"
    local_ip = os.environ.get("UA_LOCAL_IP", "10.30.70.77")
    payload = {
        "runId": f"ua2_{case_id}",
        "selectedCaseIds": [case_id],
        "subject": {
            "baseUrl": os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.153:31501/"),
            "tenantId": "",
            "username": os.environ.get("DATAHUB_USER", "admin"),
            "password": "",
            "token": "",
        },
        "localIp": local_ip,
        "mock": {
            "controlMode": "external-script",
            "endpoints": {
                "functional": f"opc.tcp://{local_ip}:18965/ua_mocker/",
                "reconnect": "",
                "performance": "",
                "abnormal": "",
            },
        },
        "timeouts": {"pollIntervalMs": 500, "rtVisibilitySec": 30, "historyVisibilitySec": 120, "dsConnectSec": 60},
        "paths": {
            "runDir": str(case_dir / "run"),
            "evidenceDir": str(case_dir / "run" / "evidence"),
            "reportPath": str(case_dir / "run" / "report.json"),
        },
        "note": f"UA-2 first batch case {case_id}",
    }
    cfg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stdout_path = case_dir / "stdout.log"
    stderr_path = case_dir / "stderr.log"
    result_path = case_dir / "timeout-result.json"

    runner = REPO_ROOT / "scripts" / "run_with_timeout.py"
    cmd = [
        sys.executable, str(runner),
        "--timeout-sec", str(_case_timeout(case_id)),
        "--stdout", str(stdout_path),
        "--stderr", str(stderr_path),
        "--result", str(result_path),
        "--",
        sys.executable, "-m", "ua_test_harness.cli", "run",
        "--config", str(cfg_path), "--cases", case_id,
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=_case_timeout(case_id) + 30.0,
    )
    timed_out = proc.returncode == 124
    summary = _summarize_case(case_dir)
    summary["stdoutTail"] = proc.stdout[-2000:] if proc.stdout else ""
    summary["stderrTail"] = proc.stderr[-2000:] if proc.stderr else ""
    return summary


def _summarize_case(case_dir: Path) -> dict[str, Any]:
    report_path = case_dir / "run" / "report.json"
    result_path = case_dir / "timeout-result.json"
    base: dict[str, Any] = {
        "caseId": case_dir.name,
        "caseDir": str(case_dir),
        "reportPath": str(report_path),
        "resultPath": str(result_path),
        "status": "UNKNOWN",
        "durationMs": 0,
        "cleanupStatus": "UNKNOWN",
        "cleanupMessage": "",
    }
    if report_path.is_file():
        try:
            rep = json.loads(report_path.read_text(encoding="utf-8"))
            status = rep.get("status", "UNKNOWN")
            base["status"] = status
            base["durationMs"] = sum(
                c.get("durationMs", 0) for c in rep.get("cases", []) if c.get("id") == case_dir.name
            ) or sum(c.get("durationMs", 0) for c in rep.get("cases", []))
            for c in rep.get("cases", []):
                if c.get("id") == case_dir.name or case_dir.name.startswith(c.get("id", "")):
                    base["status"] = c.get("status", base["status"])
                    base["durationMs"] = c.get("durationMs", base["durationMs"])
                    base["cleanupStatus"] = c.get("cleanupStatus", "PASS")
                    base["cleanupMessage"] = c.get("cleanupMessage", "")
                    break
        except Exception as exc:
            base["reportParseError"] = f"{type(exc).__name__}: {exc}"
    if result_path.is_file():
        try:
            res = json.loads(result_path.read_text(encoding="utf-8"))
            base["runnerExitCode"] = res.get("exitCode")
            base["runnerTimedOut"] = res.get("timedOut", False)
            base["runnerDurationSec"] = res.get("durationSec")
            if res.get("timedOut"):
                base["status"] = "TIMEOUT"
        except Exception as exc:
            base["resultParseError"] = f"{type(exc).__name__}: {exc}"
    cleanup_log = case_dir / "cleanup-result.json"
    if cleanup_log.is_file():
        try:
            base["cleanupAfter"] = json.loads(cleanup_log.read_text(encoding="utf-8"))
        except Exception:
            pass
    return base


def _cleanup(out_dir: Path) -> dict[str, Any]:
    runner = REPO_ROOT / "scripts" / "cleanup_ua2_resources.py"
    result_path = out_dir / "cleanup-after-all.json"
    cmd = [sys.executable, str(runner), "--result", str(result_path)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120)
        payload: dict[str, Any] = {
            "exitCode": proc.returncode,
            "stdout": (proc.stdout or "")[-1000:],
            "stderr": (proc.stderr or "")[-1000:],
        }
        if result_path.is_file():
            payload["report"] = json.loads(result_path.read_text(encoding="utf-8"))
        return payload
    except subprocess.TimeoutExpired:
        return {"exitCode": -1, "error": "cleanup exceeded 120s"}


def _cleanup_after_case(out_dir: Path, case_id: str) -> dict[str, Any]:
    runner = REPO_ROOT / "scripts" / "cleanup_ua2_resources.py"
    result_path = out_dir / "cases" / case_id / "cleanup-result.json"
    cmd = [sys.executable, str(runner), "--result", str(result_path)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60)
        return {
            "exitCode": proc.returncode,
            "report": json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None,
            "stderr": (proc.stderr or "")[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"exitCode": -1, "error": "case cleanup exceeded 60s"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", default=str(REPO_ROOT / "output"))
    args = parser.parse_args()

    out_root = Path(args.out_root)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = out_root / f"automation_ua2_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "selectedCases": list(CASES_UA2),
        "selectedCount": len(CASES_UA2),
        "caseResults": [],
        "passCount": 0,
        "failCount": 0,
        "errorCount": 0,
        "blockedCount": 0,
        "timeoutCount": 0,
        "cleanupFailedCount": 0,
        "mockProcess": None,
        "startedAt": "",
        "finishedAt": "",
        "status": "FAIL",
    }

    if not os.environ.get("DATAHUB_PASSWORD"):
        (out_dir / "result.json").write_text(
            json.dumps({"status": "FAIL", "error": "DATAHUB_PASSWORD is required"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 2

    started = time.monotonic()
    deadline_ts = started + CHAPTER_TOTAL_TIMEOUT
    summary["startedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))

    prereq_results = []
    prereq_results.append(phase_compile(deadline_ts))
    prereq_results.append(phase_unit_tests(deadline_ts))
    catalog_path = out_dir / "catalog.json"
    prereq_results.append(phase_catalog(catalog_path, deadline_ts))
    inventory_path = out_dir / "case-inventory.json"
    prereq_results.append(phase_inventory(inventory_path, deadline_ts))

    summary["prerequisites"] = prereq_results

    mock_handle = _start_mock(out_dir, deadline_ts)
    summary["mockProcess"] = {
        "started": bool(mock_handle.get("started")),
        "readyInSec": mock_handle.get("readyInSec"),
        "error": mock_handle.get("error"),
    }

    if not mock_handle.get("started"):
        _stop_mock(mock_handle)
        summary["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        summary["status"] = "FAIL"
        (out_dir / "ua2-result.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 1

    case_results: list[dict[str, Any]] = []
    allowed_retry = {"ERROR", "TIMEOUT"}
    for case_id in CASES_UA2:
        if time.monotonic() >= deadline_ts:
            break
        attempts = 0
        result: dict[str, Any] = {"caseId": case_id, "status": "UNKNOWN"}
        while attempts < 2:
            attempts += 1
            result = _run_single_case(out_dir, case_id)
            status = result.get("status")
            if status not in allowed_retry or attempts == 2:
                break
        cleanup_report = _cleanup_after_case(out_dir, case_id)
        result["cleanupAfter"] = cleanup_report
        case_results.append(result)

        st = result.get("status")
        if st == "PASS":
            summary["passCount"] += 1
        elif st == "FAIL":
            summary["failCount"] += 1
        elif st == "ERROR":
            summary["errorCount"] += 1
        elif st == "BLOCKED":
            summary["blockedCount"] += 1
        elif st == "TIMEOUT":
            summary["timeoutCount"] += 1
        if result.get("cleanupStatus") == "CLEANUP_FAILED" or (cleanup_report.get("report") or {}).get("residualDatasources", 0) > 0:
            summary["cleanupFailedCount"] += 1

    summary["caseResults"] = case_results
    summary["finalCleanup"] = _cleanup(out_dir)

    _stop_mock(mock_handle)
    summary["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary["status"] = "PASS" if (
        summary["passCount"] == summary["selectedCount"]
        and summary["cleanupFailedCount"] == 0
    ) else "FAIL"

    (out_dir / "ua2-result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
