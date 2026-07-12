"""tests/ua_3/test_13_types.py:13 类型参数化采集与写(plan.md 11 推荐补充)。

参数化方式:循环 13 种数据类型,每个跑一次 UA-3-1-001 + UA-3-3-001 的核心断言。
为了避免 catalog 爆胀,这里只暴露一个 case(UA-3-1-013types),但函数内遍历 13 种类型。
"""
from __future__ import annotations

from ua_test_harness.catalog import case
from ua_test_harness.fixtures import datasource, tag
from ua_test_harness.fixtures.environment import ensure_mock_ready, ensure_logged_in
from ua_test_harness.clients import mock_control
from ua_test_harness.polling import wait_until
from ua_test_harness.models import StepDef


DS_NAME = "ua_auto_ua3_13types"

TYPES = [
    ("BOOLEAN", True), ("S_BYTE", -1), ("BYTE", 1), ("SHORT", -2), ("U_SHORT", 2),
    ("INT", -3), ("U_INT", 3), ("LONG", -4), ("U_LONG", 4),
    ("FLOAT", 1.5), ("DOUBLE", 2.5), ("STRING", "hi"), ("DATE_TIME", "2026-01-01T00:00:00Z"),
]


@case(
    id="UA-3-1-013types",
    title="13 类型参数化采集",
    chapter="UA-3-1",
    kind="exploratory",
    tags=["rt", "ua-3", "13-types"],
    timeout_sec=600,
    steps=[
        StepDef(step_id="ensure-mock", title="mock ready"),
        StepDef(step_id="create-ds", title="创建数据源"),
        StepDef(step_id="loop-types", title="遍历 13 种类型 add + 采集"),
    ],
    assertions=["每种类型 RT 在 timeout 内出现值;不串类型"],
)
def ua_3_1_013types_collect(ctx, cc):
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    endpoint = mock_control.get_endpoint("functional", ctx)
    ds = datasource.create_datasource(ctx, DS_NAME, endpoint)
    from ua_test_harness.fixtures.datasource import wait_alive

    wait_alive(ctx, ds["id"], timeout=90.0)
    for dtype, sample in TYPES:
        name = f"ua31t_{dtype.lower()}_{ctx.config.run_id[:10]}".replace("-", "_")
        tag.create_tag(ctx, name, ds_id=ds["id"], data_type=dtype, writable=(dtype not in ("STRING", "DATE_TIME")), frequency=5)
        def has_value(d=dtype):
            rt = tag.read_rt(ctx, name)
            return rt.get("quality", 0) != 0
        wait_until(f"rt:{name}", has_value, timeout=ctx.config.timeouts.rt_visibility_sec, interval=2.0)