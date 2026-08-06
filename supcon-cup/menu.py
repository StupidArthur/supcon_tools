"""后台管理菜单提取。

从 umsAdmin/info 返回的菜单树中提取竞赛关心的三类菜单：
  - 算法和模型管理（分类算法、算法管理）
  - 数据仓库
  - 任务管理
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "tpt_api" / "python"))

from tpt_api import AlgAPI
from tpt_api import users as users_mod


@dataclass
class MenuItem:
    """菜单项：标题 + 路由路径 + 子菜单（递归同结构）。"""
    title: str = ""
    path: str = ""
    children: list["MenuItem"] = field(default_factory=list)

    @classmethod
    def from_raw(cls, d: dict[str, Any]) -> "MenuItem":
        return cls(
            title=d.get("title", "") or "",
            path=d.get("name", "") or "",
            children=[cls.from_raw(c) for c in (d.get("children") or [])],
        )


@dataclass
class BackendMenus:
    """从系统管理下提取的三类菜单：算法和模型管理、数据仓库、任务管理。"""
    算法和模型管理: MenuItem = field(default_factory=MenuItem)
    数据仓库: MenuItem = field(default_factory=MenuItem)
    任务管理: MenuItem = field(default_factory=MenuItem)

    @property
    def 分类算法(self) -> str:
        return self._find_child_path(self.算法和模型管理, "分类算法")

    @property
    def 算法管理(self) -> str:
        return self._find_child_path(self.算法和模型管理, "算法管理")

    @staticmethod
    def _find_child_path(parent: MenuItem, title: str) -> str:
        for c in parent.children:
            if c.title == title:
                return c.path
        return ""

    def summary(self) -> str:
        lines = ["=== 后台管理菜单 ==="]
        for label, menu in [
            ("算法和模型管理", self.算法和模型管理),
            ("数据仓库", self.数据仓库),
            ("任务管理", self.任务管理),
        ]:
            lines.append(f"{label}:")
            self._dump(menu, lines, 1)
        return "\n".join(lines)

    @staticmethod
    def _dump(menu: MenuItem, lines: list[str], depth: int) -> None:
        for c in menu.children:
            path = f"  path={c.path}" if c.path else ""
            lines.append(f"{'  ' * depth}- {c.title}{path}")
            if c.children:
                BackendMenus._dump(c, lines, depth + 1)


_WANTED = {"算法和模型管理", "数据仓库", "任务管理"}


def get_backend_menus(api: AlgAPI) -> BackendMenus:
    """登录后调用，提取后台管理菜单。"""
    info = users_mod.get_admin_info(api)
    result = BackendMenus()
    for m in info.menus:
        if m.get("title") != "系统管理":
            continue
        for child in (m.get("children") or []):
            title = child.get("title", "")
            if title == "算法和模型管理":
                result.算法和模型管理 = MenuItem.from_raw(child)
            elif title == "数据仓库":
                result.数据仓库 = MenuItem.from_raw(child)
            elif title == "任务管理":
                result.任务管理 = MenuItem.from_raw(child)
    return result


def get_scene_menus(api: AlgAPI) -> list[MenuItem]:
    """提取 TptSceneApp 下的 children。"""
    info = users_mod.get_admin_info(api)
    for m in info.menus:
        if m.get("title") == "TptSceneApp":
            return [MenuItem.from_raw(c) for c in (m.get("children") or [])]
    return []
