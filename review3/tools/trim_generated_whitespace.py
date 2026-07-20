#!/usr/bin/env python
"""trim_generated_whitespace.py

Wails generate (Wails v2.12.0) 在 wailsjs/go/models.ts 中会产生
带尾部空格的缩进行（``        `` 后接换行）。`git diff --check` 默认
会报 trailing whitespace。

本脚本一次性去掉这些尾部空格，让 `git diff --check` 退出码为 0。

阶段 4 验收要求：fix generated file trailing whitespace。
后续每次 wails build 之后可以重新运行本脚本。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    ROOT / "config-tool" / "frontend" / "wailsjs" / "go" / "models.ts",
]

PATTERN = re.compile(r"(.*?)([\r\n]*)\Z")


def trim(path: Path) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    new_lines = []
    for line in content.splitlines(True):
        m = PATTERN.match(line)
        body = m.group(1).rstrip()
        nl = m.group(2)
        new_lines.append(body + nl)
    new_content = "".join(new_lines)
    if new_content != content:
        path.write_text(new_content, encoding="utf-8", newline="")
        return True
    return False


def main() -> int:
    changed = []
    for p in TARGETS:
        if trim(p):
            changed.append(str(p))
    if changed:
        print("trimmed trailing whitespace in:")
        for c in changed:
            print(f"  {c}")
    else:
        print("no trailing whitespace to trim")
    return 0


if __name__ == "__main__":
    sys.exit(main())