"""fixtures/tag.py:位号 fixtures(创建 / 查询 / 软删 / 恢复 / 写值 / 读实时 / 读历史)。"""
from __future__ import annotations

from tpt_api.datahub import (
    add_tag,
    list_tags,
    delete_tags,
    get_tag_by_name,
    remove_tag_group_relation,
    get_rt_value,
    write_tag_values,
    get_history_value,
)
from tpt_api.types import DataTypes, TagTypes

from ua_test_harness.context import RunContext
from ua_test_harness.assertions import AssertFail


def create_tag(
    ctx: RunContext,
    name: str,
    ds_id: int,
    data_type: str = "DOUBLE",
    writable: bool = False,
    frequency: int = 10,
    group_id: str = "0",
    tag_base_name: str | None = None,
) -> dict:
    from tpt_api.datahub import delete_tags_physical, list_recycle_tags, list_tags
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    page = list_tags(api, page=1, page_size=500, data={"tagName": name})
    active_ids = [int(r["id"]) for r in page.get("records") or [] if r.get("tagName") == name]
    if active_ids:
        try:
            delete_tags_physical(api, active_ids)
        except Exception:
            pass
    rec = list_recycle_tags(api, page=1, page_size=500)
    records = ((rec or {}).get("tagInfoList") or {}).get("records") or []
    recycle_ids = [int(r["id"]) for r in records if r.get("tagName") == name]
    if recycle_ids:
        try:
            delete_tags_physical(api, recycle_ids)
        except Exception:
            pass

    data = add_tag(
        api,
        tag_name=name,
        data_type=DataTypes[data_type],
        tag_type=TagTypes["一次位号"],
        ds_id=ds_id,
        group_id=group_id,
        unit="",
        only_read=not writable,
        frequency=frequency,
        need_push=True,
        tag_desc=f"{name} 描述",
        is_vector=True,
        tag_base_name=tag_base_name or f"1_{name}",
    )
    tag_id = data.get("id") or data.get("tagId")

    def cleanup() -> None:
        try:
            if tag_id:
                delete_tags_physical(api, [int(tag_id)])
        except Exception as e:
            raise RuntimeError(f"delete tag {name} failed: {e}")

    ctx.registry.register(f"tag:{name}", "tag", cleanup)
    return {"id": int(tag_id) if tag_id else 0, "name": name}


def find_tag(ctx: RunContext, name: str) -> dict | None:
    from tpt_api.datahub import list_tags
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    page = list_tags(api, page=1, page_size=500, data={"tagName": name})
    for r in page.get("records") or []:
        if r.get("tagName") == name:
            return r
    return None


def wait_tag_present(ctx: RunContext, name: str, timeout: float = 30.0) -> dict:
    from ua_test_harness.polling import wait_until

    found: dict = {}

    def fetch() -> bool:
        tag = find_tag(ctx, name)
        if not tag:
            return False
        found["v"] = tag
        return True

    wait_until(
        f"tag_present:{name}",
        fetch,
        timeout=timeout,
        interval=1.0,
    )
    return found.get("v") or find_tag(ctx, name) or {}


def soft_delete_tag(ctx: RunContext, name: str) -> None:
    from tpt_api.datahub import delete_tags, list_tags
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    page = list_tags(api, page=1, page_size=500, data={"tagName": name})
    ids = [int(r["id"]) for r in page.get("records") or [] if r.get("tagName") == name]
    if ids:
        delete_tags(api, ids)


def restore_from_recycle(ctx: RunContext, name: str) -> None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    from tpt_api.datahub import list_recycle_tags

    data = list_recycle_tags(api, page=1, page_size=500)
    records = ((data or {}).get("tagInfoList") or {}).get("records") or []
    ids = [int(r["id"]) for r in records if r.get("tagName") == name]
    if ids:
        remove_tag_group_relation(api, group_id="1", tag_ids=ids)


def write_tag(ctx: RunContext, name: str, value) -> None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    write_tag_values(api, {name: value})


def read_rt(ctx: RunContext, name: str, from_db: bool = False) -> dict:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    data = get_rt_value(api, [name], is_from_db=from_db)
    if isinstance(data, list):
        for p in data:
            if p.get("tagName") == name:
                return p
        return {}
    if isinstance(data, dict):
        return data
    return {}


def read_history(ctx: RunContext, name: str, begin_ms: int, end_ms: int) -> list:
    from datetime import datetime, timezone
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    beg_str = datetime.fromtimestamp(begin_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_str = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    raw = get_history_value(api, tag_names=[name], beg_time=beg_str, end_time=end_str, page=1, page_size=1000)
    if isinstance(raw, dict):
        entry = raw.get(name) or {}
        if isinstance(entry, dict):
            return entry.get("list") or []
        return []
    if isinstance(raw, list):
        return raw
    return (raw or {}).get("records") or []
