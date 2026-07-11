"""
交互演示工具 — 无需服务器，体验 CLI 全部交互方式

模拟一个完整的"算法体检"流程：
  连接 → 获取数据 → 分析 → 展示报告 → 长时任务(运行中交互) → 日志折叠 → 导出确认
"""
import sys
import os
import time
import random
import threading
import msvcrt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.common import (
    Wizard, banner, step, info, success, error, warn, divider,
    ask_text, confirm, choose, spinner, result_table, console,
)

# ── 模拟数据 ──────────────────────────────────────────

MOCK_ALGOS = [
    {"name": "cstr_v3.zip",      "id": 1001, "zhName": "CSTR反应器模型",   "isRelease": 1, "status": "healthy"},
    {"name": "ph_model_v2.zip",  "id": 1002, "zhName": "PH值预测模型",     "isRelease": 1, "status": "warning"},
    {"name": "temp_ctrl.zip",    "id": 1003, "zhName": "温度控制算法",     "isRelease": 0, "status": "healthy"},
    {"name": "pressure_v1.zip",  "id": 1004, "zhName": "压力监测算法",     "isRelease": 1, "status": "error"},
    {"name": "flow_rate.zip",    "id": 1005, "zhName": "流量计算模型",     "isRelease": 0, "status": "healthy"},
    {"name": "level_ctrl.zip",   "id": 1006, "zhName": "液位控制算法",     "isRelease": 1, "status": "healthy"},
]

STATUS_MAP = {
    "healthy": ("正常", "bold green"),
    "warning": ("告警", "bold yellow"),
    "error":   ("异常", "bold red"),
}


# ── Step 1: 连接配置 (text + password) ────────────────

def step_connect(ctx: dict):
    """演示: 文本输入 + 密码输入"""
    console.print("[dim]演示: 文本输入、密码输入[/dim]\n")

    ctx["url"] = ask_text("服务器地址", default="http://10.16.11.1:31501")
    ctx["username"] = ask_text("用户名", default="admin")
    ctx["password"] = ask_text("密码", password=True)

    with spinner("正在连接服务器"):
        time.sleep(1.2)  # 模拟网络延迟

    success(f"连接成功: {ctx['url']}")
    info(f"用户: {ctx['username']}")

    with spinner("获取算法列表"):
        time.sleep(0.8)

    success(f"已缓存 {len(MOCK_ALGOS)} 个算法")


# ── Step 2: 数据分析 (spinner + warn/error) ───────────

def step_analyze(ctx: dict):
    """演示: 加载动画 + 告警/错误信息"""
    console.print("[dim]演示: 加载动画、告警提示、错误提示[/dim]\n")

    with spinner("扫描算法健康状态"):
        time.sleep(1.0)

    healthy = [a for a in MOCK_ALGOS if a["status"] == "healthy"]
    warnings = [a for a in MOCK_ALGOS if a["status"] == "warning"]
    errors = [a for a in MOCK_ALGOS if a["status"] == "error"]

    success(f"扫描完成: 正常 {len(healthy)}，告警 {len(warnings)}，异常 {len(errors)}")

    if warnings:
        warn("发现告警算法:")
        for a in warnings:
            info(f"  - {a['name']} ({a['zhName']})")

    if errors:
        error("发现异常算法:")
        for a in errors:
            info(f"  - {a['name']} ({a['zhName']})")

    ctx["warnings"] = warnings
    ctx["errors"] = errors


# ── Step 3: 报告展示 (table) ──────────────────────────

def step_report(ctx: dict):
    """演示: Rich 表格"""
    console.print("[dim]演示: 结果表格[/dim]\n")

    rows = []
    for a in MOCK_ALGOS:
        status_text, _ = STATUS_MAP.get(a["status"], ("未知", ""))
        release_text = "已发布" if a["isRelease"] else "未发布"
        rows.append([
            a["name"],
            str(a["id"]),
            a["zhName"],
            release_text,
            status_text,
        ])

    result_table(
        "算法健康报告",
        ["算法名称", "ID", "中文名", "发布状态", "健康状态"],
        rows,
    )

    divider()
    info(f"共 {len(MOCK_ALGOS)} 个算法")
    info(f"已发布: {sum(1 for a in MOCK_ALGOS if a['isRelease'])} 个")
    info(f"需要关注: {len(ctx['warnings']) + len(ctx['errors'])} 个")


# ── Step 4: 操作选择 (choose) ─────────────────────────

def step_choose(ctx: dict):
    """演示: 单选列表"""
    console.print("[dim]演示: 选择列表[/dim]\n")

    action = choose(
        "选择后续操作",
        choices=[
            "批量修复算法 (体验运行中交互)",
            "导出报告为 CSV",
            "仅查看，不做操作",
        ]
    )
    ctx["action"] = action
    info(f"已选择: {action}")


