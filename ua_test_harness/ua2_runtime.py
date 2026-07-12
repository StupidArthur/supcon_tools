"""UA-2 精确执行器派发。

建立 caseId -> handler 映射。未在表里的 ID 不进入 default 冒烟,直接抛配置错误。
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from ua_test_harness.assertions import AssertFail
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import BaselineError

from ua_test_harness import ua2_create_runtime, ua2_query_runtime, ua2_recycle_runtime


_EXECUTE_UA2: dict[str, Callable] = {
    "UA-2-1-017": ua2_create_runtime.duplicate_name_rejected,
    "UA-2-1-019": ua2_create_runtime.empty_name_rejected,
    "UA-2-1-021": ua2_create_runtime.name_length_127,
    "UA-2-1-022": ua2_create_runtime.name_length_128,
    "UA-2-2-004": ua2_query_runtime.query_config_fields,
    "UA-2-2-005": ua2_query_runtime.query_repeat_stable,
    "UA-2-2-008": ua2_query_runtime.query_missing_name,
    "UA-2-2-011": ua2_query_runtime.query_clear_name_filter,
    "UA-2-2-015": ua2_query_runtime.query_base_name_exact,
    "UA-2-2-016": ua2_query_runtime.query_missing_base_name,
    "UA-2-2-019": ua2_query_runtime.query_empty_datasource,
    "UA-2-2-033": ua2_query_runtime.query_config_fields,
    "UA-2-4-001": ua2_recycle_runtime.soft_delete_one,
    "UA-2-4-013": ua2_recycle_runtime.restore_one,
    "UA-2-4-020": ua2_recycle_runtime.physical_delete_one,
    "UA-2-4-024": ua2_recycle_runtime.physical_delete_irreversible,
}


def supported_ua2_ids() -> list[str]:
    return sorted(_EXECUTE_UA2.keys())


def is_supported_ua2(case_id: str) -> bool:
    return case_id in _EXECUTE_UA2


def execute_ua2_case(ctx, cc, meta) -> CaseStatus:
    case_id = meta["id"]
    handler = _EXECUTE_UA2.get(case_id)
    if handler is None:
        raise AssertFail(
            f"UA-2 precise runtime has no adapter for {case_id}; "
            "this case must remain BLOCKED until queryWithQuality / asyncua / batch / "
            "import-export / group adapter is added."
        )
    sig = inspect.signature(handler)
    kwargs: dict[str, Any] = {}
    accepted = ("ctx", "cc", "meta")
    for i, name in enumerate(sig.parameters):
        if name in accepted:
            kwargs[name] = {"ctx": ctx, "cc": cc, "meta": meta}[name]
    try:
        return handler(**kwargs)
    except BaselineError:
        # 共享数据源 / 环境前置不可用(共享 DS 缺失、配置不匹配、未 alive、
        # empty DS 非空等)不是框架 ERROR,而是 BLOCKED 前置条件。显式映射,
        # 让 runner 记 BLOCKED 而非 ERROR;产品断言失败(AssertFail)仍正常
        # 向上抛出归为 FAIL。
        return CaseStatus.BLOCKED
