"""UA-2 automation runner (Python 版).

不走 PowerShell pipeline;每条 Case 用独立进程 + 超时 + 强制 cleanup。

阶段:
  1. 预检 DATAHUB_PASSWORD
  2. compileall ua_test_harness (180s)
  3. unit tests (300s)
  4. catalog export (180s)
  5. inventory strict (180s)
  6. 启动 ua_mocker/ua2_types.yaml (端口 18965)
  7. 启动 ua_mocker/ua2_empty.yaml (端口 18967)
  8. ensure_ua2_baseline 在 TPT 服务器上 provision/校验两个共享 DS
     (失败 -> BLOCKED,停 mock,exit 1)
  9. 16 条 Case 各跑独立子进程(普通 180s / 删除恢复 240s)
 10. 每条 Case 跑完后只清 ua_case_ua2_ 私有位号(调 cleanup_ua2_resources 默认前缀)
 11. 批次结束**不删共享 DS** -- 不调 teardown_ua2_baseline
 12. 停两个 mock,汇总 ua2-result.json
 13. pass/fail/所有 PASS + 无 cleanup-failed 才 exit 0
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from ua_test_harness.env_config import load_env_json

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

SHARED_TYPES_DS_NAME = "ua_shared_ua2_types_ds"
SHARED_EMPTY_DS_NAME = "ua_shared_ua2_empty_ds"
TYPES_PORT = 18965
EMPTY_PORT = 18967


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


def _start_mock_at(yaml_name: str, port: int, out_dir: Path, deadline_ts: float,
                   ip: str = "127.0.0.1") -> dict[str, Any]:
    """Generic mock starter: spawns ua_mocker/main.py with the given YAML, waits
    for the listening port to accept a TCP connection.
    """
    yaml_path = REPO_ROOT / "ua_mocker" / yaml_name
    stdout_path = out_dir / f"mock-{yaml_name}.stdout.log"
    stderr_path = out_dir / f"mock-{yaml_name}.stderr.log"
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
            sock = socket.socket()
            sock.settimeout(0.5)
            sock.connect((ip, port))
            sock.close()
            return {
                "started": True,
                "readyInSec": round(time.monotonic() - started, 2),
                "pid": proc.pid,
                "port": port,
                "yaml": yaml_name,
                "stdoutPath": str(stdout_path),
                "stderrPath": str(stderr_path),
                "_proc": proc,
            }
        except Exception:
            time.sleep(0.5)
    proc.kill()
    return {
        "started": False,
        "readyInSec": round(time.monotonic() - started, 2),
        "port": port,
        "yaml": yaml_name,
        "error": "mock did not become ready",
    }


def _stop_mock(handle: dict[str, Any]) -> None:
    proc = handle.get("_proc") if handle else None
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _mock_summary(handle: dict[str, Any]) -> dict[str, Any]:
    return {
        "started": bool(handle.get("started")),
        "readyInSec": handle.get("readyInSec"),
        "port": handle.get("port"),
        "yaml": handle.get("yaml"),
        "error": handle.get("error"),
    }


def _provision_shared_baseline(local_ip: str, deadline_ts: float) -> tuple[dict[str, Any], Any | None]:
    """Provision the shared baseline DS (ua_shared_ua2_types_ds + empty_ds).

    Returns (summary_entry, baseline_or_None). On BaselineError, summary_entry
    has status=BLOCKED and baseline_or_None is None.
    """
    from unittest.mock import MagicMock
    from ua_test_harness.config import RunConfig
    from ua_test_harness.context import RunContext
    from ua_test_harness.provisioning import ensure_ua2_baseline

    pcfg = RunConfig()
    pcfg.run_id = f"ua2_baseline_{int(time.time())}"
    pcfg.local_ip = local_ip
    pcfg.mock.endpoints.functional = f"opc.tcp://{local_ip}:{TYPES_PORT}/ua_mocker/"
    env = load_env_json()
    pcfg.subject.base_url = env.get("baseUrl", "")
    pcfg.subject.username = env.get("username", "admin")
    pcfg.subject.password = env.get("password", "")
    pcfg.subject.tenant_id = env.get("tenantId", "")

    pctx = RunContext(config=pcfg, emitter=MagicMock())

    if time.monotonic() >= deadline_ts:
        return {"status": "BLOCKED", "error": "chapter deadline already elapsed"}, None
    try:
        baseline = ensure_ua2_baseline(pctx)
        return (
            {
                "status": "OK",
                "typesDatasourceName": baseline.types_ds_name,
                "typesDatasourceId": baseline.types_ds_id,
                "typesEndpoint": baseline.types_endpoint,
                "emptyDatasourceName": baseline.empty_ds_name,
                "emptyDatasourceId": baseline.empty_ds_id,
                "emptyEndpoint": baseline.empty_endpoint,
            },
            baseline,
        )
    except Exception as exc:
        return (
            {
                "status": "BLOCKED",
                "error": f"{type(exc).__name__}: {exc}",
            },
            None,
        )


def _case_timeout(case_id: str) -> float:
    if case_id.startswith("UA-2-4-"):
        return CASE_TIMEOUTS["delete"]
    return CASE_TIMEOUTS["default"]


def _build_case_run_config(case_dir: Path, case_id: str, baseline,
                           local_ip: str) -> dict[str, Any]:
    env = load_env_json()
    payload = {
        "runId": f"ua2_{case_id}",
        "selectedCaseIds": [case_id],
        "subject": {
            "baseUrl": env.get("baseUrl", ""),
            "tenantId": env.get("tenantId", ""),
            "username": env.get("username", "admin"),
            "password": env.get("password", ""),
            "token": "",
        },
        "localIp": local_ip,
        "mock": {
            "controlMode": "external-script",
            "endpoints": {
                "functional": f"opc.tcp://{local_ip}:{TYPES_PORT}/ua_mocker/",
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
    if baseline is not None:
        payload["ua2Baseline"] = {
            "typesDatasourceName": baseline.types_ds_name,
            "typesEndpoint": baseline.types_endpoint,
            "emptyDatasourceName": baseline.empty_ds_name,
            "emptyEndpoint": baseline.empty_endpoint,
        }
    return payload


def _run_single_case(out_dir: Path, case_id: str, baseline, local_ip: str) -> dict[str, Any]:
    case_dir = out_dir / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = case_dir / "run-config.json"
    payload = _build_case_run_config(case_dir, case_id, baseline, local_ip)
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
    """Final cleanup: case-only (ua_case_ua2_ prefix by default). NEVER deletes shared DS."""
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
    """Per-case cleanup: case-only (default prefix ua_case_ua2_). NEVER touches shared DS."""
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
        "emptyMockProcess": None,
        "baseline": None,
        "startedAt": "",
        "finishedAt": "",
        "status": "FAIL",
    }

    env_cfg = load_env_json()
    if not env_cfg.get("password"):
        (out_dir / "result.json").write_text(
            json.dumps({"status": "FAIL", "error": "env.json missing password"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 2

    started = time.monotonic()
    deadline_ts = started + CHAPTER_TOTAL_TIMEOUT
    summary["startedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))

    local_ip = env_cfg.get("localIp", "127.0.0.1")

    prereq_results = []
    prereq_results.append(phase_compile(deadline_ts))
    prereq_results.append(phase_unit_tests(deadline_ts))
    catalog_path = out_dir / "catalog.json"
    prereq_results.append(phase_catalog(catalog_path, deadline_ts))
    inventory_path = out_dir / "case-inventory.json"
    prereq_results.append(phase_inventory(inventory_path, deadline_ts))

    summary["prerequisites"] = prereq_results

    # 6. start types mock
    mock_types = _start_mock_at("ua2_types.yaml", TYPES_PORT, out_dir, deadline_ts, ip=local_ip)
    summary["mockProcess"] = _mock_summary(mock_types)

    # 7. start empty mock
    mock_empty = _start_mock_at("ua2_empty.yaml", EMPTY_PORT, out_dir, deadline_ts, ip=local_ip)
    summary["emptyMockProcess"] = _mock_summary(mock_empty)

    if not (mock_types.get("started") and mock_empty.get("started")):
        _stop_mock(mock_types)
        _stop_mock(mock_empty)
        summary["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        summary["status"] = "FAIL"
        (out_dir / "ua2-result.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 1

    # 9. provision shared baseline (BLOCKED -> stop mocks, exit 1)
    baseline_summary, baseline = _provision_shared_baseline(local_ip, deadline_ts)
    summary["baseline"] = baseline_summary
    if baseline is None:
        _stop_mock(mock_types)
        _stop_mock(mock_empty)
        summary["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        summary["status"] = "FAIL"
        (out_dir / "ua2-result.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 1

    # 10. run 16 cases (each in own subprocess)
    case_results: list[dict[str, Any]] = []
    allowed_retry = {"ERROR", "TIMEOUT"}
    for case_id in CASES_UA2:
        if time.monotonic() >= deadline_ts:
            break
        attempts = 0
        result: dict[str, Any] = {"caseId": case_id, "status": "UNKNOWN"}
        while attempts < 2:
            attempts += 1
            result = _run_single_case(out_dir, case_id, baseline, local_ip)
            status = result.get("status")
            if status not in allowed_retry or attempts == 2:
                break
        # 11. per-case cleanup (case-only default prefix ua_case_ua2_)
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
        _cleanup_report = cleanup_report.get("report") or {}
        _residual = (
            _cleanup_report.get("residualActive", 0)
            or _cleanup_report.get("residualRecycle", 0)
            or _cleanup_report.get("residualCaseDatasources", 0)
        )
        if result.get("cleanupStatus") == "CLEANUP_FAILED" or _residual:
            summary["cleanupFailedCount"] += 1

    summary["caseResults"] = case_results
    # 12. batch end: NO teardown_ua2_baseline call (shared DS persist).
    summary["finalCleanup"] = _cleanup(out_dir)

    # 13. stop both mocks
    _stop_mock(mock_types)
    _stop_mock(mock_empty)
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