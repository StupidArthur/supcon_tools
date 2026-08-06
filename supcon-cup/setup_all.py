"""批量配置租户菜单：对未配置的租户执行标准 12 步流程。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tpt_api" / "python"))

from tpt_api import AlgAPI
from tpt_api import menus as m
from tpt_api import users as users_mod

TEAMS_JSON = Path(__file__).resolve().parent / "teams.json"
BASE_URL = "https://tpt.supcon.com"
ADMIN_USER = "admin"
ADMIN_PWD = "tpt@2026"
SYS_MGR_ID = 1213


def _find_child(children: list, title: str) -> dict | None:
    for c in children:
        if c.get("title") == title:
            return c
    return None


def check_ok(raw_menus: list) -> bool:
    sys_menu = None
    for m_ in raw_menus:
        if m_.get("title") == "系统管理":
            sys_menu = m_
            break
    if not sys_menu:
        return False
    children = sys_menu.get("children") or []
    for need in ("算法和模型管理", "数据仓库", "任务管理"):
        if not _find_child(children, need):
            return False
    has_scene = any(m_.get("title") == "TptSceneApp" for m_ in raw_menus)
    return has_scene


def setup_tenant(tenant_id: str) -> str:
    """对单个租户执行标准流程，返回 'OK' 或错误信息。"""
    api = AlgAPI(BASE_URL, timeout=60.0)
    api.login(ADMIN_USER, ADMIN_PWD, tenant_id)

    info = users_mod.get_admin_info(api)
    if check_ok(info.menus):
        return "SKIP(已配置)"

    # 查找或创建"数据仓库"
    sys_menu = _find_child(info.menus, "系统管理")
    if not sys_menu:
        return "ERROR: admin 无[系统管理]菜单"
    ds = _find_child(sys_menu.get("children") or [], "数据仓库")
    if ds:
        ds_id = ds["id"]
    else:
        r = m.create_dir_menu(api, parent_id=SYS_MGR_ID, parent_name="系统管理",
                              title="数据仓库", level=1, sort=2)
        ds_id = r.get("id")
        if not ds_id:
            return "ERROR: 创建数据仓库失败 r=%s" % r

    # 步骤2-5: 创建4个页面菜单
    pages = []
    for title, route, sort in [
        ("批流任务模板", "/ware-house/algmanage", 0),
        ("批流任务配置", "/ware-house/taskconfig", 2),
        ("任务监控", "/ware-house/taskmonitor", 3),
        ("文件管理", "/ware-house/filemanage", 4),
    ]:
        existing = _find_child(
            (_find_child(sys_menu.get("children") or [], "数据仓库") or {}).get("children") or [],
            title,
        )
        if existing:
            mid = existing["id"]
        else:
            r = m.create_page_menu(api, parent_id=ds_id, parent_name="数据仓库",
                                   title=title, route=route, level=2, sort=sort)
            mid = r.get("id")
            if not mid:
                return "ERROR: 创建%s失败 r=%s" % (title, r)
        pages.append((title, mid))
        time.sleep(0.3)

    # 步骤6-8: 禁用前3个
    for title, mid in pages[:3]:
        m.disable_menu(api, menu_id=mid)

    file_mgr_id = pages[3][1]

    # 步骤9: 创建TptSceneApp
    scene = _find_child(info.menus, "TptSceneApp")
    if scene:
        scene_id = scene["id"]
    else:
        r = m.create_dir_menu(api, parent_id=0, parent_name="根目录",
                              title="TptSceneApp", level=0, sort=1)
        scene_id = r.get("id")
        if not scene_id:
            return "ERROR: 创建TptSceneApp失败 r=%s" % r

    # 步骤10: 创建后台管理
    admin_entry = _find_child(
        (_find_child(info.menus, "TptSceneApp") or {}).get("children") or [],
        "后台管理",
    )
    if admin_entry:
        admin_entry_id = admin_entry["id"]
    else:
        r = m.create_page_menu(api, parent_id=scene_id, parent_name="TptSceneApp",
                               title="后台管理", route="/tpt-admin", level=1, sort=0, path_type=2)
        admin_entry_id = r.get("id")
        if not admin_entry_id:
            return "ERROR: 创建后台管理失败 r=%s" % r

    # 步骤11: 禁用TptSceneApp
    m.disable_menu(api, menu_id=scene_id)

    # 步骤12: 分配角色菜单
    menu_ids = [
        1,
        scene_id, admin_entry_id,
        1218, 1219, 1220,
        1234, 1235, 1236,
        file_mgr_id,
        ds_id,
        pages[0][1], pages[1][1], pages[2][1],
        str(scene_id), str(1218), str(1214), str(1234), str(1213), str(ds_id),
        "0",
    ]
    r = m.alloc_role_menus(api, role_id=5, menu_ids=menu_ids)
    if isinstance(r, dict) and r.get("isSuccess"):
        return "OK"
    return "WARN: alloc结果=%s" % r


def main() -> None:
    with open(TEAMS_JSON, encoding="utf-8") as f:
        teams = json.load(f)

    ok, fail, skip = 0, 0, 0
    for i, t in enumerate(teams, 1):
        tid = t["密码"]
        phone = t["登录号码"]
        try:
            result = setup_tenant(tid)
            if result == "OK":
                ok += 1
                print("[%2d/39] OK    %s  tid=%s" % (i, phone, tid))
            elif result.startswith("SKIP"):
                skip += 1
                print("[%2d/39] SKIP  %s  tid=%s" % (i, phone, tid))
            else:
                fail += 1
                print("[%2d/39] FAIL  %s  tid=%s  %s" % (i, phone, tid, result))
        except Exception as e:
            fail += 1
            print("[%2d/39] ERROR %s  tid=%s  %s" % (i, phone, tid, str(e)[:100]))
        time.sleep(0.5)

    print("\n=== 成功 %d | 跳过 %d | 失败 %d | 总计 %d ===" % (ok, skip, fail, ok + skip + fail))


if __name__ == "__main__":
    main()
