"""tpt_checker 单元测试（用 mock transport 模拟 tpt 响应）。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from tpt_api import AlgAPI
from ua_tpt_loop import MockerSpec
from ua_tpt_loop.tpt_checker import check_tpt_data_flow, check_tpt_ds, check_tpt_tags


def make_mock_api(transport: httpx.MockTransport) -> AlgAPI:
    api = AlgAPI("http://test", timeout=5.0)
    api.client = httpx.Client(base_url=api.base_url, transport=transport)
    api.token = "abc"
    return api


def make_mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --- check_tpt_ds ---


def test_check_tpt_ds_existing() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000",
            "records": [
                {"id": 5, "dsName": "omc167",
                 "dsTarUrl": "opc.tcp://10.10.58.105:18950/ua_mocker/", "alive": True},
            ],
            "total": 1, "size": 10, "current": 1, "pages": 1,
        }, request=req)

    api = make_mock_api(make_mock_transport(handler))
    r = check_tpt_ds(api, mocker_url="opc.tcp://10.10.58.105:18950/ua_mocker/", auto_register=True)
    assert r.passed
    assert r.ds_id == 5
    assert "omc167" in r.details


def test_check_tpt_ds_auto_register() -> None:
    """ds 不在 → auto_register=True → add_ds_info 被调。"""
    def handler(req: httpx.Request) -> httpx.Response:
        if "/ds-info/page" in req.url.path:
            return httpx.Response(200, json={
                "code": "00000", "records": [], "total": 0,
                "size": 10, "current": 1, "pages": 0,
            }, request=req)
        if "/ds-info/add" in req.url.path:
            return httpx.Response(200, json={
                "code": "00000", "id": 7, "dsName": "mocker_x_18950",
                "dsType": 1, "dsSubType": 4,
                "dsTarUrl": "opc.tcp://x:18950/ua_mocker/",
            }, request=req)
        return httpx.Response(404, json={"code": "NOT_FOUND"}, request=req)

    api = make_mock_api(make_mock_transport(handler))
    r = check_tpt_ds(api, mocker_url="opc.tcp://x:18950/ua_mocker/", auto_register=True)
    assert r.passed
    assert r.ds_id == 7
    assert "自动注册" in r.details


def test_check_tpt_ds_no_register() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000", "records": [], "total": 0,
            "size": 10, "current": 1, "pages": 0,
        }, request=req)

    api = make_mock_api(make_mock_transport(handler))
    r = check_tpt_ds(api, mocker_url="opc.tcp://x:18950/ua_mocker/", auto_register=False)
    assert not r.passed
    assert "未注册" in r.error


# --- check_tpt_tags ---


def make_simple_spec(tmp_path) -> MockerSpec:
    p = tmp_path / "c.yaml"
    p.write_text("""
server: "0.0.0.0"
port: 18950
cycle: 1000
namespace_index: 1
nodes:
  - name: "t_"
    type: Double
    count: 3
    change: false
    writable: false
""", encoding="utf-8")
    return MockerSpec.from_yaml(p)


def test_check_tpt_tags_all_existing(tmp_path) -> None:
    """tag 用 namespaced 名字 1_t_1，dsId 一致。"""
    def handler(req: httpx.Request) -> httpx.Response:
        if "/tag-info/page" in req.url.path:
            return httpx.Response(200, json={
                "code": "00000",
                "records": [
                    {"id": 10, "tagName": "1_t_1", "dsId": 5},
                    {"id": 11, "tagName": "1_t_2", "dsId": 5},
                    {"id": 12, "tagName": "1_t_3", "dsId": 5},
                ],
                "total": 3, "size": 10, "current": 1, "pages": 1,
            }, request=req)
        return httpx.Response(404, json={"code": "NOT_FOUND"}, request=req)

    api = make_mock_api(make_mock_transport(handler))
    spec = make_simple_spec(tmp_path)
    r = check_tpt_tags(api, ds_id=5, spec=spec, auto_register=True)
    assert r.passed
    assert r.existing == 3
    assert r.registered == 0


def test_check_tpt_tags_auto_register_missing(tmp_path) -> None:
    """缺 2 个 tag → auto_register → 调 2 次 add_tag。"""
    add_calls = {"n": 0}
    sent_base_names: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if "/tag-info/page" in req.url.path:
            return httpx.Response(200, json={
                "code": "00000",
                "records": [
                    {"id": 10, "tagName": "1_t_1", "dsId": 5},
                ],
                "total": 1, "size": 10, "current": 1, "pages": 1,
            }, request=req)
        if "/tag-info/add" in req.url.path:
            import json as _j
            sent_base_names.append(_j.loads(req.content)["data"]["tagBaseName"])
            add_calls["n"] += 1
            return httpx.Response(200, json={"code": "00000", "msg": "OK"}, request=req)
        return httpx.Response(404, json={"code": "NOT_FOUND"}, request=req)

    api = make_mock_api(make_mock_transport(handler))
    spec = make_simple_spec(tmp_path)
    r = check_tpt_tags(api, ds_id=5, spec=spec, auto_register=True)
    assert r.passed
    assert r.existing == 3
    assert r.registered == 2
    assert add_calls["n"] == 2
    # tagBaseName 应该是 namespaced 形式
    assert sent_base_names == ["1_t_2", "1_t_3"]


def test_check_tpt_tags_no_register(tmp_path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000", "records": [], "total": 0,
            "size": 10, "current": 1, "pages": 0,
        }, request=req)

    api = make_mock_api(make_mock_transport(handler))
    spec = make_simple_spec(tmp_path)
    r = check_tpt_tags(api, ds_id=5, spec=spec, auto_register=False)
    assert not r.passed
    assert "缺 3 个" in r.error


def test_check_tpt_tags_name_clash_on_different_ds(tmp_path) -> None:
    """同名 tag 挂在别的 ds 上（脏数据）：auto_register 时会报告 ⚠️，不强行 add。"""
    def handler(req: httpx.Request) -> httpx.Response:
        if "/tag-info/page" in req.url.path:
            # 3 个 tag 名字相同但 dsId=99（不是当前的 5）
            return httpx.Response(200, json={
                "code": "00000",
                "records": [
                    {"id": 10, "tagName": "1_t_1", "dsId": 99},
                    {"id": 11, "tagName": "1_t_2", "dsId": 99},
                    {"id": 12, "tagName": "1_t_3", "dsId": 99},
                ],
                "total": 3, "size": 10, "current": 1, "pages": 1,
            }, request=req)
        return httpx.Response(404, json={"code": "NOT_FOUND"}, request=req)

    api = make_mock_api(make_mock_transport(handler))
    spec = make_simple_spec(tmp_path)
    r = check_tpt_tags(api, ds_id=5, spec=spec, auto_register=True)
    # existing=0（dsId 不匹配），name_only=3（挂着别的 ds）
    assert r.existing == 0
    # 不应尝试 add（因为会 A0001 duplicated）
    # 实际上当前实现把 name_only 不当作 missing，所以 passed=True
    # 但 details 里有 ⚠️ 提示
    assert r.passed
    assert "⚠️" in r.details or "脏数据" in r.details or "同名" in r.details


def test_check_tpt_tags_skips_unsupported_types(tmp_path) -> None:
    """String 类型 tpt 不支持，应跳过。"""
    p = tmp_path / "c.yaml"
    p.write_text("""
server: "0.0.0.0"
port: 18950
cycle: 1000
namespace_index: 1
nodes:
  - name: "t_"
    type: Double
    count: 2
  - name: "str_"
    type: String
    count: 2
""", encoding="utf-8")
    spec = MockerSpec.from_yaml(p)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000", "records": [], "total": 0,
            "size": 10, "current": 1, "pages": 0,
        }, request=req)

    api = make_mock_api(make_mock_transport(handler))
    r = check_tpt_tags(api, ds_id=5, spec=spec, auto_register=False)
    # expected=2 (只 t_), skipped=2 (str_)
    assert r.expected == 2
    assert r.skipped == 2


# --- check_tpt_data_flow ---


def test_check_tpt_data_flow_all_flowing(tmp_path, monkeypatch) -> None:
    """mock get_all_history 返回所有 namespaced tag 都有数据。"""
    spec = make_simple_spec(tmp_path)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000",
            "content": {
                "1_t_1": {"total": 5, "list": [{}] * 5},
                "1_t_2": {"total": 3, "list": [{}] * 3},
                "1_t_3": {"total": 7, "list": [{}] * 7},
            },
        }, request=req)

    api = make_mock_api(make_mock_transport(handler))
    import ua_tpt_loop.tpt_checker as tc
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    r = check_tpt_data_flow(api, spec, ds_id=5, sample_seconds=1)
    assert r.passed
    assert r.flowing_count == 3
    assert r.sample == {"1_t_1": 5, "1_t_2": 3, "1_t_3": 7}


def test_check_tpt_data_flow_some_missing(tmp_path, monkeypatch) -> None:
    spec = make_simple_spec(tmp_path)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000",
            "content": {
                "1_t_1": {"total": 5, "list": [{}] * 5},
                "1_t_2": {"total": 0, "list": []},
                "1_t_3": {"total": 7, "list": [{}] * 7},
            },
        }, request=req)

    api = make_mock_api(make_mock_transport(handler))
    import ua_tpt_loop.tpt_checker as tc
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    r = check_tpt_data_flow(api, spec, ds_id=5, sample_seconds=1)
    assert not r.passed
    assert r.flowing_count == 2
    assert "1_t_2" in r.error


def test_check_tpt_data_flow_no_registerable(tmp_path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("""
server: "0.0.0.0"
port: 18950
cycle: 1000
namespace_index: 1
nodes:
  - name: "s_"
    type: String
    count: 1
""", encoding="utf-8")
    spec = MockerSpec.from_yaml(p)

    api = make_mock_api(make_mock_transport(lambda r: httpx.Response(200, json={"code": "00000"}, request=r)))
    r = check_tpt_data_flow(api, spec, ds_id=5, sample_seconds=1)
    assert not r.passed
    assert "tpt 不支持" in r.error
