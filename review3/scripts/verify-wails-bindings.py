"""
verify-wails-bindings.py
========================

检查 Wails 自动生成的前端绑定是否暴露了内部/测试 API。

workplan 3.4 安全合同明确禁止生产绑定出现以下符号：
  - ForTest (除 *ForTest 命名族)  ——测试 helper 残留
  - TestHelper  ——helper 进程
  - commandFactory  ——低层工厂
  - readinessChecker  ——检查器类型
  - AddExitListener  ——进程 listener 注册
  - SetChildPid  ——子进程 PID 修补
  - IsPriorityCleanup  ——Cleanup 排序标记
  - terminateErrorOverride  ——测试 hook

输出：artifacts/wails-api-surface.txt
退出码：非 0 表示命中禁止符号。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BINDINGS_DIR = REPO_ROOT / "config-tool" / "frontend" / "wailsjs" / "go" / "bindings"
MODELS_FILE = REPO_ROOT / "config-tool" / "frontend" / "wailsjs" / "go" / "models.ts"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

FORBIDDEN_SYMBOLS = [
    "ForTest",
    "TestHelper",
    "commandFactory",
    "readinessChecker",
    "AddExitListener",
    "SetChildPid",
    "IsPriorityCleanup",
    "terminateErrorOverride",
]


def collect_exports_from_dts(dts_path: Path) -> list[tuple[str, str]]:
    """返回 [(binding, function)] 列表。"""
    out: list[tuple[str, str]] = []
    if not dts_path.exists():
        return out
    text = dts_path.read_text(encoding="utf-8")
    for m in re.finditer(r"export\s+function\s+(\w+)", text):
        out.append((dts_path.stem, m.group(1)))
    for m in re.finditer(r"export\s+class\s+(\w+)", text):
        out.append((dts_path.stem, m.group(1) + " (class)"))
    return out


def collect_models_classes(models_path: Path) -> list[str]:
    if not models_path.exists():
        return []
    text = models_path.read_text(encoding="utf-8")
    return re.findall(r"export\s+class\s+(\w+)", text)


def collect_exports_from_js(js_path: Path) -> list[str]:
    if not js_path.exists():
        return []
    text = js_path.read_text(encoding="utf-8")
    return re.findall(r"export\s+function\s+(\w+)", text)


def main() -> int:
    surface_lines: list[str] = []
    forbidden_hits: list[str] = []

    surface_lines.append("# Wails 生产绑定 API 面")
    surface_lines.append("")

    for dts in sorted(BINDINGS_DIR.glob("*.d.ts")):
        exports = collect_exports_from_dts(dts)
        surface_lines.append(f"## {dts.stem}")
        if not exports:
            surface_lines.append("  (no exports)")
        for binding, func in exports:
            surface_lines.append(f"  - {func}")
        for sym in FORBIDDEN_SYMBOLS:
            for _, name in exports:
                if sym in name:
                    forbidden_hits.append(
                        f"{dts.stem}: 命中禁止符号 {sym!r} （{name}）"
                    )
        js = dts.with_suffix(".js")
        js_exports = collect_exports_from_js(js)
        if js_exports:
            surface_lines.append("  (js exports: " + ", ".join(js_exports) + ")")
        for sym in FORBIDDEN_SYMBOLS:
            for name in js_exports:
                if sym in name:
                    forbidden_hits.append(
                        f"{js.name}: 命中禁止符号 {sym!r} （{name}）"
                    )
        surface_lines.append("")

    if MODELS_FILE.exists():
        surface_lines.append("## models.ts exported classes")
        for cls in collect_models_classes(MODELS_FILE):
            surface_lines.append(f"  - {cls}")
        for sym in FORBIDDEN_SYMBOLS:
            if sym in MODELS_FILE.read_text(encoding="utf-8"):
                forbidden_hits.append(f"models.ts: 命中禁止符号 {sym!r}")
        surface_lines.append("")

    surface_lines.append("## Forbidden symbol scan")
    if forbidden_hits:
        surface_lines.append("  HITS:")
        for h in forbidden_hits:
            surface_lines.append(f"    - {h}")
    else:
        surface_lines.append("  clean")

    out_path = ARTIFACTS_DIR / "wails-api-surface.txt"
    out_path.write_text("\n".join(surface_lines) + "\n", encoding="utf-8")

    print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    if forbidden_hits:
        print("FORBIDDEN HITS:")
        for h in forbidden_hits:
            print(f"  - {h}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
