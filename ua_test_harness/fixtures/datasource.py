"""fixtures/datasource.py:数据源 fixtures(创建 / 查询 / 启停 / 删除)。

封装创建到清理的 LIFO 流程,与 ResourceRegistry 协作。
"""
from __future__ import annotations

from typing import Callable

from tpt_api.datahub import (
    add_ds_info,
    change_ds_state,
    list_ds_info,
    delete_ds_info,
)
from tpt_api.types import DsSubTypes, DsTypes

from ua_test_harness.context import RunContext
from ua_test_harness.assertions import AssertFail


def find_ds_by_name(api, name: str) -> dict | None:
    page = list_ds_info(api, page=1, page_size=200, data={"dsName": name})
    rows = page.get("records") or []
    for row in rows:
        if row.get("name") == name or row.get("dsName") == name:
            return row
    return None


def create_datasource(ctx: RunContext, name: str, endpoint: str, sub_type: str = "OPC_UA_SERVER") -> dict:
    """创建数据源,登记清理动作。已存在同 endpoint 的则复用。"""
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    # 1. 优先按 endpoint 复用,2. 再按 name 复用
    page = list_ds_info(api, page=1, page_size=200, data={"dsTarUrl": endpoint})
    for row in page.get("records") or []:
        if row.get("dsTarUrl") == endpoint:
            ds_id = int(row["id"])
            ctx.registry.register(f"ds:{name}", "datasource", lambda: _safe_delete(api, ds_id))
            return {"id": ds_id, "name": name, "reused": True}
    page2 = list_ds_info(api, page=1, page_size=200, data={"dsName": name})
    for row in page2.get("records") or []:
        if row.get("dsName") == name or row.get("name") == name:
            ds_id = int(row["id"])
            ctx.registry.register(f"ds:{name}", "datasource", lambda: _safe_delete(api, ds_id))
            return {"id": ds_id, "name": name, "reused": True}

    data = add_ds_info(
        api,
        ds_name=name,
        ds_type=DsTypes["REAL_TIME_DB"],
        ds_sub_type=DsSubTypes[sub_type],
        ds_tar_url=endpoint,
    )
    ds_id = data.get("id") or data.get("dsId")
    if not ds_id:
        raise AssertFail(f"create datasource {name} no id returned: {data}")

    def cleanup() -> None:
        _safe_delete(api, int(ds_id))

    ctx.registry.register(f"ds:{name}", "datasource", cleanup)
    return {"id": int(ds_id), "name": name}


def _safe_delete(api, ds_id: int) -> None:
    try:
        delete_ds_info(api, [ds_id])
    except Exception as e:
        raise RuntimeError(f"delete ds {ds_id} failed: {e}")


def change_state(ctx: RunContext, ds_id: int, enabled: bool) -> None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    change_ds_state(api, ds_id, enabled)


def wait_alive(ctx: RunContext, ds_id: int, timeout: float = 60.0) -> bool:
    """轮询 ds 是否 alive=True。"""
    from ua_test_harness.clients.tpt_client import get_api
    from ua_test_harness.polling import wait_until

    api = get_api(ctx)

    def fetch():
        page = list_ds_info(api, page=1, page_size=200, data={"id": ds_id})
        rows = page.get("records") or []
        return bool(rows) and bool(rows[0].get("alive"))

    try:
        wait_until(f"ds_alive:{ds_id}", fetch, timeout=timeout, interval=1.0)
        return True
    except Exception:
        return False