"""全局检测：登录 + 菜单一致性校验，输出表格。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tpt_api" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tpt_api import AlgAPI
from tpt_api import users as users_mod

from menu import get_scene_menus

TEAMS_JSON = Path(__file__).resolve().parent / "teams.json"

EXPECTED = {
    "算法和模型管理": {
        "算法管理": {
            "path": "/alg-manager-v2.2-tpt/alglistmanage",
            "children": {"在线调试": "OnlineEditing", "发布": "Publish"},
        },
    },
    "数据仓库": {
        "文件管理": {"path": "/ware-house/filemanage", "children": {}},
    },
    "任务管理": {
        "任务管理": {"path": "/ibd-schedule/task", "children": {}},
        "任务实例": {"path": "/ibd-schedule/excutedTask", "children": {}},
    },
}


def _find_child(children: list, title: str) -> dict | None:
    for c in children:
        if c.get("title") == title:
            return c
    return None


def check_menus(raw_menus: list) -> list[str]:
    """校验系统管理下三类菜单及子菜单的路径是否正确。"""
    issues: list[str] = []
    sys_menu = None
    for m in raw_menus:
        if m.get("title") == "系统管理":
            sys_menu = m
            break
    if not sys_menu:
        actual = [m.get("title", "") for m in raw_menus]
        issues.append("无[系统管理], 实际=%s" % actual)
        return issues

    children = sys_menu.get("children") or []
    for section, subs in EXPECTED.items():
        top = _find_child(children, section)
        if not top:
            actual_titles = [c.get("title", "") for c in children]
            issues.append("缺[%s] 实际=%s" % (section, actual_titles))
            continue
        top_children = top.get("children") or []
        for sub_title, spec in subs.items():
            sub = _find_child(top_children, sub_title)
            if not sub:
                actual_titles = [c.get("title", "") for c in top_children]
                issues.append("%s缺[%s] 实际=%s" % (section, sub_title, actual_titles))
                continue
            if sub.get("name", "") != spec["path"]:
                issues.append("%s/%s path=%s≠%s" % (section, sub_title, sub.get("name", ""), spec["path"]))
            for child_title, child_path in spec["children"].items():
                fc = _find_child(sub.get("children") or [], child_title)
                if not fc:
                    issues.append("%s/%s缺子[%s]" % (section, sub_title, child_title))
                elif fc.get("name", "") != child_path:
                    issues.append("%s/%s/%s path=%s≠%s" % (section, sub_title, child_title, fc.get("name", ""), child_path))
    return issues


def check_scene(raw_menus: list) -> list[str]:
    """校验 TptSceneApp 下只有[后台管理]且 path=/tpt-admin。"""
    issues: list[str] = []
    scene = None
    for m in raw_menus:
        if m.get("title") == "TptSceneApp":
            scene = m
            break
    if not scene:
        actual = [m.get("title", "") for m in raw_menus]
        issues.append("无[TptSceneApp] 实际=%s" % actual)
        return issues
    children = scene.get("children") or []
    if len(children) != 1:
        titles = [c.get("title", "") for c in children]
        issues.append("子项数=%d 实际=%s 应为1个[后台管理]" % (len(children), titles))
        return issues
    child = children[0]
    if child.get("title") != "后台管理":
        issues.append("子项title=%s 应为[后台管理]" % child.get("title", ""))
    if child.get("name") != "/tpt-admin":
        issues.append("子项path=%s 应为[/tpt-admin]" % child.get("name", ""))
    return issues


def main() -> None:
    with open(TEAMS_JSON, encoding="utf-8") as f:
        teams = json.load(f)

    rows: list[list[str]] = []
    for i, t in enumerate(teams, 1):
        url = t["TPT地址"]
        phone = t["登录号码"]
        pwd = t["密码"]
        tid = pwd

        login_status = ""
        menu_status = ""
        scene_status = ""
        diff = ""

        try:
            api = AlgAPI("https://tpt.supcon.com", timeout=15.0)
            api.login(phone, pwd, tid)
            tlen = len(api.token or "")
            if tlen > 0:
                login_status = "OK"
            else:
                login_status = "OK(token空)"
        except Exception as e:
            login_status = "FAIL(%s)" % str(e)[:60]
            rows.append([str(i), url, phone, pwd, login_status, "-", "-", "-"])
            continue

        try:
            info = users_mod.get_admin_info(api)
            issues = check_menus(info.menus)
            if issues:
                menu_status = "MISMATCH"
                diff = "; ".join(issues)
            else:
                menu_status = "OK"
            scene_issues = check_scene(info.menus)
            if scene_issues:
                scene_status = "MISMATCH"
                diff = (diff + "; " if diff else "") + "; ".join(scene_issues)
            else:
                scene_status = "OK"
        except Exception as e:
            menu_status = "ERR(%s)" % str(e)[:60]
            scene_status = "-"

        rows.append([str(i), url, phone, pwd, login_status, menu_status, scene_status, diff])
        time.sleep(0.3)

    headers = ["#", "URL", "用户", "密码", "登录", "菜单", "场景", "差异项"]
    widths = [4, 12, 14, 12, 14, 10, 10, 60]

    def fmt_row(cells: list[str]) -> str:
        parts = []
        for cell, w in zip(cells, widths):
            parts.append(cell[:w].ljust(w))
        return " | ".join(parts)

    sep = "-+-".join("-" * w for w in widths)
    print(fmt_row(headers))
    print(sep)
    for r in rows:
        print(fmt_row(r))

    ok_login = sum(1 for r in rows if r[4].startswith("OK"))
    ok_menu = sum(1 for r in rows if r[5] == "OK")
    ok_scene = sum(1 for r in rows if r[6] == "OK")
    total = len(rows)
    print()
    print("登录成功 %d/%d | 菜单一致 %d/%d | 场景一致 %d/%d" % (ok_login, total, ok_menu, total, ok_scene, total))


if __name__ == "__main__":
    main()
