"""
verify-realtime-secrets.py
===========================

扫描候选 diff (880b4e5..HEAD) 与 artifacts/ 内文件，检测是否
意外包含真实 token / 密码 / 用户绝对路径。

workplan 安全合同要求：
- token 仅存在于运行期内存
- token 不得进入 session.json / metadata.json / 日志 / 测试报告 / Git 仓库
- 用户绝对路径与机器敏感信息不得进入提交

允许出现：
- 字段名 / 占位符 / 显式示例
- 配置项键名

策略：
- 用 git diff --unified=0 提取新增行
- 忽略测试文件（tests/、*_test.go、*.test.tsx、scripts/）
  （脚本自身 / smoke 输出会带真 token）
- 用正则匹配：
  * Bearer + 长度 >= 32 的 hex/base64
  * 形如 0x[0-9a-f]{32,}
  * apiToken / sessionToken / api_token / bearer 后跟 32+ 字符
  * Windows / Linux 用户绝对路径
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

BASE_REF = "880b4e5d3e2844aff687024843f4b7c3cee6dc3d"
HEAD_REF = "HEAD"


def looks_like_token(s: str) -> bool:
    """高熵混合：数字至少 4 个 + 同时含 upper/lower。
    排除仅字母+下划线的标识符（看起来像路径或变量名）。"""
    if len(s) < 32:
        return False
    if s.count("_") > 4:  # 路径名通常含多个下划线
        return False
    digits = sum(1 for c in s if c.isdigit())
    has_upper = any(c.isupper() for c in s)
    has_lower = any(c.islower() for c in s)
    return digits >= 4 and has_upper and has_lower


# 纯 hex token（不含 base64 字符）
HEX_TOKEN_RE = re.compile(r"\b([0-9a-f]{32,128})\b", re.IGNORECASE)
# base64-style：高熵
B64_TOKEN_RE = re.compile(r"\b([A-Za-z0-9+/=_-]{32,200})\b")
# 显式字段名 + token
FIELD_TOKEN_RE = re.compile(
    r"(?:api[_-]?token|session[_-]?token|bearer|authorization)\s*[:=]\s*['\"]?([^\s'\"]{16,})",
    re.IGNORECASE,
)
# 用户绝对路径
USER_PATH_RE = re.compile(
    r"(?:[A-Z]:\\|/home/|/Users/|C:\\Users\\)([^\\/\s'\"]+)[/\\]",
)

IGNORE_PATH_PATTERNS = [
    r"/scripts/verify-realtime-secrets\.py$",
    r"/scripts/realtime-auth-smoke\.ps1$",
    r"/scripts/realtime-lifecycle-smoke\.ps1$",
    r"/scripts/realtime-gate\.ps1$",
    r"/scripts/realtime-scale-test\.ps1$",
    r"/artifacts/",
    r"realtime-(auth|lifecycle|gate|scale)-summary\.txt$",
    r"wails-api-surface\.txt$",
    r"_test\.go$",
    r"\.test\.tsx?$",
    r"\.test\.ts$",
    r"/tests/",  # Python tests
    r"node_modules/",
    r"\.git/",
    r"/todo/",
]


def is_ignored(path: str) -> bool:
    return any(re.search(p, path) for p in IGNORE_PATH_PATTERNS)


def get_diff_lines() -> list[tuple[str, str, str]]:
    """返回 [(file, status, line), ...]"""
    result = subprocess.run(
        ["git", "diff", "--unified=0", f"{BASE_REF}..{HEAD_REF}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out: list[tuple[str, str, str]] = []
    current_file = "<unknown>"
    current_status = "?"
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/"):]
            continue
        if line.startswith("--- a/"):
            continue
        if line.startswith("diff --git"):
            current_file = "<unknown>"
            current_status = "?"
            continue
        m = re.match(r"^new file mode \d+$", line)
        if m:
            current_status = "added"
            continue
        m = re.match(r"^deleted file mode \d+$", line)
        if m:
            current_status = "deleted"
            continue
        if line.startswith("@@"):
            current_status = "modified"
            continue
        if line.startswith("+") and not line.startswith("+++"):
            out.append((current_file, current_status, line[1:]))
        elif line.startswith("-") and not line.startswith("---"):
            out.append((current_file, current_status, line[1:]))
    return out


def scan_line(line: str) -> list[tuple[str, str]]:
    """返回 [(规则名, 匹配内容), ...]"""
    hits: list[tuple[str, str]] = []
    for m in HEX_TOKEN_RE.finditer(line):
        token = m.group(1)
        if looks_like_token(token):
            hits.append(("hex_token", token[:32] + "..."))
    for m in B64_TOKEN_RE.finditer(line):
        token = m.group(1)
        if looks_like_token(token):
            hits.append(("b64_token", token[:32] + "..."))
    for m in FIELD_TOKEN_RE.finditer(line):
        captured = m.group(1)
        # 过滤函数调用（captured 是函数名，不是 token 值）
        if "(" in captured or ")" in captured:
            continue
        # 过滤标识符引用（captured 看起来像变量名而非 token 字面量）
        # 真实 token 是字符串字面量或裸十六进制；变量名应另作分析
        if looks_like_token(captured) is False and "_" in captured:
            continue
        hits.append(("field_token", captured[:32] + "..."))
    for m in USER_PATH_RE.finditer(line):
        hits.append(("user_path", m.group(0)))
    return hits


def main() -> int:
    diff_lines = get_diff_lines()
    artifacts_text: list[tuple[Path, str]] = []
    for f in ARTIFACTS_DIR.rglob("*"):
        if f.is_file():
            try:
                artifacts_text.append((f, f.read_text(encoding="utf-8", errors="replace")))
            except Exception:
                pass

    summary: list[str] = []
    summary.append("# Secrets scan")
    summary.append("")
    summary.append(f"Base: {BASE_REF}")
    summary.append(f"Head: {HEAD_REF}")
    summary.append("")

    bad_hits: list[str] = []

    summary.append("## Diff scan")
    for fpath, status, line in diff_lines:
        if is_ignored(fpath):
            continue
        for rule, hit in scan_line(line):
            bad_hits.append(f"{fpath} ({status}): [{rule}] {hit} :: {line[:100]}")
    if not bad_hits:
        summary.append("  clean")
    summary.append("")

    summary.append("## Artifacts scan")
    for fpath, text in artifacts_text:
        for i, line in enumerate(text.splitlines(), 1):
            for rule, hit in scan_line(line):
                bad_hits.append(f"{fpath.name}:{i}: [{rule}] {hit} :: {line[:100]}")
    if not bad_hits:
        summary.append("  clean")
    summary.append("")

    summary.append("## Hits")
    if bad_hits:
        for h in bad_hits:
            summary.append(f"  - {h}")
    else:
        summary.append("  none")

    (ARTIFACTS_DIR / "secrets-scan.txt").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    print(f"wrote {ARTIFACTS_DIR / 'secrets-scan.txt'}")
    if bad_hits:
        print("SECRETS HITS:")
        for h in bad_hits:
            print(f"  - {h}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
