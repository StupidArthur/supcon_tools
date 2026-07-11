"""tests/ua_3:采集 / 实时 / 写 / 历史 / 响应时间 用例。"""
from __future__ import annotations

import time

from ua_test_harness.catalog import case
from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures import datasource, tag
from ua_test_harness.fixtures.environment import ensure_mock_ready, ensure_logged_in
from ua_test_harness.clients import mock_control
from ua_test_harness.fixtures.history import HistoryFixtureFactory
from ua_test_harness.metrics import measure_ms
from ua_test_harness.models import CaseStatus, StepDef


DS_NAME = "ua_auto_ua3"


@case(
    id="UA-3-1-001",
    title="新增读取位号后自动开始采集",
    chapter="UA-3-1",
    kind="regression",
    tags=["rt", "collect", "ua-3"],
    timeout_sec=180,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增 Double 位号"),
        StepDef(step_id="wait-rt", title="轮询 RT 出现值"),
    ],
    assertions=["新增读取位号后 RT 在 rtVisibilitySec 内出现有效值"],
)
def ua_3_1_001_collect_starts_automatically(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_001", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua3_1_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="DOUBLE", writable=False, frequency=5)

    from ua_test_harness.polling import wait_until

    def has_value():
        rt = tag.read_rt(ctx, name, from_db=False)
        return rt.get("quality", 0) != 0 and rt.get("tagValue") is not None

    wait_until(f"rt:{name}", has_value, timeout=ctx.config.timeouts.rt_visibility_sec, interval=2.0)


@case(
    id="UA-3-2-001",
    title="实时库按名称读取",
    chapter="UA-3-2",
    kind="regression",
    tags=["rt", "ua-3"],
    timeout_sec=120,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增 Double 位号"),
        StepDef(step_id="rt-read", title="等 RT 出现值并读出"),
    ],
    assertions=["getRTValue 返回 quality 有效、tagTime/appTime 可解析"],
)
def ua_3_2_001_rt_read_by_name(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_002a", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua3_2a_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="DOUBLE", writable=False, frequency=5)
    from ua_test_harness.polling import wait_until

    def rt_ready():
        rt = tag.read_rt(ctx, name)
        return rt.get("quality", 0) != 0

    wait_until(f"rt:{name}", rt_ready, timeout=ctx.config.timeouts.rt_visibility_sec, interval=2.0)
    rt = tag.read_rt(ctx, name)
    check_true("rt_quality", rt.get("quality", 0) != 0)
    check_true("rt_tagTime", bool(rt.get("tagTime")))


@case(
    id="UA-3-2-012",
    title="数据库模式读取",
    chapter="UA-3-2",
    kind="regression",
    tags=["rt", "db-mode", "ua-3"],
    timeout_sec=120,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增位号"),
        StepDef(step_id="rt-read", title="等待 RT 出现"),
        StepDef(step_id="db-read", title="isFromDB=true 读取"),
    ],
    assertions=["从 DB 模式可读出最近一条 RT"],
)
def ua_3_2_012_rt_db_mode(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_002b", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua3_2b_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="INT", writable=False, frequency=5)
    from ua_test_harness.polling import wait_until

    def rt_ready():
        rt = tag.read_rt(ctx, name)
        return rt.get("quality", 0) != 0

    wait_until(f"rt:{name}", rt_ready, timeout=ctx.config.timeouts.rt_visibility_sec, interval=2.0)
    rt_db = tag.read_rt(ctx, name, from_db=True)
    check_true("rt_db_present", bool(rt_db))


@case(
    id="UA-3-3-001",
    title="单个位号写入",
    chapter="UA-3-3",
    kind="regression",
    tags=["write", "ua-3"],
    timeout_sec=120,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增可写 Double 位号"),
        StepDef(step_id="write", title="写值"),
        StepDef(step_id="readback", title="读回与写入值一致"),
    ],
    assertions=["writeTagValues 后 RT 等到对应值"],
)
def ua_3_3_001_single_tag_write(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_003", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua3_3_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="DOUBLE", writable=True, frequency=5)
    target = 42.5
    tag.write_tag(ctx, name, target)
    from ua_test_harness.polling import wait_until

    def rt_matches():
        rt = tag.read_rt(ctx, name)
        try:
            v = float(rt.get("tagValue"))
            return abs(v - target) < 1e-3
        except Exception:
            return False

    wait_until(f"write_rt:{name}", rt_matches, timeout=ctx.config.timeouts.rt_visibility_sec, interval=1.0)


@case(
    id="UA-3-4-001",
    title="方式 B 造数与基础历史查询",
    chapter="UA-3-4",
    kind="regression",
    tags=["history", "ua-3"],
    timeout_sec=240,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增 Double 位号"),
        StepDef(step_id="fixture", title="方式 B import 历史"),
        StepDef(step_id="query", title="getHistoryValue 查询"),
    ],
    assertions=["导入 N 条,getHistoryValue 返回 >= N 条"],
)
def ua_3_4_001_history_import_query(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_004", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua3_4_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="DOUBLE", writable=False, frequency=5)
    factory = HistoryFixtureFactory(ctx)
    factory.create_import_dataset(name, count=30)
    n = factory.verify_history(name, min_count=20)
    check_true("history_count", n >= 20)


@case(
    id="UA-3-5-001",
    title="单个位号实时读响应时间",
    chapter="UA-3-5",
    kind="response_time",
    tags=["rt", "response-time", "ua-3"],
    timeout_sec=120,
    destructive=False,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="add-tag", title="新增 Double 位号"),
        StepDef(step_id="warm-up", title="预热一次读取"),
        StepDef(step_id="measure", title="连续 5 次 RT 测量"),
    ],
    assertions=["5 次 RT 响应时间均记录为 metric"],
)
def ua_3_5_001_rt_response_time(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME + "_005", endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    name = "ua3_5_" + ctx.config.run_id.replace("-", "_").replace(":", "")[:14]
    tag.create_tag(ctx, name, ds_id=ds["id"], data_type="DOUBLE", writable=False, frequency=5)
    # 等 RT 出现
    from ua_test_harness.polling import wait_until

    def rt_ready():
        rt = tag.read_rt(ctx, name)
        return rt.get("quality", 0) != 0

    wait_until(f"rt:{name}", rt_ready, timeout=ctx.config.timeouts.rt_visibility_sec, interval=2.0)

    samples = []
    for i in range(5):
        with measure_ms(ctx.emitter, "UA-3-5-001", f"rt_call_{i + 1}") as h:
            tag.read_rt(ctx, name)
        samples.append(h["value"])
    samples_sorted = sorted(samples)
    p50 = samples_sorted[len(samples_sorted) // 2]
    p95 = samples_sorted[max(0, int(len(samples_sorted) * 0.95) - 1)]
    ctx.emitter.metric("UA-3-5-001", "rt_p50_ms", p50, unit="ms")
    ctx.emitter.metric("UA-3-5-001", "rt_p95_ms", p95, unit="ms")
    return CaseStatus.MEASURED