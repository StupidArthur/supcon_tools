"""Document Case exact-execution dispatch.

调度顺序:
  UA-1 -> execute_ua1_case
  UA-2 -> execute_ua2_case (章节 dispatcher)
  UA-3 -> execute_ua3_case (章节 dispatcher)
  其他 -> _execute_shared (遗留)

419 条文档 Case 均在 _SUPPORTED 中登记;运行时由对应 runtime 执行。
仅 KNOWN_BLOCKED 中的 ID 在真环境中预期 BLOCKED/OBSERVED,不得空函数 PASS。
"""
from __future__ import annotations

from dataclasses import dataclass

from ua_test_harness.models import CaseStatus
from ua_test_harness.scenario_runtime import execute_documented_case as _execute_shared
from ua_test_harness.ua1_runtime import execute_ua1_case
from ua_test_harness.ua2_registry import ua2_supported_sets
from ua_test_harness.ua2_runtime import is_supported_ua2, execute_ua2_case
from ua_test_harness.ua3_runtime import is_supported_ua3, execute_ua3_case


def _ua1_all_supported() -> dict[str, set[str]]:
    from pathlib import Path
    from ua_test_harness.case_inventory import load_documented_cases

    rows, _ = load_documented_cases(Path(__file__).resolve().parents[1])
    out: dict[str, set[str]] = {}
    for row in rows:
        if not row["id"].startswith("UA-1-"):
            continue
        out.setdefault(row["chapter"], set()).add(row["id"])
    return out


def _ua3_all_supported() -> dict[str, set[str]]:
    from pathlib import Path
    from ua_test_harness.case_inventory import load_documented_cases

    rows, _ = load_documented_cases(Path(__file__).resolve().parents[1])
    out: dict[str, set[str]] = {}
    for row in rows:
        if not row["id"].startswith("UA-3-"):
            continue
        out.setdefault(row["chapter"], set()).add(row["id"])
    return out


_SUPPORTED = {
    **_ua1_all_supported(),
    **ua2_supported_sets(),
    **_ua3_all_supported(),
}


_SHARED_SCENARIOS = {
    "UA-3-1-001": "rt_read",
    "UA-3-1-002": "rt_read",
    "UA-3-1-003": "rt_read",
    "UA-3-1-010": "rt_read",
    "UA-3-2-001": "rt_read",
    "UA-3-2-021": "rt_read",
    "UA-3-3-001": "rt_write",
    "UA-3-4-001": "history",
    "UA-3-5-001": "response_time",
    "UA-3-6-001": "performance",
}


def _ua3_scenario_for(meta) -> str:
    cid = meta["id"]
    title = meta.get("title") or ""
    if cid in _SHARED_SCENARIOS:
        return _SHARED_SCENARIOS[cid]
    if "写" in title or "回写" in title:
        return "rt_write"
    if "历史" in title:
        return "history"
    if "响应" in title or "响应时间" in title:
        return "response_time"
    if "性能" in title or "并发" in title or "长稳" in title:
        return "performance"
    if "数据源" in title or "启用" in title or "禁用" in title:
        return "datasource_state"
    if "删除" in title or "软删" in title or "物理" in title:
        return "tag_delete"
    if "查询" in title or "列表" in title:
        return "tag_query"
    return "rt_read"


_BLOCK_REASONS = {
    # 仅当 case 不在 _SUPPORTED 时使用的兜底说明
    "UA-2-2": "文档 Case 未纳入 supported 矩阵",
}


@dataclass(frozen=True)
class ScenarioDecision:
    executable: bool
    scenario: str = ""
    reason: str = ""


def classify_case(meta) -> ScenarioDecision:
    case_id = meta["id"]
    if case_id.startswith("UA-3-"):
        if is_supported_ua3(case_id):
            return ScenarioDecision(True, scenario="ua3_runtime")
        return ScenarioDecision(False, reason=f"UA-3 handler missing for {case_id}")
    if case_id.startswith("UA-2-"):
        if is_supported_ua2(case_id):
            return ScenarioDecision(True, scenario="ua2_runtime")
        return ScenarioDecision(False, reason=f"UA-2 handler missing for {case_id}")
    if case_id.startswith("UA-1-"):
        chapter = meta.get("chapter") or ""
        if case_id in _SUPPORTED.get(chapter, set()):
            return ScenarioDecision(True, scenario="ua1_runtime")
        return ScenarioDecision(False, reason=f"UA-1 not in supported matrix: {case_id}")
    scenario = _SHARED_SCENARIOS.get(case_id)
    if scenario:
        return ScenarioDecision(True, scenario=scenario)
    return ScenarioDecision(False, reason=f"no precise shared scenario for {case_id}")


def execute_documented_case(ctx, cc, meta):
    chapter = meta["chapter"]
    case_id = meta["id"]
    if case_id not in _SUPPORTED.get(chapter, set()):
        reason = _BLOCK_REASONS.get(chapter, f"章节 {chapter} 尚无精确共享执行器")
        ctx.emitter.log("WARN", case_id, f"BLOCKED: {reason}")
        return CaseStatus.BLOCKED
    if chapter.startswith("UA-1-"):
        return execute_ua1_case(ctx, cc, meta)
    if chapter.startswith("UA-2-"):
        if not is_supported_ua2(case_id):
            ctx.emitter.log(
                "WARN",
                case_id,
                "BLOCKED: UA-2 在 registered set 中但未挂 handler;"
                " 需要 queryWithQuality、asyncua、批量、导入导出或分组适配器。",
            )
            return CaseStatus.BLOCKED
        return execute_ua2_case(ctx, cc, meta)
    if chapter.startswith("UA-3-"):
        if not is_supported_ua3(case_id):
            ctx.emitter.log(
                "WARN",
                case_id,
                "BLOCKED: UA-3 在 registered set 中但未挂 handler。",
            )
            return CaseStatus.BLOCKED
        return execute_ua3_case(ctx, cc, meta)
    return _execute_shared(ctx, cc, meta)
