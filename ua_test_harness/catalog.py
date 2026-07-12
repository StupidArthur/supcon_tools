"""catalog.py:用例装饰器 + catalog JSON 导出。

约定(plan.md 4):
- 测试函数装饰器 @case(...) 元数据是执行事实源;
- python -m ua_test_harness.catalog export 生成 catalog.json 给 Go/UI。
- 同一进程内 also 通过 all_defs() 提供内存访问。
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import CaseDef, StepDef

_REGISTRY: list[CaseDef] = []


def case(
    id: str,
    title: str,
    chapter: str,
    kind: str = "regression",
    tags: list[str] | None = None,
    timeout_sec: int = 600,
    exclusive_resources: list[str] | None = None,
    destructive: bool = False,
    doc_path: str = "",
    description: str = "",
    steps: list[StepDef] | None = None,
    assertions: list[str] | None = None,
) -> Callable[[Callable], Callable]:
    """用例装饰器。"""

    def deco(fn: Callable) -> Callable:
        try:
            file_path = os.path.relpath(fn.__code__.co_filename)
        except Exception:
            file_path = ""
        cd = CaseDef(
            id=id,
            title=title,
            chapter=chapter,
            kind=kind,
            tags=list(tags or []),
            timeout_sec=int(timeout_sec),
            exclusive_resources=list(exclusive_resources or []),
            destructive=bool(destructive),
            doc_path=doc_path,
            description=description,
            steps=list(steps or []),
            assertions=list(assertions or []),
            impl_func=fn,
            file_path=file_path,
            lineno=int(fn.__code__.co_firstlineno),
        )
        _REGISTRY.append(cd)
        fn.__ua_case_def__ = cd  # type: ignore[attr-defined]
        return fn

    return deco


def step(step_id: str, title: str = "") -> Callable[[Callable], Callable]:
    """步骤装饰器(轻量标记,仅记录到 CaseDef.steps)。"""
    _LAST_STEP = (step_id, title)

    def deco(fn: Callable) -> Callable:
        _LAST_STEP  # noqa: F841 (placeholder marker; CaseDef.steps 由装饰器构造)
        return fn

    return deco


def all_defs() -> list[CaseDef]:
    """返回当前进程中已注册的全部 CaseDef。

    为保证稳定顺序,按 (chapter, id) 排序。
    """
    return sorted(_REGISTRY, key=lambda c: (c.chapter, c.id))


def reset() -> None:
    """清空注册表(仅供单测)。"""
    _REGISTRY.clear()


def discover(package: str = "ua_test_harness.tests") -> int:
    """递归导入 tests 包以触发装饰器注册。

    返回新注册的 CaseDef 数量。
    """
    before = len(_REGISTRY)
    try:
        mod = importlib.import_module(package)
    except ModuleNotFoundError:
        return 0
    if not hasattr(mod, "__path__"):
        return 0
    for _finder, name, _ispkg in pkgutil.walk_packages(mod.__path__, prefix=f"{package}."):
        try:
            importlib.import_module(name)
        except Exception:
            continue
    return len(_REGISTRY) - before


def export_catalog(
    out_path: str | Path,
    *,
    package: str = "ua_test_harness.tests",
    version: int = 1,
) -> dict:
    """导出 catalog JSON 到文件,并返回导出的 dict。"""
    discover(package)
    chapters_map: dict[str, dict] = {}
    for c in all_defs():
        ch = chapters_map.setdefault(
            c.chapter,
            {"id": c.chapter, "title": c.chapter, "cases": []},
        )
        ch["cases"].append(
            {
                "id": c.id,
                "title": c.title,
                "kind": c.kind,
                "implemented": True,
                "tags": c.tags,
                "timeoutSec": c.timeout_sec,
                "destructive": c.destructive,
                "exclusiveResources": c.exclusive_resources,
                "docPath": c.doc_path,
                "description": c.description,
                "steps": [{"stepId": s.step_id, "title": s.title} for s in c.steps],
                "assertions": c.assertions,
                "filePath": c.file_path,
                "lineno": c.lineno,
            }
        )
    chapters = [chapters_map[k] for k in sorted(chapters_map.keys())]
    catalog = {
        "version": version,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chapters": chapters,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog