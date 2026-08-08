"""TPT admin 用户管理测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from tpt_api import AlgAPI, User, UserDraft
from tpt_api import users as users_module


def test_list_users_empty_keyword(api, mock_transport) -> None:
    mock_transport.register(
        "/xpt-system/api/system-manager/umsAdmin/listByOrgId",
        {"code": "00000", "content": {"records": [], "total": 0, "size": 10, "current": 1, "pages": 0}},
    )
    resp = users_module.list_users(api, page=1, page_size=10)
    assert resp.total == 0
    assert resp.records == []


def test_list_users_with_keyword(api, mock_transport) -> None:
    """关键词搜索：adminWhere 应当是 {"*nickName*|...": "kw"}。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "content": {
                "records": [
                    {"id": 1, "username": "u1", "nickName": "n1", "email": "e1@x", "phone": "138"}
                ],
                "total": 1, "size": 10, "current": 1, "pages": 1,
            },
        }, request=request)

    # 重置 transport 为自定义
    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    api.client.headers["Authorization"] = "Bearer abc"

    resp = users_module.list_users(api, page=1, page_size=10, keyword="u1")
    assert captured["body"]["data"]["adminWhere"] == {"*nickName*|*username*|*phone*|*email*": "u1"}
    assert len(resp.records) == 1
    assert resp.records[0].username == "u1"


def test_create_user_defaults(api, mock_transport) -> None:
    """CreateUser body 必须含硬编码默认值 orgIds=[1], roleIds="5", type="2"。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000", "msg": "OK"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    users_module.create_user(api, UserDraft(
        username="alice", password="p", nickName="A", email="a@x", phone="1",
    ))

    data = captured["body"]["data"]
    assert data["orgIds"] == [1]
    assert data["roleIds"] == "5"
    assert data["type"] == "2"
    assert data["gender"] == "1"
    assert data["orgName"] == "默认组织"
    assert data["code"] == "alice"  # code 沿用 username
    assert data["icon"] == ""


def test_create_user_admin_override(api, mock_transport) -> None:
    """CreateUser 传管理员类型+管理员角色时 body 用的是传入值。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000", "msg": "OK"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    users_module.create_user(api, UserDraft(
        username="bob", password="p", nickName="B",
        type="1", orgIds=[7], orgName="研发部", roleIds="4",
    ))

    data = captured["body"]["data"]
    assert data["orgIds"] == [7]
    assert data["orgName"] == "研发部"
    assert data["type"] == "1"
    assert data["roleIds"] == "4"


def test_list_roles(api, mock_transport) -> None:
    """list_roles 解析 umsRole/page 记录，body 含 *name* 模糊 + 分页。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "content": {
                "records": [
                    {"id": 5, "name": "普通用户角色", "code": "normalRole", "description": "普通用户角色", "status": 0},
                    {"id": 4, "name": "管理员角色", "code": "systemRole", "description": "管理员角色", "status": 0},
                ],
                "total": 2, "size": 1000, "current": 1, "pages": 1,
            },
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    resp = users_module.list_roles(api, name="角色")
    assert captured["body"]["data"]["*name*"] == "角色"
    assert captured["body"]["requestBase"]["page"] == "1-1000"
    assert resp.total == 2
    assert resp.records[0].name == "普通用户角色"
    assert resp.records[1].id == 4


def test_get_all_users_paginates(api) -> None:
    """get_all_users 自动翻页：第一页满，第二页空。"""
    import httpx as _httpx
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> _httpx.Response:
        call_count["n"] += 1
        body = json.loads(request.content)
        page = body["requestBase"]["page"]
        if page == "1-2":
            # 1 record（< page_size=2）→ loop breaks
            return _httpx.Response(200, json={
                "code": "00000",
                "content": {
                    "records": [{"id": 1}],
                    "total": 1, "size": 2, "current": 1, "pages": 1,
                },
            }, request=request)
        return _httpx.Response(200, json={
            "code": "00000",
            "content": {"records": [], "total": 0, "size": 2, "current": 2, "pages": 0},
        }, request=request)

    api.client = _httpx.Client(base_url=api.base_url, transport=_httpx.MockTransport(handler))
    api.token = "abc"
    all_users = users_module.get_all_users(api, page_size=2)
    assert len(all_users) == 1
    assert call_count["n"] == 1  # 第一页不足 page_size，循环停下


def test_user_from_dict() -> None:
    u = User.from_dict({
        "id": 1, "username": "u", "code": "u", "nickName": "n",
        "email": "e@x", "phone": "138", "status": 0, "type": 2,
    })
    assert u.id == 1
    assert u.username == "u"
    assert u.status == 0
    assert u.type == 2
