"""tests/ua_2:位号管理用例(新增 / 查询 / 软删+恢复 / 分组)。"""
from __future__ import annotations

from ua_test_harness.catalog import case
from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures import datasource, tag
from ua_test_harness.fixtures.environment import ensure_mock_ready, ensure_logged_in
from ua_test_harness.clients import mock_control
from ua_test_harness.models import StepDef


DS_NAME = "ua_auto_ua2"


@case(
    id="UA-2-1-001",
    title="位号新增闭环",
    chapter="UA-2-1",
    kind="regression",
    tags=["tag", "ua-2"],
    timeout_sec=180,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增 Double 位号"),
        StepDef(step_id="query-tag", title="查询位号存在"),
    ],
    assertions=["add_tag 返回 id;tag_page 能查到该 name"],
)
def ua_2_1_001_tag_create(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_001", endpoint)
    ds_id = ds["id"]
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds_id, timeout=90.0)
    name = "ua2_1_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    res = tag.create_tag(ctx, name, ds_id=ds_id, data_type="DOUBLE", writable=True, frequency=5)
    check_true("tag_id_present", bool(res.get("id")))
    found = tag.find_tag(ctx, name)
    check_true("tag_found_in_page", bool(found))


@case(
    id="UA-2-2-001",
    title="位号查询",
    chapter="UA-2-2",
    kind="regression",
    tags=["tag", "query", "ua-2"],
    timeout_sec=120,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增位号"),
        StepDef(step_id="query-by-name", title="按名称查"),
    ],
    assertions=["按名称 page 能查到"],
)
def ua_2_2_001_tag_query(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_002", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua2_2_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="INT", writable=False, frequency=10)
    found = tag.find_tag(ctx, name)
    check_true("tag_found", bool(found))


@case(
    id="UA-2-4-001",
    title="位号软删除与恢复",
    chapter="UA-2-4",
    kind="regression",
    tags=["tag", "recycle", "ua-2"],
    timeout_sec=180,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增位号"),
        StepDef(step_id="soft-delete", title="软删除"),
        StepDef(step_id="recycle-contains", title="断言在回收站"),
        StepDef(step_id="restore", title="恢复"),
        StepDef(step_id="active-contains", title="断言可重新查得"),
    ],
    assertions=["软删后回收站可查;恢复后正常 query 命中"],
)
def ua_2_4_001_tag_soft_delete_restore(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_004", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua2_4_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="DOUBLE", writable=True, frequency=5)

    # 软删除后,删除登记的 cleanup 不再需要(因为我们要测回收 + 恢复)
    ctx.registry.pop(f"tag:{name}")
    tag.soft_delete_tag(ctx, name)

    from ua_test_harness.polling import wait_until

    wait_until(f"tag_in_recycle:{name}", lambda: bool(_query_recycle(ctx, name)), timeout=30.0, interval=1.0)
    tag.restore_from_recycle(ctx, name)
    wait_until(f"tag_active:{name}", lambda: bool(tag.find_tag(ctx, name)), timeout=30.0, interval=1.0)

    def cleanup_active() -> None:
        from ua_test_harness.clients.tpt_client import get_api

        try:
            get_api(ctx).post(
                "ibd-data-hub-web-v2.2/api/tag-info/batchDelete",
                {"tagNames": [name]},
            )
        except Exception:
            pass

    ctx.registry.register(f"tag:{name}", "tag", cleanup_active)


def _query_recycle(ctx, name: str) -> dict | None:
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    r = api.post("ibd-data-hub-web-v2.2/api/tag-group/get", {"groupId": "1"})
    if r.get("code") != "00000":
        return None
    rows = (r.get("data") or {}).get("records") or []
    for row in rows:
        if row.get("tagName") == name:
            return row
    return None