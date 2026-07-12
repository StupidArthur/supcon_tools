"""Document Case exact-execution dispatch.

调度顺序:
  UA-1 -> execute_ua1_case
  UA-2 -> execute_ua2_case (章节 dispatcher)
  其他 -> _execute_shared

未接适配器的 case 仍返回 BLOCKED,精确说明缺口类别,不允许退化冒烟。
"""
from __future__ import annotations

from dataclasses import dataclass

from ua_test_harness.models import CaseStatus
from ua_test_harness.scenario_runtime import execute_documented_case as _execute_shared
from ua_test_harness.ua1_runtime import execute_ua1_case
from ua_test_harness.ua2_registry import ua2_supported_sets
from ua_test_harness.ua2_runtime import is_supported_ua2, execute_ua2_case


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
    "UA-1-1": "需要鉴权 Mock、质量码扩展配置或不可达转可达控制夹具",
    "UA-1-2": "历史增长/停增场景需要稳定历史落库夹具",
    "UA-1-3": "需要隔离的 Mock 停启控制、断线时间线和恢复证据执行器",
    "UA-1-4": "需要两个独立 Mock endpoint 和双源隔离夹具",
    "UA-1-5": "需要启用删除、有位号删除、回收站关联和多数据源删除执行器",
    "UA-1-6": "需要 ds-info/test testType=1..5 的 tpt_api 适配器",
    "UA-2-3": "需要导入导出上传下载适配器及 xlsx 夹具",
    "UA-2-5": "需要完整分组树、移动、收藏、循环检测和批量操作执行器",
    "UA-2-1": "未在 UA-2 第一批精确清单内的 case 需要 queryWithQuality、异常映射、空名边界或长名边界执行器",
    "UA-2-2": "未在 UA-2 第一批精确清单内的 case 需要 queryWithQuality、底层节点浏览、分组/收藏和分页选择器适配器",
    "UA-2-4": "未在 UA-2 第一批精确清单内的 case 需要批量、恢复、删除影响、重建和历史生命周期执行器",
    "UA-3-1": "需要 13 类型源端对照、频率、断线、多源和历史落地执行器",
    "UA-3-2": "需要 ID/分组/数据库/queryTime 选择器和删除恢复执行器",
    "UA-3-3": "需要批量类型、失败隔离、时间质量、源端对照和并发写执行器",
    "UA-3-4": "需要确定历史导入夹具、分页、采样和双接口一致性执行器",
    "UA-3-5": "需要 100 位号、写入和历史查询响应时间夹具",
    "UA-3-6": "需要可配置并发、批量、长稳、历史负载和恢复测试引擎",
}


@dataclass(frozen=True)
class ScenarioDecision:
    executable: bool
    scenario: str = ""
    reason: str = ""


def classify_case(meta) -> ScenarioDecision:
    case_id = meta["id"]
    if case_id.startswith("UA-3-"):
        return ScenarioDecision(True, scenario=_ua3_scenario_for(meta))
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
    return _execute_shared(ctx, cc, meta)
