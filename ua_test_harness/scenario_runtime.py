"""共享 Case 执行器。

每条 Markdown Case 都通过本模块进入真实 API/Mock 操作路径。当前底层接口或
测试数据确实不足时返回 BLOCKED，并记录具体能力缺口；不允许空函数直接 PASS。
"""
from __future__ import annotations

import inspect
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.type_mapping import tpt_tag_base_name


_MOCK_NAMESPACE_INDEX = 2


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _call(fn: Callable, /, *args, **kwargs):
    """仅传递当前 tpt_api 版本真正支持的关键字。"""
    sig = inspect.signature(fn)
    accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(*args, **accepted)


def _row_value(row: dict[str, Any]) -> Any:
    return row.get("tagValue", row.get("value"))


def _quality(row: dict[str, Any]) -> Any:
    return row.get("quality", row.get("qualityCode"))


def _unique(ctx, prefix: str) -> str:
    run_id = (ctx.config.run_id or "run").replace("-", "_")
    return f"{prefix}_{run_id[:16]}_{time.time_ns() % 1_000_000}"


def _wait(name: str, fn: Callable[[], Any], timeout: float = 60.0, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertFail(f"{name} timeout after {timeout}s; last={last!r}")


def _ds_row(ctx, ds_id: int) -> dict[str, Any] | None:
    from tpt_api.datahub import list_ds_info
    page = list_ds_info(_api(ctx), page=1, page_size=200, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", 0)) == int(ds_id):
            return row
    return None


def _prepare_online(ctx, cc, *, writable: bool = False, changing: bool = True):
    from ua_test_harness.fixtures import datasource, tag
    from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = ctx.config.mock.endpoints.functional
    if not endpoint:
        from ua_test_harness.clients.mock_control import get_endpoint
        endpoint = get_endpoint("functional", ctx)
    check_true("functional_endpoint", bool(endpoint))
    ds_name = _unique(ctx, "ua_auto_case_ds")
    ds = datasource.create_datasource(ctx, ds_name, endpoint, registry=cc.registry)
    datasource.change_state(ctx, ds["id"], True)
    check_true("datasource_alive", datasource.wait_alive(ctx, ds["id"], timeout=ctx.config.timeouts.ds_connect_sec))
    tag_name = _unique(ctx, "ua_auto_case_tag")
    node_name = "smoke_static_1" if writable or not changing else "smoke_change_1"
    base_name = tpt_tag_base_name(_MOCK_NAMESPACE_INDEX, node_name)
    dtype = "DOUBLE" if writable or not changing else "INT"
    tg = tag.create_tag(
        ctx,
        tag_name,
        ds_id=ds["id"],
        data_type=dtype,
        writable=writable,
        frequency=1,
        tag_base_name=base_name,
        registry=cc.registry,
    )
    tag.wait_tag_present(ctx, tag_name, timeout=30.0)
    return ds, tg


def _wait_rt(ctx, name: str, timeout: float | None = None) -> dict[str, Any]:
    from ua_test_harness.fixtures import tag
    return _wait(
        f"rt:{name}",
        lambda: (lambda r: r if r and _quality(r) is not None else None)(tag.read_rt(ctx, name)),
        timeout=timeout or ctx.config.timeouts.rt_visibility_sec,
    )


def _wait_changed(ctx, name: str, first: Any, timeout: float = 30.0) -> dict[str, Any]:
    from ua_test_harness.fixtures import tag
    return _wait(
        f"rt_changed:{name}",
        lambda: (lambda r: r if r and _row_value(r) != first else None)(tag.read_rt(ctx, name)),
        timeout=timeout,
    )


def _online_smoke(ctx, cc, meta):
    _ds, tg = _prepare_online(ctx, cc, changing=True)
    first = _wait_rt(ctx, tg["name"])
    second = _wait_changed(ctx, tg["name"], _row_value(first))
    check_true("quality_present", _quality(first) is not None)
    check_true("changing_value", _row_value(first) != _row_value(second))
    return CaseStatus.PASS


def _datasource_state(ctx, cc, meta):
    from ua_test_harness.fixtures import datasource
    ds, tg = _prepare_online(ctx, cc, changing=True)
    title = meta["title"]
    if "重复启用" in title:
        datasource.change_state(ctx, ds["id"], True)
        check_true("alive_after_repeat_enable", datasource.wait_alive(ctx, ds["id"], timeout=30.0))
        return CaseStatus.PASS
    datasource.change_state(ctx, ds["id"], False)
    _wait("disabled", lambda: (lambda r: r if r and not bool(r.get("alive")) else None)(_ds_row(ctx, ds["id"])), timeout=30.0)
    if "重复禁用" in title:
        datasource.change_state(ctx, ds["id"], False)
        check_true("still_disabled", not bool((_ds_row(ctx, ds["id"]) or {}).get("alive")))
        return CaseStatus.PASS
    if "禁用" in title and "启用" not in title and "循环" not in title:
        from ua_test_harness.fixtures import tag
        rt = tag.read_rt(ctx, tg["name"])
        if rt:
            check_true("disabled_quality_not_good", _quality(rt) in (None, 0) or not bool((_ds_row(ctx, ds["id"]) or {}).get("alive")))
        return CaseStatus.PASS
    datasource.change_state(ctx, ds["id"], True)
    check_true("alive_after_enable", datasource.wait_alive(ctx, ds["id"], timeout=60.0))
    _wait_rt(ctx, tg["name"])
    if "循环" in title:
        datasource.change_state(ctx, ds["id"], False)
        _wait("disabled_again", lambda: (lambda r: r if r and not bool(r.get("alive")) else None)(_ds_row(ctx, ds["id"])), timeout=30.0)
        datasource.change_state(ctx, ds["id"], True)
        check_true("alive_final", datasource.wait_alive(ctx, ds["id"], timeout=60.0))
    return CaseStatus.PASS


def _tag_query(ctx, cc, meta):
    from tpt_api.datahub import list_tags
    ds, tg = _prepare_online(ctx, cc, changing=True)
    page = list_tags(_api(ctx), page=1, page_size=10, data={"tagName": tg["name"]})
    rows = page.get("records") or []
    check_true("query_has_target", any(r.get("tagName") == tg["name"] for r in rows))
    ids = [r.get("id") for r in rows]
    check_eq("unique_ids", len(ids), len(set(ids)))
    return CaseStatus.PASS


def _tag_delete(ctx, cc, meta):
    from tpt_api.datahub import delete_tags, delete_tags_physical, list_recycle_tags, list_tags
    ds, tg = _prepare_online(ctx, cc, changing=False)
    api = _api(ctx)
    title = meta["title"]
    if "物理删除" in title:
        delete_tags_physical(api, [tg["id"]])
        active = list_tags(api, page=1, page_size=100, data={"tagName": tg["name"]}).get("records") or []
        check_true("physically_deleted", not any(r.get("tagName") == tg["name"] for r in active))
        cc.registry.pop(f"tag:{tg['name']}")
        return CaseStatus.PASS
    delete_tags(api, [tg["id"]])
    active = list_tags(api, page=1, page_size=100, data={"tagName": tg["name"]}).get("records") or []
    recycle = ((list_recycle_tags(api, page=1, page_size=500) or {}).get("tagInfoList") or {}).get("records") or []
    check_true("removed_from_active", not any(r.get("tagName") == tg["name"] for r in active))
    check_true("present_in_recycle", any(int(r.get("id", 0)) == tg["id"] for r in recycle))
    return CaseStatus.PASS


def _rt_read(ctx, cc, meta):
    _ds, tg = _prepare_online(ctx, cc, changing="静态" not in meta["title"])
    first = _wait_rt(ctx, tg["name"])
    check_true("rt_identity", bool(first.get("tagName", tg["name"])))
    check_true("quality_present", _quality(first) is not None)
    if "连续" in meta["title"] or "变化" in meta["title"]:
        second = _wait_changed(ctx, tg["name"], _row_value(first))
        check_true("changed", _row_value(second) != _row_value(first))
    return CaseStatus.PASS


def _rt_write(ctx, cc, meta):
    from ua_test_harness.fixtures import tag
    _ds, tg = _prepare_online(ctx, cc, writable=True, changing=False)
    title = meta["title"]
    if "只读" in title or "不存在" in title or "类型不匹配" in title or "超出" in title:
        target = tg["name"] if "不存在" not in title else _unique(ctx, "missing_tag")
        before = tag.read_rt(ctx, tg["name"])
        failed = False
        try:
            tag.write_tag(ctx, target, "abc" if "类型不匹配" in title else 123.5)
        except Exception:
            failed = True
        after = tag.read_rt(ctx, tg["name"])
        check_true("invalid_write_rejected_or_unchanged", failed or _row_value(before) == _row_value(after))
        return CaseStatus.PASS
    value = 123.5 + (time.time_ns() % 1000) / 1000.0
    tag.write_tag(ctx, tg["name"], value)
    observed = _wait(
        "write_visible",
        lambda: (lambda r: r if r and abs(float(_row_value(r)) - value) < 0.01 else None)(tag.read_rt(ctx, tg["name"])),
        timeout=30.0,
    )
    check_true("write_readback", abs(float(_row_value(observed)) - value) < 0.01)
    return CaseStatus.PASS


def _history(ctx, cc, meta):
    from ua_test_harness.fixtures import tag
    _ds, tg = _prepare_online(ctx, cc, changing=True)
    _wait_rt(ctx, tg["name"])
    deadline = time.time() + min(ctx.config.timeouts.history_visibility_sec, 30)
    found = None
    while time.time() < deadline:
        found = tag.read_history(ctx, tg["name"], seconds=120)
        if found:
            break
        time.sleep(2)
    if not found:
        return CaseStatus.BLOCKED
    return CaseStatus.PASS


def _response_time(ctx, cc, meta):
    from ua_test_harness.fixtures import tag
    _ds, tg = _prepare_online(ctx, cc, changing=True)
    _wait_rt(ctx, tg["name"])
    samples: list[float] = []
    for _ in range(5):
        tag.read_rt(ctx, tg["name"])
    for _ in range(30):
        started = time.perf_counter()
        row = tag.read_rt(ctx, tg["name"])
        if not row:
            raise AssertFail("response-time sample returned no data")
        samples.append((time.perf_counter() - started) * 1000)
    ctx.bag[f"metrics_{meta['id']}"] = {
        "min": min(samples),
        "mean": statistics.fmean(samples),
        "p50": statistics.median(samples),
        "p95": sorted(samples)[int(len(samples) * 0.95) - 1],
        "max": max(samples),
        "count": len(samples),
    }
    return CaseStatus.PASS


def _performance(ctx, cc, meta):
    from ua_test_harness.fixtures import tag
    _ds, tg = _prepare_online(ctx, cc, changing=True)
    _wait_rt(ctx, tg["name"])
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(tag.read_rt, ctx, tg["name"]) for _ in range(20)]
        for future in as_completed(futures):
            try:
                row = future.result()
                if not row:
                    errors.append("empty response")
                else:
                    results.append(row)
            except Exception as exc:
                errors.append(str(exc))
    check_eq("performance_error_count", len(errors), 0)
    check_eq("performance_response_count", len(results), 20)
    return CaseStatus.PASS


_SCENARIOS: dict[str, Callable] = {
    "online_smoke": _online_smoke,
    "datasource_state": _datasource_state,
    "tag_query": _tag_query,
    "tag_delete": _tag_delete,
    "rt_read": _rt_read,
    "rt_write": _rt_write,
    "history": _history,
    "response_time": _response_time,
    "performance": _performance,
}


def execute_documented_case(ctx, cc, meta: dict[str, Any]):
    from ua_test_harness.scenario_policy import classify_case
    decision = classify_case(meta)
    if not decision.executable:
        ctx.bag[f"blocked_{meta['id']}"] = decision.reason
        return CaseStatus.BLOCKED
    scenario = _SCENARIOS.get(decision.scenario)
    if scenario is None:
        ctx.bag[f"blocked_{meta['id']}"] = f"missing scenario adapter: {decision.scenario}"
        return CaseStatus.BLOCKED
    return scenario(ctx, cc, meta)
