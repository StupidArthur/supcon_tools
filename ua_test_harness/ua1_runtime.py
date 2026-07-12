"""UA-1 数据源管理专用执行器。"""
from __future__ import annotations

import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.type_mapping import tpt_tag_base_name


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _unique(ctx, prefix: str) -> str:
    run_id = (ctx.config.run_id or "run").replace("-", "_")
    return f"{prefix}_{run_id[:14]}_{time.time_ns() % 1_000_000}"


def _endpoint(ctx) -> str:
    from ua_test_harness.clients.tpt_client import endpoint_for
    value = ctx.config.mock.endpoints.functional or endpoint_for("functional", ctx)
    if not value:
        raise AssertFail("functional mock endpoint is empty")
    return value


def _wait(name: str, fn, timeout: float = 60.0, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertFail(f"{name} timeout after {timeout}s; last={last!r}")


def _row(ctx, ds_id: int) -> dict[str, Any] | None:
    from ua_test_harness.fixtures.datasource import get_state
    return get_state(ctx, ds_id)


def _prepare(ctx, cc, *, endpoint: str | None = None, with_tag: bool = True, enabled: bool = True):
    from ua_test_harness.fixtures import datasource, tag
    from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ep = endpoint or _endpoint(ctx)
    ds_name = _unique(ctx, "ua_auto_ua1_ds")
    ds = datasource.create_datasource(ctx, ds_name, ep, registry=cc.registry)
    if enabled:
        datasource.change_state(ctx, ds["id"], True)
        check_true("datasource_alive", datasource.wait_alive(ctx, ds["id"], timeout=ctx.config.timeouts.ds_connect_sec))
    tg = None
    if with_tag:
        tag_name = _unique(ctx, "ua_auto_ua1_tag")
        tg = tag.create_tag(
            ctx,
            tag_name,
            ds_id=ds["id"],
            data_type="INT",
            writable=False,
            frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_change_1"),
            registry=cc.registry,
        )
        tag.wait_tag_present(ctx, tag_name, timeout=30.0)
    return ds, tg


def _wait_rt(ctx, tag_name: str):
    from ua_test_harness.fixtures.tag import read_rt
    return _wait(
        f"rt:{tag_name}",
        lambda: (lambda row: row if row and row.get("quality") is not None else None)(read_rt(ctx, tag_name)),
        timeout=ctx.config.timeouts.rt_visibility_sec,
    )


def _connection(ctx, cc, meta):
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes, DsTypes
    from ua_test_harness.fixtures import datasource

    case_id = meta["id"]
    if case_id == "UA-1-1-04":
        host = ctx.config.local_ip or "127.0.0.1"
        unreachable = f"opc.tcp://{host}:18969/ua_mocker/"
        ds, _ = _prepare(ctx, cc, endpoint=unreachable, with_tag=False, enabled=False)
        datasource.change_state(ctx, ds["id"], True)
        time.sleep(3)
        check_true("unreachable_not_alive", not bool((_row(ctx, ds["id"]) or {}).get("alive")))
        return CaseStatus.PASS

    if case_id == "UA-1-1-12":
        ds, _ = _prepare(ctx, cc, with_tag=False)
        duplicate_failed = False
        try:
            add_ds_info(
                _api(ctx),
                ds_name=_unique(ctx, "ua_auto_ua1_dup"),
                ds_type=DsTypes["REAL_TIME_DB"],
                ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
                ds_tar_url=ds["endpoint"],
            )
        except Exception:
            duplicate_failed = True
        check_true("duplicate_endpoint_rejected", duplicate_failed)
        return CaseStatus.PASS

    endpoint = _endpoint(ctx)
    if case_id == "UA-1-1-01":
        endpoint = endpoint.split("/ua_mocker/", 1)[0]
    ds, tg = _prepare(ctx, cc, endpoint=endpoint, with_tag=True)
    check_true("alive", bool((_row(ctx, ds["id"]) or {}).get("alive")))
    first = _wait_rt(ctx, tg["name"])
    check_true("rt_has_value", first.get("tagValue", first.get("value")) is not None)
    return CaseStatus.PASS


def _delete(ctx, cc, meta):
    from tpt_api.datahub import delete_ds_info
    from ua_test_harness.fixtures import datasource

    case_id = meta["id"]
    with_tag = case_id not in {"UA-1-5-01", "UA-1-5-03"}
    enabled = case_id != "UA-1-5-01"
    ds, tg = _prepare(ctx, cc, with_tag=with_tag, enabled=enabled)

    if case_id == "UA-1-5-07":
        endpoint = ds["endpoint"]
        if tg:
            cc.registry.pop(f"tag:{tg['name']}")
            from tpt_api.datahub import delete_tags_physical
            delete_tags_physical(_api(ctx), [tg["id"]])
        datasource.change_state(ctx, ds["id"], False)
        delete_ds_info(_api(ctx), [ds["id"]])
        cc.registry.pop(f"ds:{ds['name']}")
        rebuilt, rebuilt_tag = _prepare(ctx, cc, endpoint=endpoint, with_tag=True, enabled=True)
        check_true("rebuilt_alive", bool((_row(ctx, rebuilt["id"]) or {}).get("alive")))
        _wait_rt(ctx, rebuilt_tag["name"])
        return CaseStatus.PASS

    if enabled:
        try:
            datasource.change_state(ctx, ds["id"], False)
        except Exception:
            pass
    if tg:
        cc.registry.pop(f"tag:{tg['name']}")
        from tpt_api.datahub import delete_tags_physical
        delete_tags_physical(_api(ctx), [tg["id"]])
    delete_ds_info(_api(ctx), [ds["id"]])
    cc.registry.pop(f"ds:{ds['name']}")
    check_true("datasource_deleted", _row(ctx, ds["id"]) is None)
    return CaseStatus.PASS


def execute_ua1_case(ctx, cc, meta):
    chapter = meta["chapter"]
    if chapter == "UA-1-1":
        return _connection(ctx, cc, meta)
    if chapter == "UA-1-2":
        from ua_test_harness.scenario_runtime import execute_documented_case
        return execute_documented_case(ctx, cc, meta)
    if chapter == "UA-1-5":
        return _delete(ctx, cc, meta)
    raise AssertFail(f"UA-1 runtime has no adapter for {meta['id']}")
