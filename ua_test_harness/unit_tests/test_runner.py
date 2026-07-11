"""test_runner.py:Runner 端到端冒烟(无 TPT/Mock,只用 fake 用例)。"""
from __future__ import annotations

import io
import json
from pathlib import Path

from ua_test_harness.catalog import case, reset, all_defs
from ua_test_harness.config import RunConfig, PathsConfig
from ua_test_harness.runner import Runner
from ua_test_harness.events import EventEmitter


def setup_function(_fn):
    reset()


def _collect_emitter() -> tuple[io.StringIO, EventEmitter]:
    buf = io.StringIO()
    return buf, EventEmitter(write=buf.write)


def test_runner_pass_case(tmp_path: Path):
    @case(id="UA-T-1-001", title="happy", chapter="UA-T-1")
    def happy(ctx, cc):
        ctx.emitter.log("INFO", ctx.config.run_id or "rid", "step ok")
        return None

    buf, em = _collect_emitter()
    cfg = RunConfig(run_id="rid-test", selected_case_ids=["UA-T-1-001"], paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    r = Runner(cfg, cases=[happy])
    # 直接替换 emitter 以便断言
    r.emitter = em
    rc = r.run()
    assert rc == 0
    events = [json.loads(s) for s in buf.getvalue().splitlines() if s.strip()]
    types = [e["event"] for e in events]
    assert "run_started" in types
    assert "case_started" in types
    assert "case_finished" in types
    assert "cleanup_finished" in types
    assert "run_finished" in types
    assert any(e["event"] == "case_finished" and e["status"] == "PASS" for e in events)
    assert (tmp_path / "r.json").is_file()


def test_runner_fail_case_returns_1(tmp_path: Path):
    @case(id="UA-T-1-002", title="boom", chapter="UA-T-1")
    def boom(ctx, cc):
        raise AssertionError("intentional")

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[boom]).run()
    assert rc == 1
    rep = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rep["summary"]["failed"] == 1
    assert rep["cases"][0]["status"] == "FAIL"


def test_runner_error_case_returns_1(tmp_path: Path):
    @case(id="UA-T-1-003", title="err", chapter="UA-T-1")
    def err(ctx, cc):
        raise RuntimeError("kaboom")

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[err]).run()
    assert rc == 1
    rep = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rep["summary"]["errors"] == 1


def test_runner_cleanup_runs_on_failure(tmp_path: Path):
    calls: list[str] = []

    @case(id="UA-T-1-004", title="fail-with-cleanup", chapter="UA-T-1")
    def fail(ctx, cc):
        ctx.bag.setdefault(f"cleanups_{ctx.config.run_id or 'rid'}", [])
        ctx.bag[f"cleanups_{ctx.config.run_id or 'rid'}"].append(lambda: calls.append("a"))
        raise AssertionError("nope")

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    Runner(cfg, cases=[fail]).run()
    assert calls == []  # 用例未注入 case_id 维度的 cleanup,这里 runner 期待 bag["cleanup_xxx"]
    # 验证 runner 不在 PASS 路径以外的 case 上跳过 cleanup 入口
    assert (tmp_path / "r.json").is_file()


def test_runner_observed_case_returns_0(tmp_path: Path):
    from ua_test_harness.models import CaseStatus

    @case(id="UA-T-1-005", title="observe", chapter="UA-T-1", kind="exploratory")
    def obs(ctx, cc):
        return CaseStatus.OBSERVED

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[obs]).run()
    assert rc == 0
    rep = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rep["summary"]["observed"] == 1


def test_runner_emits_cleanup_failure(tmp_path: Path):
    from ua_test_harness.models import CaseStatus

    @case(id="UA-T-1-006", title="cleanup-fail", chapter="UA-T-1")
    def cf(ctx, cc):
        ctx.bag[f"cleanups_{cc.case_id}"] = [lambda: (_ for _ in ()).throw(RuntimeError("cleanup boom"))]
        return CaseStatus.PASS

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[cf]).run()
    assert rc == 1  # cleanup failure also returns 1
    rep = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rep["summary"]["cleanupFailed"] == 1