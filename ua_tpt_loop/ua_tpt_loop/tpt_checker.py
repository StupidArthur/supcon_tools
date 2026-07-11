"""tpt 检查器：步骤 2/3/4。

复用 tpt_api.datahub 调数据源 / 位号 / 历史值 API。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from tpt_api import AlgAPI, TptAPIError
from tpt_api import datahub as dh_mod

from .mocker_yaml import MockerSpec
from .ua_client import connect_endpoint

log = logging.getLogger(__name__)


@dataclass
class TptDsCheckResult:
    """步骤 2：tpt 数据源检查结果。"""
    passed: bool
    details: str
    ds_id: int | None = None
    ds_name: str | None = None
    error: str | None = None


@dataclass
class TptTagsCheckResult:
    """步骤 3：tpt 位号检查结果。"""
    passed: bool
    details: str
    expected: int = 0
    existing: int = 0
    registered: int = 0
    skipped: int = 0
    error: str | None = None


@dataclass
class TptFlowCheckResult:
    """步骤 4：tpt 数据流检查结果。"""
    passed: bool
    details: str
    tag_count: int = 0
    flowing_count: int = 0
    sample: dict[str, int] = None  # type: ignore[assignment]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.sample is None:
            self.sample = {}


def check_tpt_ds(
    api: AlgAPI,
    mocker_url: str,
    auto_register: bool = True,
    ds_name_hint: str | None = None,
) -> TptDsCheckResult:
    """步骤 2：检查 tpt 是否已注册 ds-info（按 dsTarUrl 查）。缺失则按 auto_register 决定是否补。

    注意: 如果 mocker_url 是 0.0.0.0 之类的 bind 地址，会先翻译成 127.0.0.1 再注册，
    这样 tpt 才能真的连上。
    """
    # 把 YAML 里的 0.0.0.0 翻译成 tpt 能连的地址
    register_url = connect_endpoint(mocker_url)

    all_ds = dh_mod.get_all_ds_info(api)
    for ds in all_ds:
        if ds.get("dsTarUrl") == register_url:
            return TptDsCheckResult(
                passed=True,
                details=f"ds_id={ds['id']}, name={ds['dsName']}, alive={ds.get('alive')}",
                ds_id=ds["id"],
                ds_name=ds["dsName"],
            )

    if not auto_register:
        return TptDsCheckResult(
            passed=False,
            details="",
            error=f"dsTarUrl={register_url} 未注册；传 --no-auto-register 时不自动注册",
        )

    # 自动注册
    if not ds_name_hint:
        # 默认名从 URL 派生：mocker_<host>_<port>
        from urllib.parse import urlparse
        u = urlparse(register_url)
        ds_name_hint = f"mocker_{u.hostname}_{u.port}"
    try:
        result = dh_mod.add_ds_info(api, ds_name=ds_name_hint, ds_tar_url=register_url)
        return TptDsCheckResult(
            passed=True,
            details=f"自动注册: ds_id={result['id']}, name={ds_name_hint}, url={register_url}",
            ds_id=result["id"],
            ds_name=ds_name_hint,
        )
    except TptAPIError as e:
        return TptDsCheckResult(
            passed=False,
            details="",
            error=f"add_ds_info 失败: code={e.code} msg={e.msg}",
        )


def check_tpt_tags(
    api: AlgAPI,
    ds_id: int,
    spec: MockerSpec,
    auto_register: bool = True,
) -> TptTagsCheckResult:
    """步骤 3：检查 tpt 是否已注册 tag-info（按 dsId + tagName 查）。

    关键约定：tpt 端的 tagName / tagBaseName 格式是 "{ns}_{node_id}"，例如
    ua_mocker 的 ns=1 + node "loop_demo_1" → tag "1_loop_demo_1"。

    查 tag 时也用这个 namespaced 形式；同时验证返回 tag 的 dsId 是不是当前 ds_id
    （之前测试发现 tag 名字相同但 dsId 不同的旧记录会被误判为"已存在"）。
    """
    # 拉一次全量 tag
    all_tags = dh_mod.get_all_tags(api)
    by_name: dict[str, dict[str, Any]] = {t["tagName"]: t for t in all_tags}

    expected = spec.registerable_node_ids  # [(node_id, tpt_data_type), ...]
    skipped = len(spec.unsupported_node_ids)
    ns = spec.namespace_index

    existing_ids: list[str] = []       # 名字 + dsId 都对
    name_only: list[str] = []          # 名字存在但 dsId 不对（脏数据）
    missing: list[tuple[str, int]] = []  # 名字不存在
    for node_id, dt in expected:
        namespaced = f"{ns}_{node_id}"
        rec = by_name.get(namespaced)
        if rec is None:
            missing.append((node_id, dt))
        elif rec.get("dsId") == ds_id:
            existing_ids.append(node_id)
        else:
            # 同名 tag 但挂在别的 ds 上 —— 不能直接当"已存在"，
            # 也不能用同名 add（会 A0001: duplicated）
            name_only.append(node_id)

    if not missing and not name_only:
        return TptTagsCheckResult(
            passed=True,
            details=f"{len(existing_ids)}/{len(expected)} tag 已注册，{skipped} 个 tpt 不支持的节点已跳过",
            expected=len(expected),
            existing=len(existing_ids),
            registered=0,
            skipped=skipped,
        )

    if not auto_register:
        msg_parts = []
        if missing:
            msg_parts.append(f"缺 {len(missing)} 个: {[n for n, _ in missing[:3]]}{'...' if len(missing) > 3 else ''}")
        if name_only:
            msg_parts.append(
                f"{len(name_only)} 个同名 tag 挂在别的 ds 上（脏数据）: {name_only[:3]}{'...' if len(name_only) > 3 else ''}；"
                f"需先 delete_tags 再 add（tpt_api 暂无 delete 端点，需手动或新增）"
            )
        return TptTagsCheckResult(
            passed=False,
            details="",
            expected=len(expected),
            existing=len(existing_ids),
            skipped=skipped,
            error="；".join(msg_parts) + "；传 --no-auto-register 时不自动注册",
        )

    # 自动注册缺失的
    registered = 0
    register_errors: list[str] = []
    for node_id, dt in missing:
        try:
            namespaced = f"{ns}_{node_id}"
            dh_mod.add_tag(
                api, tag_name=namespaced, tag_base_name=namespaced,
                data_type=dt, ds_id=ds_id,
                group_id="0", unit="", only_read=False, frequency=10,
                need_push=True, is_vector=False,
            )
            registered += 1
        except TptAPIError as e:
            register_errors.append(f"{node_id}: {e.code} {e.msg}")

    if register_errors:
        return TptTagsCheckResult(
            passed=False,
            details="",
            expected=len(expected),
            existing=len(existing_ids) + registered,
            registered=registered,
            skipped=skipped,
            error=f"注册失败 {len(register_errors)} 个: {register_errors[:2]}",
        )

    summary = f"自动注册 {registered} 个，已有 {len(existing_ids)} 个，{skipped} 个 tpt 不支持已跳过"
    if name_only:
        summary += f"；⚠️ {len(name_only)} 个同名 tag 挂在别的 ds 上：{name_only[:3]}，需先清"

    return TptTagsCheckResult(
        passed=True,
        details=summary,
        expected=len(expected),
        existing=len(existing_ids) + registered,
        registered=registered,
        skipped=skipped,
    )


def check_tpt_data_flow(
    api: AlgAPI,
    spec: MockerSpec,
    ds_id: int,
    sample_seconds: int = 10,
) -> TptFlowCheckResult:
    """步骤 4：等 sample_seconds 秒，再查 tpt 看数据是否真的在流。

    tpt 端的 tag 名是 namespaced 形式 "{ns}_{node}"，所以查询时也要用 namespaced。
    """
    # 用 namespaced 名查（和 Step 3 注册时一致）
    expected_node_ids = [f"{spec.namespace_index}_{nid}" for nid, _ in spec.registerable_node_ids]
    if not expected_node_ids:
        return TptFlowCheckResult(
            passed=False,
            details="",
            tag_count=0,
            error="无 registerable 节点（全部 tpt 不支持）",
        )

    log.info("等待 %ds 让 tpt 从数据源拉值...", sample_seconds)
    time.sleep(sample_seconds)

    end = datetime.now()
    beg = end - timedelta(seconds=sample_seconds * 3)  # 窗口 3x 留缓冲

    beg_str = beg.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end.strftime("%Y-%m-%d %H:%M:%S")
    try:
        hist = dh_mod.get_all_history(
            api, expected_node_ids, beg_str, end_str, page_size=100,
        )
    except TptAPIError as e:
        return TptFlowCheckResult(
            passed=False,
            details="",
            tag_count=len(expected_node_ids),
            error=f"get_all_history 失败: code={e.code} msg={e.msg}",
        )

    sample = {nid: len(hist.get(nid, [])) for nid in expected_node_ids}
    flowing = sum(1 for c in sample.values() if c > 0)
    missing = [nid for nid, c in sample.items() if c == 0]

    if flowing == len(expected_node_ids):
        return TptFlowCheckResult(
            passed=True,
            details=f"{flowing}/{len(expected_node_ids)} tag 在最近 {sample_seconds}s 窗口内有数据",
            tag_count=len(expected_node_ids),
            flowing_count=flowing,
            sample=sample,
        )
    return TptFlowCheckResult(
        passed=False,
        details="",
        tag_count=len(expected_node_ids),
        flowing_count=flowing,
        sample=sample,
        error=f"窗口内 {flowing}/{len(expected_node_ids)} tag 有数据，缺: {missing[:3]}{'...' if len(missing) > 3 else ''}",
    )
