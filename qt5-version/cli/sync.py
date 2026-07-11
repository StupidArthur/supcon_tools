"""
算法同步工具 — CLI 版

引导式流程：连接配置 → 扫描匹配 → 确认 → 执行同步
"""
import sys
import os

# 确保能导入 common 和 common.api
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.common import (
    Wizard, ask_text, confirm, spinner, result_table,
    info, success, error, warn, divider, console,
)
from common.api import AlgAPI


# ── Step 1: 连接配置 ─────────────────────────────────

def step_connect(ctx: dict):
    """收集连接信息并登录。"""
    ctx["url"] = ask_text("服务器地址", default="http://10.16.11.1:31501")
    ctx["username"] = ask_text("用户名", default="admin")
    ctx["password"] = ask_text("密码", password=True)

    # HTTPS 模式需要 tenant_id
    if ctx["url"].startswith("https://"):
        ctx["tenant_id"] = ask_text("Tenant ID (HTTPS 模式)")
    else:
        ctx["tenant_id"] = ""

    with spinner("正在登录"):
        api = AlgAPI(ctx["url"])
        api.login(ctx["username"], ctx["password"], ctx["tenant_id"])
        api.get_all_algorithms()
        ctx["api"] = api

    info(f"已缓存 {len(api.algorithms)} 个算法")


# ── Step 2: 扫描匹配 ─────────────────────────────────

def step_scan(ctx: dict):
    """扫描本地文件并匹配平台算法。"""
    ctx["dir_path"] = ask_text("算法目录", default="resource")

    with spinner("扫描本地文件并匹配平台算法"):
        matched = ctx["api"].match_local_files(ctx["dir_path"])

    found = [item for item in matched if item["isExist"]]
    not_found = [item for item in matched if not item["isExist"]]
    published = [item for item in found if item.get("isRelease") == 1]

    ctx["found"] = found
    ctx["published"] = published

    info(f"本地文件: {len(matched)} 个，命中平台: {len(found)} 个，未命中: {len(not_found)} 个")

    if not_found:
        warn("以下文件未在平台找到:")
        for item in not_found:
            info(f"  - {item['name']}")

    if not found:
        warn("无匹配的算法，流程结束")
        sys.exit(0)

    # 展示匹配结果表格
    rows = []
    for item in found:
        status = "已发布" if item.get("isRelease") == 1 else "未发布"
        rows.append([
            item["name"],
            str(item.get("id", "")),
            item.get("zhName", ""),
            status,
        ])
    result_table(
        "匹配结果",
        ["算法名称", "ID", "中文名", "状态"],
        rows,
        styles=["", "", "", "bold green"],
    )

    if published:
        divider()
        info(f"需取消发布后重新同步: {len(published)} 个")
        for item in published:
            info(f"  - {item['name']} (id={item['id']})")
        info("流程: 取消发布 → 上传 → 编辑 → 重新发布")


# ── Step 3: 确认并执行 ────────────────────────────────

def step_execute(ctx: dict):
    """确认后执行同步。"""
    found = ctx["found"]
    published = ctx["published"]

    if not confirm(f"确认开始同步 {len(found)} 个算法"):
        warn("已取消")
        sys.exit(0)

    api = ctx["api"]
    dir_path = ctx["dir_path"]
    published_ids = {item["id"] for item in published}
    total = len(found)

    divider()
    console.print(f"\n[bold]开始同步 {total} 个算法...[/bold]\n")

    for idx, item in enumerate(found, 1):
        name = item["name"]
        algo_id = item["id"]
        is_pub = algo_id in published_ids
        zh_name = item.get("zhName", "")

        console.print(f"[bold]({idx}/{total})[/bold] {name}  (id={algo_id}, {zh_name})")

        try:
            if is_pub:
                with spinner("  取消发布"):
                    api.release_algorithm(
                        algo_id=algo_id,
                        is_release=0,
                        cores=item["cores"],
                        resource_type=item["resourceType"],
                        num_replicas=item["numReplicas"],
                    )

            file_path = os.path.join(dir_path, name)
            with spinner("  上传文件"):
                api.upload_file(file_path)

            with spinner("  编辑算法"):
                api.edit_algorithm(source_path=name)

            if is_pub:
                with spinner("  重新发布"):
                    api.release_algorithm(
                        algo_id=algo_id,
                        is_release=1,
                        cores=item["cores"],
                        resource_type=item["resourceType"],
                        num_replicas=item["numReplicas"],
                    )

            success(f"  {name} 完成\n")

        except Exception as e:
            auth_hint = " (可能是登录过期)" if getattr(e, "is_auth_error", False) else ""
            error(f"  {name} 失败: {e}{auth_hint}")
            if not confirm("  是否继续处理剩余算法"):
                error("同步中止")
                sys.exit(1)

    divider()
    success(f"同步完成: 共处理 {total} 个算法，其中 {len(published)} 个重新发布")


# ── 主入口 ────────────────────────────────────────────

def main():
    w = Wizard(
        "算法同步工具 (CLI)",
        "同步本地算法文件与平台发布状态",
    )
    w.add_step("连接配置", step_connect)
    w.add_step("扫描匹配", step_scan)
    w.add_step("确认并执行", step_execute)
    w.run()


if __name__ == "__main__":
    main()
