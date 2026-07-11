"""报告：把 StepResult 渲染成可读输出。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tpt_checker import TptDsCheckResult, TptFlowCheckResult, TptTagsCheckResult
from .ua_client import UaCheckResult


# 各步骤的统一结构
@dataclass
class StepResult:
    index: int
    name: str
    passed: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0


# 4 步检查的总结果
@dataclass
class LoopResult:
    steps: list[StepResult]
    mocker_endpoint: str
    tpt_url: str

    @property
    def is_closed(self) -> bool:
        return all(s.passed for s in self.steps)

    @property
    def passed_count(self) -> int:
        return sum(1 for s in self.steps if s.passed)

    def summary(self) -> str:
        total = len(self.steps)
        passed = self.passed_count
        total_time = sum(s.duration_seconds for s in self.steps)
        status = "Loop is closed." if self.is_closed else "Loop is broken."
        return f"{passed}/{total} steps passed in {total_time:.1f}s. {status}"


def format_step_line(step: StepResult, verbose: bool = False) -> str:
    """把单步格式化成单行输出。"""
    marker = "PASS" if step.passed else "FAIL"
    line = f"[{step.index}/4] {step.name:<22}: {marker}  ({step.summary})"
    if step.error:
        line += f"\n    ! {step.error}"
    if verbose and step.details:
        # 详细模式：打印 details
        for k, v in step.details.items():
            if v in (None, "", [], {}):
                continue
            line += f"\n    - {k}: {v}"
    return line


def format_loop_report(result: LoopResult, verbose: bool = False) -> str:
    """把整个 LoopResult 格式化成完整报告。"""
    lines: list[str] = []
    lines.append(f"=== ua_tpt_loop 检查报告 ===")
    lines.append(f"  ua-server : {result.mocker_endpoint}")
    lines.append(f"  tpt       : {result.tpt_url}")
    lines.append("")
    for step in result.steps:
        lines.append(format_step_line(step, verbose=verbose))
    lines.append("")
    lines.append(result.summary())
    return "\n".join(lines)


# 各步骤的"summary 字段"统一从子结果里取
def summarize_ua(r: UaCheckResult) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {}
    if r.sample_values:
        details["sample_values"] = {k: v for k, v in list(r.sample_values.items())[:5]}
    return (r.details or r.error or ""), details


def summarize_ds(r: TptDsCheckResult) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {}
    if r.ds_id is not None:
        details["ds_id"] = r.ds_id
    if r.ds_name is not None:
        details["ds_name"] = r.ds_name
    return (r.details or r.error or ""), details


def summarize_tags(r: TptTagsCheckResult) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {
        "expected": r.expected,
        "existing": r.existing,
        "registered": r.registered,
        "skipped(tpt_unsupported)": r.skipped,
    }
    return (r.details or r.error or ""), details


def summarize_flow(r: TptFlowCheckResult) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {
        "tag_count": r.tag_count,
        "flowing_count": r.flowing_count,
    }
    if r.sample:
        details["sample_per_tag"] = r.sample
    return (r.details or r.error or ""), details
