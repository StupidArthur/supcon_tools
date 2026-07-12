"""tests/ua_1/__init__.py:UA-1 数据源连接/启停/恢复 用例。

覆盖(plan.md 11):
- UA-1-1-001:基础数据源连接建立
- UA-1-2-001:启停
- UA-1-3-001:断线恢复
"""
from __future__ import annotations

from ua_test_harness.catalog import case
from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures import datasource, environment
from ua_test_harness.fixtures.environment import ensure_mock_ready, ensure_logged_in
from ua_test_harness.clients import mock_control
from ua_test_harness.metrics import report_text
from ua_test_harness.models import StepDef


DS_NAME = "ua_auto_ua1"


def _check_alive_after_enable(ctx, ds_id: int, timeout: float = 60.0) -> bool:
    """启用数据源后轮询 alive=True。"""
    datasource.change_state(ctx, ds_id, True)
    return datasource.wait_alive(ctx, ds_id, timeout=timeout)


@case(
    id="UA-1-1-001",
    title="基础数据源连接建立",
    chapter="UA-1-1",
    kind="regression",
    tags=["datasource", "ua-1"],
    timeout_sec=120,
    steps=[
        StepDef(step_id="ensure-mock", title="确保 functional mock ready"),
        StepDef(step_id="ensure-login", title="登录 TPT"),
        StepDef(step_id="add-ds", title="创建数据源"),
        StepDef(step_id="enable-ds", title="启用并等待 alive"),
        StepDef(step_id="check-alive", title="断言 alive=true"),
    ],
    assertions=["数据源添加成功后 enable,alive=true"],
)
def ua_1_1_001_basic_datasource_connection(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_001", endpoint)
    ds_id = ds["id"]
    ok = _check_alive_after_enable(ctx, ds_id, timeout=90.0)
    check_true("ds_alive", ok, "数据源应 alive=True")
    report_text(ctx.emitter, "UA-1-1-001", "ds_id", str(ds_id))


@case(
    id="UA-1-2-001",
    title="数据源启用与禁用",
    chapter="UA-1-2",
    kind="regression",
    tags=["datasource", "ua-1"],
    timeout_sec=180,
    steps=[
        StepDef(step_id="ensure-mock", title="确保 mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="disable", title="禁用"),
        StepDef(step_id="check-offline", title="断言 alive=false"),
        StepDef(step_id="enable", title="重新启用"),
        StepDef(step_id="check-online", title="断言 alive=true"),
    ],
    assertions=["disable 后 alive=false,enable 后 alive=true"],
)
def ua_1_2_001_datasource_enable_disable(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_002", endpoint)
    ds_id = ds["id"]
    _check_alive_after_enable(ctx, ds_id, timeout=90.0)
    datasource.change_state(ctx, ds_id, False)
    # 轮询 alive=false
    from tpt_api.datahub import list_ds_info
    from ua_test_harness.polling import wait_until

    def fetch_alive() -> bool:
        page = list_ds_info(ctx.bag["tpt_api"], page=1, page_size=200, data={"id": ds_id})
        rows = page.get("records") or []
        return bool(rows) and bool(rows[0].get("alive"))

    wait_until(f"ds_offline:{ds_id}", lambda: not fetch_alive(), timeout=60.0, interval=1.0)
    ok = _check_alive_after_enable(ctx, ds_id, timeout=90.0)
    check_true("ds_alive_after_re_enable", ok)


@case(
    id="UA-1-3-001",
    title="数据源断线与恢复",
    chapter="UA-1-3",
    kind="regression",
    tags=["datasource", "reconnect", "ua-1"],
    timeout_sec=240,
    steps=[
        StepDef(step_id="ensure-mock", title="确保 mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="check-online", title="断言 alive=true"),
        StepDef(step_id="stop-mock", title="停 mock"),
        StepDef(step_id="check-offline", title="断言 alive=false"),
        StepDef(step_id="start-mock", title="重启 mock"),
        StepDef(step_id="check-online-again", title="断言 alive=true 自动恢复"),
    ],
    assertions=["停 mock 后 alive=false,重启后自动恢复 alive=true"],
)
def ua_1_3_001_datasource_disconnect_recover(ctx, cc):
    ensure_mock_ready(ctx, "reconnect")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("reconnect", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_003", endpoint)
    ds_id = ds["id"]
    _check_alive_after_enable(ctx, ds_id, timeout=90.0)
    mock_control.stop_mock("reconnect")
    from tpt_api.datahub import list_ds_info
    from ua_test_harness.polling import wait_until

    def fetch_alive() -> bool:
        page = list_ds_info(ctx.bag["tpt_api"], page=1, page_size=200, data={"id": ds_id})
        rows = page.get("records") or []
        return bool(rows) and bool(rows[0].get("alive"))

    wait_until(f"ds_offline_after_mock_stop:{ds_id}", lambda: not fetch_alive(), timeout=60.0, interval=1.0)
    mock_control.start_mock("reconnect")
    mock_control.wait_ready("reconnect", timeout=120.0, ctx=ctx)
    ok = _check_alive_after_enable(ctx, ds_id, timeout=120.0)
    check_true("ds_alive_after_mock_restart", ok)