# ── Step 5: 运行中交互 (后台任务 + 前台命令) ──────────

def step_long_running(ctx: dict):
    """演示: 长时间运行中，用户可以随时查询状态。"""
    if "修复" not in ctx.get("action", ""):
        return

    console.print("[dim]演示: 后台任务运行中，输入命令与任务交互[/dim]\n")

    # ── 共享状态 ──
    state = {
        "current": 0,
        "total": len(MOCK_ALGOS),
        "current_algo": "",
        "current_step": "",
        "results": [],          # (name, status, detail)
        "paused": False,
        "aborted": False,
        "done": False,
        "started_at": time.time(),
        "variables": {          # 模拟运行时可查询的变量
            "retry_count": 0,
            "upload_speed": "2.3 MB/s",
            "server_load": "67%",
            "batch_id": "B-20260709-001",
        },
    }
    lock = threading.Lock()

    # ── 后台任务 ──
    def background_task():
        for i, algo in enumerate(MOCK_ALGOS):
            with lock:
                if state["aborted"]:
                    break
                state["current"] = i + 1
                state["current_algo"] = algo["name"]
                state["current_step"] = "准备中"

            # 模拟多步骤处理
            for step_name, duration in [("取消发布", 0.4), ("上传", 0.8), ("编辑", 0.5), ("发布", 0.4)]:
                with lock:
                    if state["aborted"]:
                        break
                    state["current_step"] = step_name

                # 暂停等待
                while True:
                    with lock:
                        if not state["paused"] or state["aborted"]:
                            break
                    time.sleep(0.1)

                if state["aborted"]:
                    break

                time.sleep(duration)
                with lock:
                    # 模拟变量变化
                    state["variables"]["upload_speed"] = f"{random.uniform(1.5, 4.0):.1f} MB/s"
                    state["variables"]["server_load"] = f"{random.randint(40, 90)}%"

            with lock:
                ok = random.random() > 0.15  # 85% 成功率
                state["results"].append((algo["name"], "ok" if ok else "fail", algo["zhName"]))

        with lock:
            state["done"] = True

    # ── 命令处理 ──
    def handle_command(cmd: str) -> bool:
        """返回 True 表示继续，False 表示退出交互。"""
        cmd = cmd.strip().lower()

        if cmd == "status":
            with lock:
                elapsed = time.time() - state["started_at"]
                console.print(f"  [bold]进度:[/bold] {state['current']}/{state['total']}")
                console.print(f"  [bold]当前:[/bold] {state['current_algo']} ({state['current_step']})")
                console.print(f"  [bold]已用时:[/bold] {elapsed:.0f}s")
                ok = sum(1 for _, s, _ in state["results"] if s == "ok")
                fail = sum(1 for _, s, _ in state["results"] if s == "fail")
                console.print(f"  [bold]结果:[/bold] 成功 {ok}，失败 {fail}")
                if state["paused"]:
                    warn("  当前已暂停")
            return True

        elif cmd.startswith("info "):
            target = cmd[5:].strip()
            with lock:
                for r_name, r_status, r_detail in state["results"]:
                    if target in r_name:
                        s = "[green]成功[/green]" if r_status == "ok" else "[red]失败[/red]"
                        console.print(f"  {r_name} ({r_detail}): {s}")
                        return True
                # 查看变量
                if target in state["variables"]:
                    console.print(f"  {target} = {state['variables'][target]}")
                    return True
                warn(f"  未找到: {target}")
            return True

        elif cmd == "vars":
            with lock:
                console.print("  [bold]运行时变量:[/bold]")
                for k, v in state["variables"].items():
                    console.print(f"    {k} = {v}")
            return True

        elif cmd == "pause":
            with lock:
                state["paused"] = True
            warn("  已暂停（输入 resume 继续）")
            return True

        elif cmd == "resume":
            with lock:
                state["paused"] = False
            success("  已恢复")
            return True

        elif cmd == "abort":
            with lock:
                state["aborted"] = True
                state["paused"] = False
            error("  已中止")
            return False

        elif cmd == "help":
            console.print("  [bold]可用命令:[/bold]")
            console.print("    status    — 查看当前进度")
            console.print("    info <名> — 查看已完成算法详情")
            console.print("    vars      — 查看运行时变量")
            console.print("    pause     — 暂停任务")
            console.print("    resume    — 恢复任务")
            console.print("    abort     — 中止任务")
            console.print("    help      — 显示帮助")
            console.print("    (直接回车) — 等待任务完成")
            return True

        elif cmd == "":
            return False  # 回车 = 退出交互，等待任务结束

        else:
            warn(f"  未知命令: {cmd}（输入 help 查看帮助）")
            return True

    # ── 启动 ──
    info("任务将在后台运行，你可以随时输入命令与之交互")
    info("输入 help 查看可用命令，直接回车等待任务完成\n")

    task_thread = threading.Thread(target=background_task, daemon=True)
    task_thread.start()

    # 交互循环
    while True:
        with lock:
            if state["done"]:
                break

        try:
            cmd = input(">>> ")
        except EOFError:
            break

        if not handle_command(cmd):
            break

    # 等待任务结束
    task_thread.join(timeout=2)

    # ── 汇总报告 ──
    with lock:
        results = list(state["results"])
        aborted = state["aborted"]

    divider()
    if aborted:
        warn(f"任务已中止: 共处理 {len(results)}/{state['total']} 个")
    else:
        success(f"任务完成: 共处理 {len(results)} 个")

    ok = [(n, d) for n, s, d in results if s == "ok"]
    fail = [(n, d) for n, s, d in results if s == "fail"]

    if ok:
        success(f"成功 ({len(ok)}):")
        for n, d in ok:
            info(f"  ✓ {n} ({d})")
    if fail:
        error(f"失败 ({len(fail)}):")
        for n, d in fail:
            info(f"  ✗ {n} ({d})")

    ctx["batch_ok"] = len(ok)
    ctx["batch_fail"] = len(fail)


