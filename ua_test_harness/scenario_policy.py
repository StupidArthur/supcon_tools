"""文档 Case 的执行精确度策略。

只有共享执行器已覆盖文档动作和核心断言时才执行；其余返回带原因的 BLOCKED，
防止用普通在线冒烟代替异常、批量、导入导出、重连或性能边界场景。
"""
from __future__ import annotations

from dataclasses import dataclass

from ua_test_harness.models import CaseStatus
from ua_test_harness.scenario_runtime import execute_documented_case as _execute_shared
from ua_test_harness.ua1_runtime import execute_ua1_case


_SUPPORTED = {
    "UA-1-1": {"UA-1-1-01", "UA-1-1-02", "UA-1-1-04", "UA-1-1-12"},
    "UA-1-2": {"UA-1-2-01", "UA-1-2-02", "UA-1-2-04", "UA-1-2-06", "UA-1-2-07", "UA-1-2-08"},
    "UA-1-5": {"UA-1-5-01", "UA-1-5-07"},
    "UA-2-1": {"UA-2-1-001", "UA-2-1-002"},
    "UA-2-2": {"UA-2-2-001", "UA-2-2-004", "UA-2-2-005", "UA-2-2-006"},
    "UA-2-4": {"UA-2-4-001", "UA-2-4-020"},
    "UA-2-5": {"UA-2-5-004", "UA-2-5-018"},
    "UA-3-1": {"UA-3-1-001", "UA-3-1-002", "UA-3-1-003", "UA-3-1-010"},
    "UA-3-2": {"UA-3-2-001", "UA-3-2-021"},
    "UA-3-3": {"UA-3-3-001"},
    "UA-3-4": {"UA-3-4-001"},
    "UA-3-5": {"UA-3-5-001"},
    "UA-3-6": {"UA-3-6-001"},
}

_SHARED_SCENARIOS = {
    "UA-2-1-001": "online_smoke",
    "UA-2-1-002": "online_smoke",
    "UA-2-2-001": "tag_query",
    "UA-2-2-004": "tag_query",
    "UA-2-2-005": "tag_query",
    "UA-2-2-006": "tag_query",
    "UA-2-4-001": "tag_delete",
    "UA-2-4-020": "tag_delete",
    "UA-2-5-004": "tag_query",
    "UA-2-5-018": "tag_delete",
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

_BLOCK_REASONS = {
    "UA-1-1": "需要鉴权 Mock、质量码扩展配置或不可达转可达控制夹具",
    "UA-1-2": "历史增长/停增场景需要稳定历史落库夹具",
    "UA-1-3": "需要隔离的 Mock 停启控制、断线时间线和恢复证据执行器",
    "UA-1-4": "需要两个独立 Mock endpoint 和双源隔离夹具",
    "UA-1-5": "需要启用删除、有位号删除、回收站关联和多数据源删除执行器",
    "UA-1-6": "需要 ds-info/test testType=1..5 的 tpt_api 适配器",
    "UA-2-1": "需要按文档参数生成类型、边界、异常映射和批量新增请求",
    "UA-2-2": "需要 queryWithQuality、底层节点浏览、分组/收藏和分页选择器适配器",
    "UA-2-3": "需要导入导出上传下载适配器及 xlsx 夹具",
    "UA-2-4": "需要批量、恢复、删除影响、重建和历史生命周期执行器",
    "UA-2-5": "需要完整分组树、移动、收藏、循环检测和批量操作执行器",
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
    return _execute_shared(ctx, cc, meta)
