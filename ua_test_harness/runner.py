"""runner.py:核心执行引擎。

职责(plan.md 5):
- 接收 RunConfig + 已发现的 CaseDef 列表
- 串行执行每个用例
- 每个用例:setup -> step loop -> main -> cleanup -> 触发事件
- 资源 LIFO 清理
- 输出 report.json
- stdout 全部为 NDJSON 事件;stderr + 文件日志

返回码(plan.md 5.1):
- 0  任务正常完成(允许 OBSERVED/MEASURED)
- 1  存在 FAIL/ERROR/CLEANUP_FAILED
- 2  配置错误或无法启动
- 130 收到停止信号
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .catalog import all_defs, discover
from .config import RunConfig
from .context import RunContext
from .events import EventEmitter
from .models import CaseDef, CaseResult, CaseStatus, Metric, Evidence, RunStats, StepResult, StepDef
from .report import build_report, write_report


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class CancellationToken:
    """线程安全的取消令牌。"""

    def __init__(self) -> None:
        self._evt = threading.Event()

    def cancel(self) -> None:
        self._evt.set()

    def cancelled(self) -> bool:
        return self._evt.is_set()


def _setup_file_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger("ua_test_harness.runner")
    lg.setLevel(logging.DEBUG)
    for h in list(lg.handlers):
        lg.removeHandler(h)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    lg.addHandler(fh)
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(logging.Formatter("[runner %(levelname)s] %(message)s"))
    lg.addHandler(sh)
    lg.propagate = False
    return lg


class Runner:
    def __init__(
        self,
        config: RunConfig,
        *,
        cases: list | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.config = config
        self.emitter = EventEmitter()
        self.cases = self._normalize_cases(cases) if cases is not None else all_defs()
        self.stats = RunStats()
        self.results: list[CaseResult] = []
        self.token = CancellationToken()
        self.started_at = ""
        self.finished_at = ""
        self.logger: logging.Logger | None = None
        self._sig_installed = False

    @staticmethod
    def _normalize_cases(cases: list) -> list[CaseDef]:
        out: list[CaseDef] = []
        for c in cases:
            if isinstance(c, CaseDef):
                out.append(c)
            elif callable(c) and hasattr(c, "__ua_case_def__"):
                out.append(c.__ua_case_def__)
            else:
                raise TypeError(f"unsupported case entry: {c!r}")
        return out

    # 对外 API -----------------------------------------------------------
    def run(self) -> int:
        cfg = self.config
        try:
            self.started_at = _now()
            run_dir = Path(cfg.paths.run_dir) if cfg.paths.run_dir else None
            self.logger = _setup_file_logger(run_dir / "runner.log" if run_dir else Path("./runner.log"))
            self._install_signals()
            self._emit_log(f"run started id={cfg.run_id} total={len(self.cases)}")
            self.emitter.run_started(cfg.run_id, len(self.cases))
            ctx = RunContext(
                config=cfg,
                emitter=self.emitter,
                evidence_root=run_dir,
                log_path=(run_dir / "runner.log") if run_dir else None,
                cancellation_token=self.token,
            )
            for idx, c in enumerate(self.cases, 1):
                if self.token.cancelled():
                    self._emit_log(f"cancellation received, stop at {c.id}")
                    break
                self._run_one(ctx, c, idx)
            self.finished_at = _now()
            status = self._overall_status()
            self.emitter.run_finished(status, self.stats.to_dict())
            report = build_report(
                run_id=cfg.run_id,
                started_at=self.started_at,
                finished_at=self.finished_at,
                status=status,
                stats=self.stats,
                cases=self.results,
                note=cfg.note,
            )
            if cfg.paths.report_path:
                write_report(report, cfg.paths.report_path)
                self._emit_log(f"report written: {cfg.paths.report_path}")
            self._emit_log(f"run finished status={status} summary={self.stats.to_dict()}")
            if status == "CANCELLED":
                return 130
            if status in ("FAIL", "ERROR", "CLEANUP_FAILED"):
                return 1
            return 0
        except _ConfigError as e:
            self._emit_log(f"config error: {e}", level="ERROR")
            return 2

    # 单用例执行 ----------------------------------------------------------
    def _run_one(self, ctx: RunContext, c: CaseDef, index: int) -> None:
        cr = CaseResult(case_id=c.id, title=c.title)
        cr.started_at = _now()
        self.emitter.case_started(c.id, index, len(self.cases))
        t0 = time.monotonic()
        case_status: CaseStatus = CaseStatus.PASS
        summary = ""
        try:
            cc = ctx.case_context(c.id, c.title)
            cr.steps = []
            # 步骤 0: setup / precondition(由用例 impl_func 自行实现,这里只走主流程)
            cr.steps.append(StepResult(case_id=c.id, step_id="setup", title="setup", status=CaseStatus.RUNNING, started_at=_now()))
            # 用例主体
            outcome = c.impl_func(ctx, cc)
            # outcome 可为 CaseStatus 或 None;None 表示 PASS
            if isinstance(outcome, CaseStatus):
                case_status = outcome
            elif isinstance(outcome, str):
                case_status = CaseStatus.from_str(outcome)
            # 收尾最后一步
            cr.steps[-1].status = CaseStatus.PASS
            cr.steps[-1].finished_at = _now()
            cr.steps[-1].duration_ms = int((time.monotonic() - t0) * 1000)
        except _Cancelled:
            case_status = CaseStatus.CANCELLED
            summary = "cancelled"
        except AssertionError as e:
            case_status = CaseStatus.FAIL
            summary = f"assert: {e}"
            self._emit_log(f"case {c.id} FAIL: {e}", level="ERROR")
        except Exception as e:
            case_status = CaseStatus.ERROR
            summary = f"error: {e}"
            tb = traceback.format_exc()
            self._emit_log(f"case {c.id} ERROR: {e}\n{tb}", level="ERROR")
            if cc := getattr(c, "_last_cc", None):
                # 已无引用,忽略
                pass
        finally:
            # cleanup 始终执行,独立 try/except 包裹以免主异常吞掉清理错误
            try:
                cc_obj = ctx.registry  # 仅清理 run 级,case 级清理在 step 里做
            except Exception:
                cc_obj = None
        # 清理 case 级资源
        cleanup_status, cleanup_msg = self._cleanup_case(ctx, c)
        if cleanup_status == CaseStatus.CLEANUP_FAILED:
            self.stats.add(CaseStatus.CLEANUP_FAILED)
        cr.cleanup_status = cleanup_status
        cr.cleanup_message = cleanup_msg
        cr.status = case_status
        cr.finished_at = _now()
        cr.duration_ms = int((time.monotonic() - t0) * 1000)
        if not summary:
            summary = case_status.value
        cr.summary = summary
        self.stats.add(case_status)
        self.results.append(cr)
        self.emitter.case_finished(c.id, cr.status.value, cr.duration_ms, summary=summary)
        self.emitter.cleanup_finished(c.id, cr.cleanup_status.value, message=cr.cleanup_message)

    def _cleanup_case(self, ctx: RunContext, c: CaseDef) -> tuple[CaseStatus, str]:
        """执行用例级 cleanup,并捕获错误。

        用例 impl_func 应该把清理动作 register 到 ctx(新分配的 CaseContext)上;
        但当前简化模型里,用例自带 cleanup_func 字段;为兼容,这里按惯例查找
        ctx.bag[f"cleanup_{c.id}"]。
        """
        cleanup_status = CaseStatus.PASS
        msg = ""
        bag_key = f"cleanup_{c.id}"
        cleanup = ctx.bag.pop(bag_key, None) if isinstance(ctx.bag, dict) else None
        # 同时也支持列表
        cleanups: list = []
        if isinstance(cleanup, list):
            cleanups = cleanup
        elif callable(cleanup):
            cleanups = [cleanup]
        # 兼容:从 bag 取 list
        list_key = f"cleanups_{c.id}"
        extra = ctx.bag.pop(list_key, None) if isinstance(ctx.bag, dict) else None
        if isinstance(extra, list):
            cleanups.extend(extra)
        for fn in reversed(cleanups):
            try:
                fn()
            except Exception as e:
                cleanup_status = CaseStatus.CLEANUP_FAILED
                msg = f"{e}"
                self._emit_log(f"cleanup {c.id}: {e}", level="ERROR")
        return cleanup_status, msg

    # 辅助 --------------------------------------------------------------
    def _overall_status(self) -> str:
        if self.stats.failed or self.stats.errors:
            return "FAIL"
        if self.stats.cleanup_failed:
            return "CLEANUP_FAILED"
        if any(r.status == CaseStatus.CANCELLED for r in self.results):
            return "CANCELLED"
        return "FINISHED"

    def _emit_log(self, message: str, level: str = "INFO") -> None:
        if self.logger:
            getattr(self.logger, level.lower(), self.logger.info)(message)
        # 同时 NDJSON log 事件
        self.emitter.log(level, case_id=None, message=message)

    def _install_signals(self) -> None:
        if self._sig_installed:
            return
        self._sig_installed = True

        def _h(signum, _frame):
            self._emit_log(f"signal {signum} received, cancelling", level="WARN")
            self.token.cancel()

        try:
            signal.signal(signal.SIGINT, _h)
            signal.signal(signal.SIGTERM, _h)
        except (ValueError, OSError):
            # 子线程 / Windows 某些情况无法注册
            pass


class _ConfigError(Exception):
    pass


class _Cancelled(Exception):
    pass