# ── Step 6: 日志折叠 (可展开/合上的日志面板) ───────────

LOG_TEMPLATES = [
    "[{time}] [INFO]  算法 {name} 开始处理...",
    "[{time}] [INFO]  {name} 正在上传 (1.2 MB)...",
    "[{time}] [DEBUG] HTTP POST /api/algorithm/edit → 200 OK ({elapsed}ms)",
    "[{time}] [INFO]  {name} 上传完成，服务端返回 id={id}",
    "[{time}] [INFO]  {name} 编辑算法信息...",
    "[{time}] [DEBUG] 请求体: {{\"sourcePath\": \"{name}\", \"type\": \"1-0\"}}",
    "[{time}] [INFO]  {name} 编辑完成",
    "[{time}] [INFO]  {name} 发布中...",
    "[{time}] [DEBUG] HTTP POST /api/algorithm/release → 200 OK ({elapsed}ms)",
    "[{time}] [INFO]  {name} 发布成功",
    "[{time}] [WARN]  {name} 服务端响应较慢，耗时 {elapsed}ms",
    "[{time}] [DEBUG] 连接池: active=3, idle=7, pending=0",
    "[{time}] [INFO]  心跳检测: 服务器正常",
    "[{time}] [DEBUG] 内存占用: 45.2 MB, 线程数: 4",
]


