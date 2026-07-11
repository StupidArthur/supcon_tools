"""fixtures/datasource.py:数据源 fixtures(创建 / 查询 / 启停 / 删除)。

封装创建到清理的 LIFO 流程,与 ResourceRegistry 协作。
"""
from __future__ import annotations

from typing import Callable

from tpt_api.datahub import (
    DataHubBasePath,
    DataHubDsInfoAdd,
    DataHubDsInfoChangeState,
    DataHubDsInfoPage,
    DataHubDsInfoBatchDelete,
)
from tpt_api.errors import SuccessCode
from tpt_api.types import DataTypes, DsSubTypes, DsTypes

from ua_test_harness.context import RunContext
from ua_test_harness.assertions import AssertFail


def _post(api, endpoint: str, payload: dict) -> dict:
    r = api.post(endpoint, payload)
    if r.get("code") != SuccessCode:
        raise AssertFail(f"POST {endpoint} -> {r}")
    return r.get("data") or {}


def find_ds_by_name(api, name: str) -> dict | None:
    page = _post(api, DataHubDsInfoPage, {"pageNum": 1, "pageSize": 200, "name": name})
    rows = (page or {}).get("records") or []
    for row in rows:
        if row.get("name") == name or row.get("dsName") == name:
            return row
    return None


def create_datasource(ctx: RunContext, name: str, endpoint: str, sub_type: str = "opc_ua_server") -> dict:
    """创建数据源,登记清理动作。"""
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    payload = {
        "name": name,
        "dsType": DsTypes["实时数据库"],
        "dsSubType": DsSubTypes[sub_type],
        "dsTarUrl": endpoint,
        "dsStatus": 1,
    }
    data = _post(api, DataHubDsInfoAdd, payload)
    ds_id = data.get("id") or data.get("dsId")
    if not ds_id:
        raise AssertFail(f"create datasource {name} no id returned: {data}")

    def cleanup() -> None:
        try:
            api.post(DataHubDsInfoBatchDelete, {"ids": [int(ds_id)]})
        except Exception as e:
            raise RuntimeError(f"delete ds {ds_id} failed: {e}")

    ctx.registry.register(f"ds:{name}", "datasource", cleanup)
    return {"id": int(ds_id), "name": name}


def change_state(ctx: RunContext, ds_id: int, enabled: bool) -> None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    _post(api, DataHubDsInfoChangeState, {"id": ds_id, "dsStatus": 1 if enabled else 0})


def wait_alive(ctx: RunContext, ds_id: int, timeout: float = 60.0) -> bool:
    """轮询 ds 是否 alive=True。"""
    from ua_test_harness.clients.tpt_client import get_api
    from ua_test_harness.polling import wait_until

    api = get_api(ctx)

    def fetch():
        rows = _post(api, DataHubDsInfoPage, {"pageNum": 1, "pageSize": 200, "id": ds_id}).get("records") or []
        return bool(rows) and bool(rows[0].get("alive"))

    try:
        wait_until(f"ds_alive:{ds_id}", fetch, timeout=timeout, interval=1.0)
        return True
    except Exception:
        return False