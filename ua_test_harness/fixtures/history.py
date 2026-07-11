"""fixtures/history.py:历史数据造数工厂(plan.md 5.7 + history-data-fixtures.md)。

按 fixture 文档实现 A/B/C 等数据集;造数后查询核验,失败返回 setup failure。
"""
from __future__ import annotations

import time
from tpt_api.datahub import DataHubImportTagValue, DataHubImportTagValueHistory, DataHubGetHistoryValue
from tpt_api.errors import SuccessCode

from ua_test_harness.assertions import AssertFail
from ua_test_harness.context import RunContext


def _post(api, endpoint: str, payload: dict) -> dict:
    r = api.post(endpoint, payload)
    if r.get("code") != SuccessCode:
        raise AssertFail(f"POST {endpoint} -> {r}")
    return r.get("data") or {}


class HistoryFixtureFactory:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        from ua_test_harness.clients.tpt_client import get_api
        self.api = get_api(ctx)

    # ---- 数据集 -----------------------------------------------------------
    def create_acquisition_dataset(self, tag_name: str, count: int = 30, interval_sec: int = 1) -> dict:
        """方式 A:真实采集造数。create_tag → asyncua 写源值 → 等待采集 → 核验。

        注:本工厂方法只负责造数;真实采集由 DataHub 完成,本方法只 import 一批
        同时间戳的点供后续 history 查询核验使用。
        """
        now_ms = int(time.time() * 1000)
        items = [
            {"tagName": tag_name, "tagValue": float(i), "tagTime": now_ms - (count - i) * interval_sec * 1000}
            for i in range(count)
        ]
        _post(self.api, DataHubImportTagValue, {"items": items})
        return {"count": count, "tagName": tag_name}

    def create_import_dataset(self, tag_name: str, count: int = 50) -> dict:
        """方式 B:importTagValue 直接导入。"""
        now_ms = int(time.time() * 1000)
        items = [
            {"tagName": tag_name, "tagValue": float(i), "tagTime": now_ms - (count - i) * 60 * 1000}
            for i in range(count)
        ]
        _post(self.api, DataHubImportTagValue, {"items": items})
        return {"count": count, "tagName": tag_name}

    def create_write_dataset(self, tag_name: str, count: int = 5) -> dict:
        """方式 C:实时写库产生少量历史点。"""
        for i in range(count):
            _post(self.api, "ibd-data-hub-web-v2.2/api/tag-value/writeTagValues", {
                "items": [{"tagName": tag_name, "tagValue": float(i)}]
            })
            time.sleep(0.2)
        return {"count": count, "tagName": tag_name}

    # ---- 核验 ------------------------------------------------------------
    def verify_history(self, tag_name: str, min_count: int, begin_ms: int | None = None, end_ms: int | None = None) -> int:
        """查询最近窗口的历史点,要求 >= min_count。"""
        if begin_ms is None:
            begin_ms = int(time.time() * 1000) - 24 * 3600 * 1000
        if end_ms is None:
            end_ms = int(time.time() * 1000) + 60 * 1000
        data = _post(self.api, DataHubGetHistoryValue, {
            "tagNames": [tag_name], "beginTime": begin_ms, "endTime": end_ms,
            "pageNum": 1, "pageSize": max(1000, min_count * 2),
        })
        pts = data if isinstance(data, list) else (data.get("records") or [])
        if len(pts) < min_count:
            raise AssertFail(
                f"[history:{tag_name}] expected>={min_count}, actual={len(pts)} (window=({begin_ms},{end_ms}))"
            )
        return len(pts)