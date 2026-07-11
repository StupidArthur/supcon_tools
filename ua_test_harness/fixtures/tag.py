"""fixtures/tag.py:位号 fixtures(创建 / 查询 / 软删 / 恢复 / 写值 / 读实时 / 读历史)。"""
from __future__ import annotations

from tpt_api.datahub import (
    DataHubTagAdd,
    DataHubTagPage,
    DataHubTagBatchDeleteLogic,
    DataHubTagGroupBatchDelRelation,
    DataHubGetRTValue,
    DataHubWriteTagValues,
    DataHubGetHistoryValue,
)
from tpt_api.errors import SuccessCode
from tpt_api.types import DataTypes, TagTypes

from ua_test_harness.context import RunContext
from ua_test_harness.assertions import AssertFail
from .datasource import _post


def _post_rt(api, endpoint: str, payload: dict) -> dict:
    r = api.post(endpoint, payload)
    if r.get("code") != SuccessCode:
        raise AssertFail(f"POST {endpoint} -> {r}")
    return r.get("data") or {}


def create_tag(
    ctx: RunContext,
    name: str,
    ds_id: int,
    data_type: str = "DOUBLE",
    writable: bool = False,
    frequency: int = 10,
    group_id: str = "0",
) -> dict:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    payload = {
        "tagName": name,
        "dataType": DataTypes[data_type],
        "tagType": TagTypes["一次位号"],
        "dsId": ds_id,
        "groupId": group_id,
        "onlyRead": not writable,
        "frequency": frequency,
        "needPush": True,
        "isVector": True,
        "tagBaseName": f"1_{name}",
        "tagDesc": f"{name} 描述",
    }
    data = _post(api, DataHubTagAdd, payload)
    tag_id = data.get("id") or data.get("tagId")

    def cleanup() -> None:
        try:
            api.post(DataHubTagBatchDeleteLogic, {"ids": [int(tag_id)] if tag_id else [], "tagNames": [name]})
        except Exception as e:
            raise RuntimeError(f"delete tag {name} failed: {e}")

    ctx.registry.register(f"tag:{name}", "tag", cleanup)
    return {"id": int(tag_id) if tag_id else 0, "name": name}


def find_tag(ctx: RunContext, name: str) -> dict | None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    rows = _post(api, DataHubTagPage, {"pageNum": 1, "pageSize": 200, "tagName": name}).get("records") or []
    for r in rows:
        if r.get("tagName") == name:
            return r
    return None


def wait_tag_present(ctx: RunContext, name: str, timeout: float = 30.0) -> dict:
    from ua_test_harness.polling import wait_until

    found: dict = {}
    wait_until(
        f"tag_present:{name}",
        lambda: (found.__setitem__("v", find_tag(ctx, name)) or bool(found.get("v"))) and False,
        timeout=timeout,
        interval=1.0,
    )
    return found.get("v") or find_tag(ctx, name) or {}


def soft_delete_tag(ctx: RunContext, name: str) -> None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    _post(api, DataHubTagBatchDeleteLogic, {"tagNames": [name]})


def restore_from_recycle(ctx: RunContext, name: str) -> None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    # 恢复 = 从回收站(1)分组移除关联
    _post(api, DataHubTagGroupBatchDelRelation, {"groupId": "1", "tagNames": [name]})


def write_tag(ctx: RunContext, name: str, value) -> None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    _post_rt(api, DataHubWriteTagValues, {"items": [{"tagName": name, "tagValue": value}]})


def read_rt(ctx: RunContext, name: str, from_db: bool = False) -> dict:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    data = _post_rt(api, DataHubGetRTValue, {"tagNames": [name], "isFromDB": from_db})
    pts = data if isinstance(data, list) else (data.get("records") or [])
    for p in pts:
        if p.get("tagName") == name:
            return p
    return {}


def read_history(ctx: RunContext, name: str, begin_ms: int, end_ms: int) -> list:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    data = _post_rt(api, DataHubGetHistoryValue, {
        "tagNames": [name], "beginTime": begin_ms, "endTime": end_ms, "pageNum": 1, "pageSize": 1000,
    })
    if isinstance(data, list):
        return data
    return (data or {}).get("records") or []