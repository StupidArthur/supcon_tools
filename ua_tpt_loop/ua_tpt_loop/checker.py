"""4 步闭环编排：串起 ua_client + tpt_checker。"""

from __future__ import annotations

import logging
import time
from typing import Any

from tpt_api import AlgAPI, TptAPIError

from .mocker_yaml import MockerSpec
from .report import (
    LoopResult,
    StepResult,
    summarize_ds,
    summarize_flow,
    summarize_tags,
    summarize_ua,
)
from .tpt_checker import check_tpt_data_flow, check_tpt_ds, check_tpt_tags
from .ua_client import check_ua_server

log = logging.getLogger(__name__)


def check_loop(
    mocker: MockerSpec,
    *,
    tpt_url: str,
    tpt_user: str,
    tpt_password: str,
    tpt_tenant_id: str = "",
    sample_seconds: int = 10,
    auto_register: bool = True,
    skip_step1: bool = False,
    opcua_public_host: str | None = None,
) -> LoopResult:
    """跑完整 4 步闭环检查，返回 LoopResult。

    任何一步失败都继续跑后面（不要短路），方便一次性看到全部问题。

    参数:
      opcua_public_host: tpt 用来连 ua_mocker 的 host（覆盖 YAML 里的 host）。
        如果 ua_mocker 和 tpt 在不同机器 / 不同子网，必须给这个值，
        否则 tpt 拿 127.0.0.1 连的是它自己而不是 ua_mocker。
        不影响 Step 1：Step 1 始终用 YAML 里的 host（翻译 0.0.0.0 → 127.0.0.1），
        因为它是"我能不能连上 ua_mocker"的本地检查。
    """
    # 计算 tpt 端用的 endpoint（仅用于 Step 2/3/4 注册和查询）
    from urllib.parse import urlparse, urlunparse
    tpt_endpoint = mocker.endpoint
    if opcua_public_host:
        u = urlparse(tpt_endpoint)
        tpt_endpoint = urlunparse(u._replace(netloc=f"{opcua_public_host}:{u.port}"))

    steps: list[StepResult] = []
    ds_id: int | None = None

    # --- Step 1: ua-server node (用 YAML 里的 endpoint) ---
    t0 = time.monotonic()
    if skip_step1:
        ua_result = None
        step1 = StepResult(
            index=1, name="ua-server node", passed=True,
            summary="skipped (--skip-step1)", duration_seconds=0.0,
        )
    else:
        ua_result = check_ua_server(mocker)
        summary, details = summarize_ua(ua_result)
        step1 = StepResult(
            index=1, name="ua-server node",
            passed=ua_result.passed, summary=summary,
            details=details, error=ua_result.error,
            duration_seconds=time.monotonic() - t0,
        )
    steps.append(step1)

    if not step1.passed:
        log.warning("Step 1 失败，仍继续跑 Step 2-4 收集信息")

    # --- Login tpt ---
    api = AlgAPI(tpt_url, timeout=30.0)
    try:
        api.login(tpt_user, tpt_password, tpt_tenant_id)
    except TptAPIError as e:
        for idx, name in [(2, "tpt data source"), (3, "tpt tags"), (4, "tpt data flow")]:
            steps.append(StepResult(
                index=idx, name=name, passed=False, summary="",
                error=f"tpt 登录失败: code={e.code} msg={e.msg}",
                duration_seconds=0.0,
            ))
        return LoopResult(steps=steps, mocker_endpoint=tpt_endpoint, tpt_url=tpt_url)

    # --- Step 2: tpt data source (用 tpt_endpoint) ---
    t0 = time.monotonic()
    ds_result = check_tpt_ds(api, tpt_endpoint, auto_register=auto_register)
    summary, details = summarize_ds(ds_result)
    step2 = StepResult(
        index=2, name="tpt data source",
        passed=ds_result.passed, summary=summary,
        details=details, error=ds_result.error,
        duration_seconds=time.monotonic() - t0,
    )
    steps.append(step2)
    ds_id = ds_result.ds_id

    # --- Step 3: tpt tags ---
    t0 = time.monotonic()
    if ds_id is None:
        step3 = StepResult(
            index=3, name="tpt tags", passed=False, summary="",
            error="无 ds_id（Step 2 失败）", duration_seconds=0.0,
        )
    else:
        tags_result = check_tpt_tags(api, ds_id, mocker, auto_register=auto_register)
        summary, details = summarize_tags(tags_result)
        step3 = StepResult(
            index=3, name="tpt tags",
            passed=tags_result.passed, summary=summary,
            details=details, error=tags_result.error,
            duration_seconds=time.monotonic() - t0,
        )
    steps.append(step3)

    # --- Step 4: tpt data flow ---
    t0 = time.monotonic()
    if ds_id is None:
        step4 = StepResult(
            index=4, name="tpt data flow", passed=False, summary="",
            error="无 ds_id（Step 2 失败）", duration_seconds=0.0,
        )
    else:
        flow_result = check_tpt_data_flow(api, mocker, ds_id, sample_seconds=sample_seconds)
        summary, details = summarize_flow(flow_result)
        step4 = StepResult(
            index=4, name="tpt data flow",
            passed=flow_result.passed, summary=summary,
            details=details, error=flow_result.error,
            duration_seconds=time.monotonic() - t0,
        )
    steps.append(step4)

    return LoopResult(steps=steps, mocker_endpoint=tpt_endpoint, tpt_url=tpt_url)
