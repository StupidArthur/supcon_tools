"""文档明确 BLOCKED / 环境依赖 case 登记 — 有 handler 但预期不 PASS。"""
from __future__ import annotations

# case_id -> 原因（如实记录，不改 case 文档）
KNOWN_BLOCKED: dict[str, str] = {
    "UA-2-2-053": "GUI-DEFERRED: 前端分页状态，等待 GUI 版本",
    "UA-1-4-01": "UA-1-4 双源需 ua_shared_ua2_types_ds(18965)+empty_ds(18967); UA-1 runner 仅 18960 functional mock",
    "UA-1-4-02": "UA-1-4 双源需 ua_shared_ua2_types_ds(18965)+empty_ds(18967); UA-1 runner 仅 18960 functional mock",
    "UA-1-4-03": "UA-1-4 双源需 ua_shared_ua2_types_ds(18965)+empty_ds(18967); UA-1 runner 仅 18960 functional mock",
    "UA-1-4-04": "UA-1-4 双源需 ua_shared_ua2_types_ds(18965)+empty_ds(18967); UA-1 runner 仅 18960 functional mock",
    "UA-1-4-05": "UA-1-4 双源需 ua_shared_ua2_types_ds(18965)+empty_ds(18967); UA-1 runner 仅 18960 functional mock",
    "UA-1-4-06": "UA-1-4 双源需 ua_shared_ua2_types_ds(18965)+empty_ds(18967); UA-1 runner 仅 18960 functional mock",
}


def is_known_blocked(case_id: str) -> bool:
    return case_id in KNOWN_BLOCKED


def blocked_reason(case_id: str) -> str:
    return KNOWN_BLOCKED.get(case_id, "")
