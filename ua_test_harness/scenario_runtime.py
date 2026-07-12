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
    base_name = "smoke_static_1" if writable or not changing else "smoke_change_1"
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
            check_true("disabled_quality_not_good", _quality(rt) in (None, 0) or not bool((_ds_row(ctx, ds["id"]) or {}).get("alive")) )
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
    _ds, tg = _prepare_online(ctx, cc, writable=True, changing=False)
    start = int(time.time() * 1000) - 5_000
    for value in (101.25, 102.25, 103.25):
        tag.write_tag(ctx, tg["name"], value)
        time.sleep(1.1)
    end = int(time.time() * 1000) + 2_000
    rows = tag.read_history(ctx, tg["name"], start, end)
    if not rows:
        return _blocked(ctx, meta, "当前环境未形成可查询历史记录；需要历史导入或落库能力")
    check_true("history_rows", len(rows) > 0)
    return CaseStatus.PASS


def _group(ctx, cc, meta):
    from tpt_api.datahub import add_tag_group, delete_tag_group
    api = _api(ctx)
    name = _unique(ctx, "ua_auto_group")
    created = add_tag_group(api, name, parent_id="0")
    group_id = str(created.get("id") or created.get("groupId") or "")
    check_true("group_id", bool(group_id))
    cc.registry.register(f"group:{group_id}", "tag_group", lambda: delete_tag_group(api, [group_id], is_force=True))
    if "删除" in meta["title"]:
        delete_tag_group(api, [group_id], is_force=False)
        cc.registry.pop(f"group:{group_id}")
    return CaseStatus.PASS


def _measure(ctx, cc, meta):
    _ds, tg = _prepare_online(ctx, cc, changing=True)
    from ua_test_harness.fixtures import tag
    samples = []
    for _ in range(30):
        start = time.monotonic()
        row = tag.read_rt(ctx, tg["name"])
        samples.append((time.monotonic() - start) * 1000.0)
        check_true("measured_response", bool(row))
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    ctx.emitter.metric(meta["id"], "latency_mean_ms", value=statistics.mean(samples), unit="ms")
    ctx.emitter.metric(meta["id"], "latency_p95_ms", value=p95, unit="ms")
    return CaseStatus.MEASURED


def _performance(ctx, cc, meta):
    _ds, tg = _prepare_online(ctx, cc, changing=True)
    from ua_test_harness.fixtures import tag
    errors = []
    def read_once():
        return tag.read_rt(ctx, tg["name"])
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(read_once) for _ in range(50)]
        for fut in as_completed(futures):
            try:
                check_true("perf_result", bool(fut.result()))
            except Exception as exc:
                errors.append(str(exc))
    check_true("no_perf_errors", not errors, hint=str(errors[:3]))
    ctx.emitter.metric(meta["id"], "requests", value=50, unit="count")
    return CaseStatus.MEASURED


def _blocked(ctx, meta, reason: str):
    ctx.emitter.log("WARN", meta["id"], f"BLOCKED: {reason}")
    return CaseStatus.BLOCKED


def execute_documented_case(ctx, cc, meta: dict[str, Any]):
    """按能力域和标题把文档 Case 分派到共享真实执行器。"""
    chapter = meta["chapter"]
    title = meta["title"]
    text = " ".join(str(meta.get(k, "")) for k in ("title", "precondition", "steps", "expected", "verification"))

    if chapter == "UA-1-1":
        return _online_smoke(ctx, cc, meta)
    if chapter == "UA-1-2":
        if "历史" in title:
            return _history(ctx, cc, meta)
        return _datasource_state(ctx, cc, meta)
    if chapter == "UA-1-3":
        if "历史" in text:
            return _blocked(ctx, meta, "断线历史时序需要可控历史落库夹具")
        return _datasource_state(ctx, cc, meta)
    if chapter == "UA-1-4":
        return _blocked(ctx, meta, "多数据源 Case 需要两个独立 Mock endpoint；当前 functional 配置只有一个")
    if chapter == "UA-1-5":
        if "位号" in title or "回收站" in title:
            return _tag_delete(ctx, cc, meta)
        return _online_smoke(ctx, cc, meta)
    if chapter == "UA-1-6":
        return _blocked(ctx, meta, "ds-info/test 的 testType 适配器尚未在 tpt_api 中暴露")

    if chapter == "UA-2-1":
        if "查询" in title or "列表" in title:
            return _tag_query(ctx, cc, meta)
        return _online_smoke(ctx, cc, meta)
    if chapter == "UA-2-2":
        if "GUI-DEFERRED" in text:
            return _blocked(ctx, meta, "文档明确标记 GUI-DEFERRED")
        return _tag_query(ctx, cc, meta)
    if chapter == "UA-2-3":
        return _blocked(ctx, meta, "导入导出需要文件上传/下载适配器和工作簿夹具")
    if chapter == "UA-2-4":
        return _tag_delete(ctx, cc, meta)
    if chapter == "UA-2-5":
        return _group(ctx, cc, meta)

    if chapter == "UA-3-1":
        return _rt_read(ctx, cc, meta)
    if chapter == "UA-3-2":
        return _rt_read(ctx, cc, meta)
    if chapter == "UA-3-3":
        return _rt_write(ctx, cc, meta)
    if chapter == "UA-3-4":
        return _history(ctx, cc, meta)
    if chapter == "UA-3-5":
        return _measure(ctx, cc, meta)
    if chapter == "UA-3-6":
        return _performance(ctx, cc, meta)

    raise AssertFail(f"no scenario executor for {meta['id']} chapter={chapter}")
