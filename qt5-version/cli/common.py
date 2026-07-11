"""
CLI 交互框架 — 引导式流程工具集

核心理念：工具引导用户完成流程，每步提示 + 默认值 + 确认。
用法：
    from cli.common import Wizard, step, info, success, error, warn
"""
import sys
import os
import time
from contextlib import contextmanager
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import questionary

# ── 编码修复：强制控制台使用 UTF-8 ────────────────────
def _fix_console_encoding():
    """Windows CMD 默认代码页是 GBK (936)，会导致中文乱码。"""
    if sys.platform == "win32":
        # 方法1: Python 层面重配置 stdout/stderr
        for stream in ("stdout", "stderr", "stdin"):
            obj = getattr(sys, stream)
            if hasattr(obj, "reconfigure"):
                try:
                    obj.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass
        # 方法2: 设置 Windows 控制台代码页为 UTF-8 (65001)
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass

_fix_console_encoding()

console = Console()

# ── 样式 ──────────────────────────────────────────────

TOOL_STYLE = "bold cyan"
STEP_STYLE = "bold white"
INFO_STYLE = "dim"
SUCCESS_STYLE = "bold green"
ERROR_STYLE = "bold red"
WARN_STYLE = "bold yellow"
PROMPT_STYLE = "bold"


# ── 输出 ──────────────────────────────────────────────

def banner(title: str, subtitle: str = ""):
    """打印工具标题横幅。"""
    text = Text(title, style=TOOL_STYLE)
    if subtitle:
        text.append(f"\n{subtitle}", style="dim")
    console.print(Panel(text, border_style="cyan", padding=(0, 2)))


def step(n: int, total: int, desc: str):
    """打印步骤标题。"""
    console.print(f"\n[bold]Step {n}/{total}:[/bold] {desc}")


def info(msg: str):
    console.print(f"  {msg}", style=INFO_STYLE)


def success(msg: str):
    console.print(f"  ✓ {msg}", style=SUCCESS_STYLE)


def error(msg: str):
    console.print(f"  ✗ {msg}", style=ERROR_STYLE)


def warn(msg: str):
    console.print(f"  ⚠ {msg}", style=WARN_STYLE)


def divider():
    console.print("─" * 50, style="dim")


# ── 交互 ──────────────────────────────────────────────

def ask_text(message: str, default: str = "", password: bool = False) -> str:
    """文本输入，支持默认值和密码模式。"""
    if password:
        return questionary.password(message + ":").ask() or ""
    return questionary.text(message + ":", default=default).ask() or ""


def ask_path(message: str, default: str = "") -> str:
    """路径输入，带验证。"""
    while True:
        path = ask_text(message, default=default)
        if not path:
            warn("路径不能为空")
            continue
        return path


def confirm(message: str, default: bool = True) -> bool:
    """确认对话框。"""
    result = questionary.confirm(message + "?", default=default).ask()
    return result if result is not None else False


def choose(message: str, choices: list[str]) -> str:
    """单选列表。"""
    return questionary.select(message + ":", choices=choices).ask() or ""


# ── 加载状态 ──────────────────────────────────────────

@contextmanager
def spinner(message: str):
    """显示加载动画，完成后显示成功。"""
    with console.status(f"[bold]{message}[/bold]", spinner="dots"):
        start = time.time()
        try:
            yield
            elapsed = time.time() - start
            success(f"{message} ✓ ({elapsed:.1f}s)")
        except Exception as e:
            error(f"{message} ✗")
            raise


# ── 表格 ──────────────────────────────────────────────

def result_table(title: str, headers: list[str], rows: list[list[str]], styles: list[str] = None):
    """打印结果表格。"""
    table = Table(title=title, show_header=True, header_style="bold")
    for i, h in enumerate(headers):
        s = styles[i] if styles and i < len(styles) else ""
        table.add_column(h, style=s)
    for row in rows:
        table.add_row(*row)
    console.print(table)


# ── Wizard 流程控制 ────────────────────────────────────

class Wizard:
    """
    引导式流程控制器。
    用法：
        w = Wizard("算法同步工具")
        w.add_step("连接配置", connect_fn)
        w.add_step("扫描匹配", scan_fn)
        w.add_step("执行同步", sync_fn)
        w.run()
    """

    def __init__(self, title: str, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self.steps: list[tuple[str, callable]] = []
        self.context: dict = {}  # 步骤间共享数据

    def add_step(self, name: str, fn):
        self.steps.append((name, fn))

    def run(self):
        banner(self.title, self.subtitle)
        total = len(self.steps)
        for i, (name, fn) in enumerate(self.steps, 1):
            step(i, total, name)
            try:
                fn(self.context)
            except KeyboardInterrupt:
                console.print("\n[bold]已取消。[/bold]")
                sys.exit(0)
            except Exception as e:
                error(f"步骤失败: {e}")
                if not confirm("是否重试当前步骤"):
                    error("流程中止")
                    sys.exit(1)
                # 重试一次
                try:
                    fn(self.context)
                except Exception as e2:
                    error(f"重试失败: {e2}")
                    sys.exit(1)
        console.print()
        success("全部完成！")
