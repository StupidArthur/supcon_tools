"""TPT admin 菜单管理端点。

POST /tpt-admin/system-manager/umsMenu  创建菜单项

同一端点承载两种业务：
  1. 创建目录菜单（type=0）：如"数据仓库"挂在"系统管理"下，不带路由
  2. 创建页面菜单（type=1, pathType=3）：如"批流任务模板"挂在"数据仓库"下，带内路由路径
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .client import AlgAPI

log = logging.getLogger(__name__)

MenuCreatePath = "/tpt-admin/system-manager/umsMenu"
RoleAllocMenuPath = "/xpt-system/api/system-manager/umsRole/allocMenu"

# 普通用户角色 ID（平台默认）。
NormalRoleId = 5


@dataclass
class MenuDraft:
    """创建菜单的输入载荷。

    字段含义：
      parentId:     父菜单 ID（顶级为 0）
      parentName:   父菜单标题（顶级为空串）
      title:        菜单标题
      level:        层级（0=顶级, 1=二级, ...）
      type:         类型（0=目录, 1=页面, 2=按钮）
      sort:         排序序号
      status:       状态（0=启用, 1=禁用）
      icon:         图标 class（如 "fa-connectdevelop"）
      name:         路由路径（目录类型可空）
      pathType:     路径类型（0=无, 2=外链, 3=内路由）
      dataType:     数据类型（0=系统菜单, 1=业务菜单）
    """
    parentId: int = 0
    parentName: str = ""
    title: str = ""
    level: int = 0
    type: int = 0
    sort: int = 0
    status: int = 0
    icon: str = "fa-connectdevelop"
    name: str = ""
    pathType: int = 0
    dataType: int = 1


def create_menu(api: AlgAPI, draft: MenuDraft) -> dict[str, Any]:
    """创建一个菜单项（通用，直接传 MenuDraft）。

    POST /tpt-admin/system-manager/umsMenu
    body: {"data": {parentId, level, status, parentName, type, title, sort, icon, ...}}
    """
    body: dict[str, Any] = {
        "parentId": draft.parentId,
        "level": draft.level,
        "status": draft.status,
        "parentName": draft.parentName,
        "type": draft.type,
        "title": draft.title,
        "sort": draft.sort,
        "icon": draft.icon,
    }
    if draft.name:
        body["name"] = draft.name
    if draft.pathType:
        body["pathType"] = draft.pathType
    if draft.dataType:
        body["dataType"] = draft.dataType

    raw = api._request("POST", MenuCreatePath, body=body, wrap=True)
    if isinstance(raw, dict):
        return raw
    return {"id": raw}


def create_dir_menu(
    api: AlgAPI,
    parent_id: int,
    parent_name: str,
    title: str,
    level: int = 1,
    sort: int = 0,
    icon: str = "fa-connectdevelop",
) -> dict[str, Any]:
    """创建目录菜单（type=0）。

    业务场景：在父菜单下新建一个目录分类，如"数据仓库"挂在"系统管理"下。
    不带路由路径，纯分组节点。
    """
    draft = MenuDraft(
        parentId=parent_id,
        parentName=parent_name,
        title=title,
        level=level,
        type=0,
        sort=sort,
        status=0,
        icon=icon,
    )
    return create_menu(api, draft)


def create_page_menu(
    api: AlgAPI,
    parent_id: int,
    parent_name: str,
    title: str,
    route: str,
    level: int = 2,
    sort: int = 0,
    icon: str = "fa-connectdevelop",
    path_type: int = 3,
) -> dict[str, Any]:
    """创建页面菜单（type=1）。

    path_type:
      3 = 内路由（如 /ware-house/filemanage）
      2 = 外链（如 /tpt-admin）

    业务场景：
      - 内路由：在目录菜单下新建页面，如"文件管理"挂在"数据仓库"下
      - 外链：在顶级菜单下新建后台管理入口，如"后台管理"挂在"TptSceneApp"下
    """
    draft = MenuDraft(
        parentId=parent_id,
        parentName=parent_name,
        title=title,
        level=level,
        type=1,
        sort=sort,
        status=0,
        icon=icon,
        name=route,
        pathType=path_type,
    )
    return create_menu(api, draft)


def update_menu_status(api: AlgAPI, menu_id: int, status: int) -> dict[str, Any]:
    """修改菜单状态（启用/禁用）。

    PUT /tpt-admin/system-manager/umsMenu
    body: {"data": {"id": menu_id, "status": status}}

    status: 0=启用, 1=禁用（隐藏）

    业务场景：创建菜单后，禁用不需要展示的页面，如只保留"文件管理"可见，
    禁用"批流任务模板"/"批流任务配置"/"任务监控"。
    """
    body: dict[str, Any] = {
        "id": menu_id,
        "status": status,
    }
    raw = api._request("PUT", MenuCreatePath, body=body, wrap=True)
    return raw if isinstance(raw, dict) else {}


def disable_menu(api: AlgAPI, menu_id: int) -> dict[str, Any]:
    """禁用菜单（status=1，隐藏不展示）。"""
    return update_menu_status(api, menu_id, status=1)


def enable_menu(api: AlgAPI, menu_id: int) -> dict[str, Any]:
    """启用菜单（status=0，正常展示）。"""
    return update_menu_status(api, menu_id, status=0)


def alloc_role_menus(
    api: AlgAPI,
    role_id: int,
    menu_ids: list[int | str],
) -> dict[str, Any]:
    """给角色分配菜单权限。

    POST /xpt-system/api/system-manager/umsRole/allocMenu
    body: {"data": {"id": role_id, "menuIdList": [...]}}

    注意：
      - 此接口响应较慢，建议 api 实例 timeout 设大（如 60s）
      - menuIdList 平台侧 int/str 混用，保持原样传入即可
      - role_id=5 为"普通用户角色"（平台默认）

    业务场景：创建完所有菜单后，将菜单权限分配给普通用户角色，
    使该租户下的普通用户能看到"系统管理"和"TptSceneApp"下的指定菜单。
    """
    body: dict[str, Any] = {
        "id": role_id,
        "menuIdList": menu_ids,
    }
    raw = api._request("POST", RoleAllocMenuPath, body=body, wrap=True)
    return raw if isinstance(raw, dict) else {}
