"""cubapi/cub-data tag 历史值查询测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from tpt_api import AlgAPI
from tpt_api import cubdata as cub_mod


def test_read_history_data_query_params(api) -> None:
    """read_history_data 把 tag_names 拼成逗号分隔字符串放到 query params。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={
            "code": "00000",
            "content": {"data": [{"tagName": "FICQ_60402.PV", "tagValue": 1.23}]},
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    result = cub_mod.read_history_data(
        api,
        tag_names=["FICQ_60402.PV", "LIC_60501.MV", "TE60402.PV"],
        start_time="2026-08-03 18:54:27",
        end_time="2026-08-03 20:54:27",
    )

    assert captured["method"] == "GET"
    assert captured["params"]["startTime"] == "2026-08-03 18:54:27"
    assert captured["params"]["endTime"] == "2026-08-03 20:54:27"
    assert captured["params"]["tagNames"] == "FICQ_60402.PV,LIC_60501.MV,TE60402.PV"
    assert result == {"data": [{"tagName": "FICQ_60402.PV", "tagValue": 1.23}]}


def test_read_history_data_single_tag(api) -> None:
    """单个位号也能正常拼接。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={
            "code": "00000",
            "content": [],
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    cub_mod.read_history_data(
        api,
        tag_names=["T602D.VALUE"],
        start_time="2026-08-03 00:00:00",
        end_time="2026-08-03 23:59:59",
    )

    assert captured["params"]["tagNames"] == "T602D.VALUE"


def test_read_history_data_no_content_returns_full(api) -> None:
    """响应有 code=00000 但无 content 字段时返回完整响应 dict。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000",
            "data": [{"tagName": "x", "tagValue": 1.0}],
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    result = cub_mod.read_history_data(
        api,
        tag_names=["x"],
        start_time="2026-08-03 00:00:00",
        end_time="2026-08-03 01:00:00",
    )

    assert result == {"code": "00000", "data": [{"tagName": "x", "tagValue": 1.0}]}


def test_read_history_data_business_error(api) -> None:
    """业务 code 非 00000 时（HTTPS 模式 + isSuccess 缺失）不抛异常，返回完整 dict。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "A0001",
            "msg": "参数错误",
        }, request=request)

    api.client = httpx.Client(base_url="https://test.supcon.com",
                              transport=httpx.MockTransport(handler))
    api._https_mode = True
    api.token = "abc"

    result = cub_mod.read_history_data(
        api,
        tag_names=["x"],
        start_time="2026-08-03 00:00:00",
        end_time="2026-08-03 01:00:00",
    )

    assert result == {"code": "A0001", "msg": "参数错误"}