def step_collapsible_log(ctx: dict):
    """演示: 日志持续产生，Tab 展开/合上，不遮挡交互信息。"""
    console.print("[dim]演示: 日志折叠面板 — Tab 展开/合上，q 结束[/dim]\n")

    logs: list[str] = []
    max_visible = 15           # 展开时最多显示的日志条数
    expanded = False
    new_count = 0              # 合上期间新增的日志数
    running = True
    important_events: list[str] = []  # 重要事件始终显示
    lock = threading.Lock()

    # ── 后台日志产生线程 ──
    def log_producer():
        while running:
            time.sleep(random.uniform(0.3, 1.0))
            if not running:
                break
            tmpl = random.choice(LOG_TEMPLATES)
            algo = random.choice(MOCK_ALGOS)
            now = time.strftime("%H:%M:%S")
            line = tmpl.format(
                time=now,
                name=algo["name"].replace(".zip", ""),
                id=random.randint(1000, 9999),
                elapsed=random.randint(50, 800),
            )
            with lock:
                logs.append(line)
                if not expanded:
                    new_count_holder.__setitem__(0, new_count_holder[0] + 1)
                # 重要事件始终记录
                if "[WARN]" in line or "[ERROR]" in line:
                    important_events.append(line)
                    if len(important_events) > 5:
                        important_events.pop(0)

    new_count_holder = [0]  # mutable container for cross-thread

    # ── 渲染函数 ──
    def build_display() -> Table:
        table = Table(show_header=False, box=None, padding=0, expand=True)

        # 状态行
        with lock:
            total = len(logs)
            nc = new_count_holder[0]

        if expanded:
            status = f"[bold cyan]▼ 日志面板[/bold cyan]  ({total} 条)  [dim]Tab 合上 | q 结束[/dim]"
        else:
            badge = f"  [bold yellow]+{nc} 条新日志[/bold yellow]" if nc > 0 else ""
            status = f"[bold cyan]▶ 日志面板{badge}[/bold cyan]  [dim]Tab 展开 | q 结束[/dim]"

        table.add_row(status)

        # 展开时显示日志
        if expanded:
            with lock:
                visible = logs[-max_visible:]
            table.add_row("")  # 空行
            if len(logs) > max_visible:
                table.add_row(f"  [dim]... 省略 {len(logs) - max_visible} 条旧日志 ...[/dim]")
            for line in visible:
                # 给不同级别上色
                styled = line
                if "[ERROR]" in line:
                    styled = f"[red]{line}[/red]"
                elif "[WARN]" in line:
                    styled = f"[yellow]{line}[/yellow]"
                elif "[DEBUG]" in line:
                    styled = f"[dim]{line}[/dim]"
                table.add_row(f"  {styled}")

        # 重要事件始终显示（折叠时也可见）
        if not expanded:
            with lock:
                events = list(important_events)
            if events:
                table.add_row("")
                table.add_row("  [bold]最近重要事件:[/bold]")
                for ev in events[-3:]:
                    styled = ev
                    if "[ERROR]" in ev:
                        styled = f"[red]{ev}[/red]"
                    elif "[WARN]" in ev:
                        styled = f"[yellow]{ev}[/yellow]"
                    table.add_row(f"  {styled}")

        return table

    # ── 主循环: Live 渲染 + 按键检测 ──
    producer = threading.Thread(target=log_producer, daemon=True)
    producer.start()

    try:
        with Live(build_display(), console=console, refresh_per_second=8, transient=True) as live:
            while running:
                # 检测按键
                if msvcrt.kbhit():
                    key = msvcrt.getwch()
                    if key == "\t":  # Tab = 展开/合上
                        with lock:
                            expanded = not expanded
                            if expanded:
                                new_count_holder[0] = 0
                    elif key in ("q", "Q"):
                        running = False
                        break

                live.update(build_display())
                time.sleep(0.1)
    finally:
        running = False
        producer.join(timeout=1)

    # ── 结束汇总 ──
    with lock:
        total = len(logs)
        warns = sum(1 for l in logs if "[WARN]" in l)
        errors_count = sum(1 for l in logs if "[ERROR]" in l)

    divider()
    success(f"日志收集完成: 共 {total} 条")
    if warns:
        warn(f"其中 WARN: {warns} 条")
    if errors_count:
        error(f"其中 ERROR: {errors_count} 条")


# ── Step 7: 确认导出 (confirm) ────────────────────────

def step_confirm(ctx: dict):
    """演示: 确认对话框"""
    console.print("[dim]演示: 确认对话框[/dim]\n")

    if "修复" in ctx.get("action", ""):
        errors = ctx.get("errors", [])
        if not errors:
            warn("没有需要修复的算法")
            return

        info(f"将对以下算法执行重新发布:")
        for a in errors:
            info(f"  - {a['name']} ({a['zhName']})")
        divider()

        if not confirm("确认开始修复"):
            warn("已取消")
            return

        # 模拟执行
        for i, a in enumerate(errors, 1):
            console.print(f"\n[bold]({i}/{len(errors)})[/bold] {a['name']}")
            with spinner("  取消发布"):
                time.sleep(0.3)
            with spinner("  重新上传"):
                time.sleep(0.5)
            with spinner("  重新发布"):
                time.sleep(0.3)
            success(f"  {a['name']} 修复完成")

        divider()
        success(f"修复完成: {len(errors)} 个算法")

    elif "导出" in ctx.get("action", ""):
        path = ask_text("导出路径", default="report.csv")
        if confirm(f"确认导出到 {path}"):
            with spinner("导出中"):
                time.sleep(0.8)
            success(f"已导出: {path}")
        else:
            warn("已取消导出")

    else:
        info("仅查看模式，不做任何操作")


# ── 主入口 ────────────────────────────────────────────

def main():
    w = Wizard(
        "算法体检工具 (演示)",
        "交互演示 — 无需服务器，体验全部 CLI 交互方式",
    )
    w.add_step("连接配置 (text + password)", step_connect)
    w.add_step("数据分析 (spinner + warn/error)", step_analyze)
    w.add_step("报告展示 (table)", step_report)
    w.add_step("操作选择 (choose)", step_choose)
    w.add_step("运行中交互 (后台任务 + 前台命令)", step_long_running)
    w.add_step("日志折叠 (Tab 展开/合上)", step_collapsible_log)
    w.add_step("确认导出 (confirm)", step_confirm)
    w.run()


if __name__ == "__main__":
    main()
