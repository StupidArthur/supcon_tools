"""文档 Case 的执行精确度策略。

只有共享执行器已覆盖文档动作和核心断言时才执行；其余返回带原因的 BLOCKED，
防止用普通在线冒烟代替异常、批量、导入导出、重连或性能边界场景。
"""
from __future__ import annotations

from ua_test_harness.models import CaseStatus
from ua_test_harness.scenario_runtime import execute_documented_case as _execute


_SUPPORTED = {
    # UA-1-2 的启停动作由 datasource-state/history 执行器覆盖。
    "UA-1-2": {f"UA-1-2-{index:02d}" for index in range(1, 9)},
    # 位号新增的最小在线闭环。
    "UA-2-1": {"UA-2-1-001", "UA-2-1-002"},
    # 查询列表、完整名称、配置字段和重复稳定性。
    "UA-2-2": {"UA-2-2-001", "UA-2-2-004", "UA-2-2-005", "UA-2-2-006"},
    # 删除的首个软删、物理删除闭环。
    "UA-2-4": {"UA-2-4-001", "UA-2-4-020"},
    # 根节点创建和空节点删除。
    "UA-2-5": {"UA-2-5-004", "UA-2-5-018"},
    # 初始、变化、静态采集和质量时间冒烟。
    "UA-3-1": {"UA-3-1-001", "UA-3-1-002", "UA-3-1-003", "UA-3-1-010"},
    # 按名称读取和连续读取稳定性。
    "UA-3-2": {"UA-3-2-001", "UA-3-2-021"},
    # 单个位号写入读回。
    "UA-3-3": {"UA-3-3-001"},
    # 基础历史接口；无历史夹具时执行器会明确 BLOCKED。
    "UA-3-4": {"UA-3-4-001"},
    # 单个位号响应时间基线。
    "UA-3-5": {"UA-3-5-001"},
    # 实时读低并发基线。
    "UA-3-6": {"UA-3-6-001"},
}


_BLOCK_REASONS = {
    "UA-1-3": "需要隔离的 Mock 停启控制、断线时间线和恢复证据执行器",
    "UA-1-4": "需要两个独立 Mock endpoint 和双源隔离夹具",
    "UA-1-5": "需要数据源删除矩阵、回收站关联和重建执行器",
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


def execute_documented_case(ctx, cc, meta):
    chapter = meta["chapter"]
    case_id = meta["id"]
    if case_id in _SUPPORTED.get(chapter, set()):
        return _execute(ctx, cc, meta)
    reason = _BLOCK_REASONS.get(chapter, f"章节 {chapter} 尚无精确共享执行器")
    ctx.emitter.log("WARN", case_id, f"BLOCKED: {reason}")
    return CaseStatus.BLOCKED
