#!/usr/bin/env python3
"""环境间数据迁移工具: 从源导出 xlsx → 在目标环境导入.

设计 (v4):
  - 不依赖源环境 (只读 xlsx)
  - 7 阶段编排, 每阶段通过 UI 抽象层展示
  - target tag 应该已存在; 不存在 → 报错退出 (让用户手动建)
  - 已存在的 tag: 无数据 → 直接导入; 有数据 → 用户决策 (abort/overwrite/skip)
  - UI 是 swap-able 的 (现在 CliUI, 未来 GuiUI/TUI)

依赖:
  xlsx_io.py    - 读源 xlsx, 写 wide 格式
  convert.py    - 格式转换 (long → wide)
  common_api.py - AlgAPI 客户端 (login / list_tags / add_tag / get_history_value / import_tag_value_history)

用法:
  python migrate.py --xlsx export.xlsx --target-url http://new:31501 \\
                    --target-user admin --target-password yyy
"""
import os
import sys
import time
import threading
import argparse
import logging
from dataclasses import dataclass, field
from typing import Optional

import log_config                                  # noqa: F401  setup_logging 入口
from xlsx_io import read_all_sheets, write_wide_xlsx
from convert import convert_export_to_wide_input
from common_api import AlgAPI

log = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

DEFAULTS = {
    "dsId":       2,
    "groupId":    "0",
    "frequency":  10,
    "onlyRead":   False,
    "needPush":   True,
    "isVector":   True,
}

# dataType 选项 (供用户决策)
DATATYPE_OPTIONS = [
    ("1",  "BOOLEAN"),  ("2",  "S_BYTE"),  ("3",  "BYTE"),
    ("4",  "SHORT"),    ("5",  "U_SHORT"), ("6",  "INT"),
    ("7",  "U_INT"),    ("8",  "LONG"),    ("9",  "U_LONG"),
    ("10", "FLOAT"),    ("11", "DOUBLE"),
]

HAS_DATA_OPTIONS = [
    ("overwrite", "覆盖已有数据 (推荐)"),
    ("skip",      "跳过此 tag (不导入)"),
    ("abort",     "终止迁移"),
]


# ============================================================
# 异常
# ============================================================

class MigrationCancelled(Exception):
    """用户主动取消迁移 (Ctrl+C / confirm=False / EOF)."""


class MissingTagsError(MigrationCancelled):
    """目标环境缺位号, 必须中止迁移. 携带全部缺失列表, 弹窗要专门展示.

    继承 MigrationCancelled 是为了 CLI 退出码 1 的旧行为不变.
    """
    def __init__(self, tags: list[str]):
        self.tags = tags
        super().__init__(f"目标环境缺 {len(tags)} 个位号: {', '.join(tags)}")


# ============================================================
# 数据类
# ============================================================

@dataclass
class TagCheck:
    """单个 tag 在目标环境的检查结果 + 用户决策后的 action."""
    tagName: str
    exists: bool
    has_data: bool
    existing_dataType: Optional[int] = None  # target 查到的
    action: str = ""  # 用户填: "import" | "overwrite" | "skip" | "abort" | ""(待定)


# ============================================================
# UI 抽象 + CLI 实现
# ============================================================

class UI:
    """UI 抽象基类. 业务逻辑只看到这些方法. CLI/GUI/TUI 都能 swap."""

    def info(self, msg: str) -> None: ...
    def warn(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...
    def stage(self, n: int, title: str) -> None: ...
    def table(self, headers: list, rows: list, kind: str = None) -> None: ...
    def ask_decisions(self, checks: list) -> dict: ...
    def confirm(self, msg: str, default: bool = True) -> bool: ...
    def choice(self, msg: str, options: list, default: str = None) -> str: ...
    def progress_start(self, total: int, msg: str) -> None: ...
    def progress_update(self, current: int) -> None: ...
    def progress_end(self) -> None: ...


class CliUI(UI):
    """CLI 实现. 用 print + input."""

    def info(self, msg): print(f"  {msg}")
    def warn(self, msg): print(f"  ⚠ {msg}")
    def error(self, msg): print(f"  ✗ {msg}")

    def stage(self, n, title):
        print(f"\n{'=' * 60}\n  [{n}/7] {title}\n{'=' * 60}")

    def table(self, headers, rows, kind=None):
        if not rows:
            print("  (无数据)")
            return
        # 列宽
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))
        # 打印
        sep = "  "
        fmt = sep.join(f"{{:<{w}}}" for w in widths)
        print(sep + fmt.format(*[str(h) for h in headers]))
        print(sep + sep.join("-" * w for w in widths))
        for row in rows:
            print(sep + fmt.format(*[str(c) for c in row]))

    def ask_decisions(self, checks):
        """CLI: 逐个问 (与旧行为一致). 返回 {tagName: action}."""
        decisions = {}
        for c in checks:
            decisions[c.tagName] = self.choice(
                msg=f"'{c.tagName}' 已有数据, 怎么办?",
                options=HAS_DATA_OPTIONS,
                default="overwrite",
            )
        return decisions

    def confirm(self, msg, default=True):
        suffix = " [Y/n]" if default else " [y/N]"
        while True:
            try:
                ans = input(f"  {msg}{suffix}: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                raise MigrationCancelled("用户在 confirm 阶段取消")
            if not ans:
                return default
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no"):
                return False

    def choice(self, msg, options, default=None):
        print(f"  {msg}")
        for i, (val, label) in enumerate(options, 1):
            mark = " (默认)" if val == default else ""
            print(f"    {i}. {label}{mark}")
        while True:
            try:
                ans = input(f"  选择 [1-{len(options)}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                raise MigrationCancelled("用户在 choice 阶段取消")
            if not ans and default:
                return default
            try:
                idx = int(ans) - 1
                if 0 <= idx < len(options):
                    return options[idx][0]
            except ValueError:
                pass

    def progress_start(self, total, msg):
        self._p_total = total
        self._p_msg = msg
        print(f"  {msg} 0/{total}", end="", flush=True)

    def progress_update(self, current):
        print(f"\r  {self._p_msg} {current}/{self._p_total}", end="", flush=True)

    def progress_end(self):
        print()


# ============================================================
# 业务逻辑 (Core, 不依赖 UI)
# ============================================================

def extract_tag_names(xlsx_path: str) -> list[str]:
    """读 xlsx, 返回 sheet 名 (= tag 名) 排序列表."""
    sheets = read_all_sheets(xlsx_path)
    if not sheets:
        raise ValueError(f"xlsx 无 sheet: {xlsx_path}")
    return sorted(sheets.keys())


def count_data_points(xlsx_path: str) -> dict[str, int]:
    """从 xlsx 统计每个 tag (sheet) 的数据点数 (排除表头)."""
    sheets = read_all_sheets(xlsx_path)
    return {name: max(0, len(rows) - 1) for name, rows in sheets.items()}


def _extract_data_window(xlsx_path: str) -> tuple[str, str] | None:
    """从源 xlsx 提取数据窗口 [start, end]. 用于平台 API 查询,
    避免 1970-2099 宽范围导致 timeout (2026-07 用户反馈).

    返回 (beg, end) 字符串 'yyyy-MM-dd HH:mm:ss' (无微秒, 与平台 import 格式一致).
    """
    try:
        from convert import _long_to_internal, _parse_export_time, _format_import_time
        sheets = read_all_sheets(xlsx_path)
        wide = _long_to_internal(sheets)
        times = wide.get("times", [])
        if not times:
            return None
        # App Time 列倒序: times[0] 最新, times[-1] 最早
        # _format_import_time 输出 'yyyy/MM/dd HH:mm:ss', 平台 API 接受
        beg = _format_import_time(_parse_export_time(times[-1]))
        end = _format_import_time(_parse_export_time(times[0]))
        return (beg, end)
    except Exception as e:
        log.warning("提取数据窗口失败, 用默认宽范围: %s", e)
        return None


def check_all_tags(target_api: AlgAPI, tag_names: list[str], ui: UI,
                   xlsx_path: str = None,
                   cancel_event: threading.Event = None) -> list[TagCheck]:
    """批量 check, 带进度展示.

    一次性拉所有 tag 在本地建索引, 再逐个查 has_data. tagName 过滤
    在 API 端不灵 (实测 0 命中), 所以本地过滤.

    xlsx_path: 给定时, 用源数据窗口缩窄 has_data 查询范围, 避免 timeout.
    """
    def _cancelled():
        return cancel_event is not None and cancel_event.is_set()

    # 1. 一次性拉所有 tag, 建 name_map
    ui.info(f"  拉取 target 所有 tag 建索引 (data filter 不灵, 本地查) ...")
    all_tags = target_api.get_all_tags(page_size=2000)
    name_map = {t["tagName"]: t for t in all_tags if t.get("tagName")}
    ui.info(f"  target 共 {len(all_tags)} 个 tag")

    # 2. 对每个 tag_name 查 has_data
    window = _extract_data_window(xlsx_path) if xlsx_path else None
    if window:
        beg, end = window
        ui.info(f"  has_data 查询窗口: [{beg}, {end}]")
    else:
        beg, end = "1970-01-01 00:00:00", "2099-12-31 23:59:59"

    ui.progress_start(len(tag_names), "检查 tag")
    checks = []
    for i, name in enumerate(tag_names):
        if _cancelled():
            ui.progress_end()
            raise MigrationCancelled("用户取消")
        t = name_map.get(name)
        if t is None:
            checks.append(TagCheck(tagName=name, exists=False, has_data=False))
            ui.progress_update(i + 1)
            continue

        exists_dt = t.get("dataType")
        has_data = False
        try:
            result = target_api.get_history_value(
                tag_names=[name],
                beg_time=beg,
                end_time=end,
                number_to_string=False, page_size=1,
            )
            info = result.get(name, {})
            if info.get("total", 0) > 0:
                has_data = True
        except Exception as e:
            log.warning("get_history_value timeout/error for %s: %s", name, e)
            pass

        checks.append(TagCheck(
            tagName=name,
            exists=True,
            has_data=has_data,
            existing_dataType=exists_dt,
        ))
        ui.progress_update(i + 1)
    ui.progress_end()
    return checks


def display_defaults(ui: UI) -> None:
    """展示默认配置 (供 reference, 当前 v4 不直接用)."""
    ui.info("默认配置 (本次不会创建 tag, 仅供查看):")
    rows = [[k, str(v)] for k, v in DEFAULTS.items()]
    ui.table(["参数", "值"], rows)


def resolve_actions(checks: list[TagCheck], ui: UI) -> None:
    """v0.91: 无决策环节, has_data 的 tag 默认全部 overwrite. 缺位号 → 全部列出后中止.

    修改 checks[i].action. 缺位号时一次性收集所有, 抛 MissingTagsError,
    UI 层用专门的弹窗展示列表 (而不是只报第一个).
    """
    missing = [c for c in checks if not c.exists]
    if missing:
        for c in missing:
            ui.error(f"  缺位号: {c.tagName} (dataType={c.existing_dataType or '?'})")
        raise MissingTagsError([c.tagName for c in missing])

    for c in checks:
        if c.has_data:
            c.action = "overwrite"  # v0.91: 默认覆盖, 不再询问
            ui.info(f"  '{c.tagName}' 已有数据 → 默认覆盖导入")
        else:
            c.action = "import"


def filter_wide(wide: dict, keep_tags: list[str]) -> dict:
    """从 wide 数据过滤掉不在 keep_tags 的列."""
    tag_names = wide["tag_names"]
    keep_idx = [i for i, t in enumerate(tag_names) if t in keep_tags]
    return {
        **wide,
        "tag_names": [tag_names[i] for i in keep_idx],
        "values":    [[row[i] for i in keep_idx] for row in wide["values"]],
    }


def convert_to_wide(xlsx_path: str) -> dict:
    """读 xlsx, 调 convert 转 wide 格式数据."""
    sheets = read_all_sheets(xlsx_path)
    return convert_export_to_wide_input(sheets)


def do_import(target_api: AlgAPI, output_xlsx: str) -> dict:
    """调 importTagValueHistory 上传."""
    r = target_api.import_tag_value_history(output_xlsx)
    return {
        "is_success": r["is_success"],
        "code":       r["code"],
        "requestId":  r["raw"].get("requestId") if r["raw"] else None,
    }


def verify(target_api: AlgAPI, tag_names: list[str], ui: UI,
           wait: int = 15, cancel_event: threading.Event = None,
           time_range: tuple[str, str] = None) -> dict:
    """等异步, 验证全部 tag 的数据点 (不是只抽样).

    time_range: (beg_time, end_time), 默认 1970-2099. 实测宽范围在多 tag 时会
    超时 (2026-07 用户反馈), 业务侧应传实际导入窗口.
    """
    if not tag_names:
        return {"checked": 0, "passed": True}
    ui.info(f"等异步处理 {wait}s ...")
    # 拆成 0.5s 步进, 期间可被取消
    for _ in range(wait * 2):
        if cancel_event is not None and cancel_event.is_set():
            raise MigrationCancelled("用户取消")
        time.sleep(0.5)
    beg, end = time_range if time_range else ("1970-01-01 00:00:00", "2099-12-31 23:59:59")
    log.info("verify: query %d tags in [%s, %s]", len(tag_names), beg, end)
    try:
        result = target_api.get_history_value(
            tag_names=list(tag_names),
            beg_time=beg,
            end_time=end,
            number_to_string=False, page_size=1,
        )
        # 逐 tag 验证
        results = []
        all_passed = True
        for tag in tag_names:
            info = result.get(tag, {})
            total = info.get("total", 0)
            passed = total > 0
            results.append({"tag": tag, "total": total, "passed": passed})
            if not passed:
                all_passed = False
        return {"checked": len(tag_names), "results": results, "passed": all_passed}
    except Exception as e:
        return {"error": str(e), "passed": False}


# ============================================================
# Pipeline (编排)
# ============================================================

def migrate(
    source_xlsx: str,
    target_url: str, target_user: str, target_password: str,
    ui: UI,
    verify_wait: int = 15,
    cancel_event: threading.Event = None,
) -> dict:
    """完整迁移流程 (6 阶段, v0.91 起无决策环节)."""
    def _cancelled():
        return cancel_event is not None and cancel_event.is_set()

    log.info(
        "迁移开始 xlsx=%s url=%s user=%s verify_wait=%ds",
        source_xlsx, target_url, target_user, verify_wait,
    )

    # 1. 读 xlsx
    ui.stage(1, "读源数据")
    log.info("[stage 1] 开始: 读源数据 xlsx=%s", source_xlsx)
    if _cancelled():
        raise MigrationCancelled("用户取消")
    if not os.path.exists(source_xlsx):
        log.error("xlsx 不存在: %s", source_xlsx)
        ui.error(f"xlsx 不存在: {source_xlsx}")
        raise FileNotFoundError(source_xlsx)
    tag_names = extract_tag_names(source_xlsx)
    counts = count_data_points(source_xlsx)
    total_points = sum(counts.values())
    log.info("[stage 1] 完成: %d tags, %d total points", len(tag_names), total_points)
    ui.info(f"从 {source_xlsx} 读出 {len(tag_names)} 个 tag, 总计 {total_points} 个数据点")
    ui.table(["Tag", "数据点数"], [[name, counts.get(name, 0)] for name in tag_names], kind="points")

    # 2. 登录 target
    ui.stage(2, "连接目标环境")
    log.info("[stage 2] 开始: 登录 %s", target_url)
    if _cancelled():
        raise MigrationCancelled("用户取消")
    try:
        target_api = AlgAPI(target_url)
        target_api.login(target_user, target_password, "")
        log.info("[stage 2] 完成: 登录成功, token 长度=%d", len(target_api.token or ""))
    except Exception as e:
        log.exception("[stage 2] 登录失败")
        ui.error(f"登录失败: {e}")
        raise
    ui.info(f"已登录 {target_url}")

    # 3. 检查 target
    ui.stage(3, "检查目标环境 tag 状态")
    log.info("[stage 3] 开始: 检查 %d tags", len(tag_names))
    if _cancelled():
        raise MigrationCancelled("用户取消")
    checks = check_all_tags(target_api, tag_names, ui,
                            xlsx_path=source_xlsx, cancel_event=cancel_event)
    n_has_data = sum(1 for c in checks if c.has_data)
    n_missing = sum(1 for c in checks if not c.exists)
    log.info(
        "[stage 3] 完成: %d tags, has_data=%d, missing=%d",
        len(checks), n_has_data, n_missing,
    )
    rows = []
    for c in checks:
        rows.append([
            c.tagName,
            "✅" if c.exists else "❌",
            "已有数据" if c.has_data else "当前没有数据",
            c.existing_dataType if c.existing_dataType is not None else "-",
            c.action or "-",
        ])
    ui.table(["Tag", "存在", "数据状态", "dataType", "动作"], rows, kind="check")

    # 4. 展示最终计划 (has_data 默认 overwrite, 不存在 → 报错)
    ui.stage(4, "最终计划")
    log.info("[stage 4] 开始: 决策 + 计划")
    if _cancelled():
        raise MigrationCancelled("用户取消")
    resolve_actions(checks, ui)
    plan_rows = []
    n_import = n_skip = 0
    for c in checks:
        if c.action in ("import", "overwrite"):
            label = "导入" if c.action == "import" else "覆盖导入"
            plan_rows.append([c.tagName, label])
            n_import += 1
        elif c.action == "skip":
            plan_rows.append([c.tagName, "跳过"])
            n_skip += 1
    ui.table(["Tag", "动作"], plan_rows, kind="plan")
    log.info("[stage 4] 完成: import=%d, skip=%d", n_import, n_skip)
    ui.info(f"将导入 {n_import} 个 tag, 跳过 {n_skip} 个")
    if n_import == 0:
        log.warning("没有 tag 要导入, 退出")
        ui.warn("没有 tag 要导入, 退出")
        return {"imported": 0, "skipped": n_skip}

    # 5. 转换 + 导入
    ui.stage(5, "执行迁移")
    log.info("[stage 5] 开始: 转换 + 上传, %d tags", n_import)
    if _cancelled():
        raise MigrationCancelled("用户取消")
    imported_tags = [c.tagName for c in checks if c.action in ("import", "overwrite")]
    skipped_tags = [c.tagName for c in checks if c.action == "skip"]

    ui.info("转换 xlsx (long → wide) ...")
    wide = convert_to_wide(source_xlsx)
    if skipped_tags:
        wide = filter_wide(wide, imported_tags)
        ui.info(f"过滤掉 skip 的 {len(skipped_tags)} 个 tag: {skipped_tags}")
    output_xlsx = source_xlsx.rsplit(".", 1)[0] + "_for_import.xlsx"
    write_wide_xlsx(output_xlsx, a1=wide["a1"], headers=wide["headers"], rows=wide["rows"])
    ui.info(f"写到 {output_xlsx}: {len(wide['rows'])} 行 × {len(wide['headers']) + 1} 列")

    ui.info(f"上传到 {target_url} ...")
    log.info("[stage 5] 上传文件: %s (%d 行)", output_xlsx, len(wide["rows"]))
    import_result = do_import(target_api, output_xlsx)
    log.info(
        "[stage 5] 上传响应: is_success=%s code=%s requestId=%s",
        import_result["is_success"], import_result["code"], import_result["requestId"],
    )
    ui.info(f"  is_success={import_result['is_success']} code={import_result['code']} requestId={import_result['requestId']}")
    if not import_result["is_success"]:
        log.error("[stage 5] 上传失败, 终止 (不验证)")
        ui.error("导入失败, 不验证")
        return {"imported": 0, "skipped": n_skip, "import_result": import_result}

    # 6. 验证
    ui.stage(6, "验证")
    log.info("[stage 6] 开始: 验证, 等异步 %ds", verify_wait)
    if _cancelled():
        raise MigrationCancelled("用户取消")
    # 用实际导入窗口替代 1970-2099, 避免 29 tags 宽范围查询 timeout
    data_window = _extract_data_window(source_xlsx)
    verify_result = verify(
        target_api, imported_tags, ui,
        wait=verify_wait, cancel_event=cancel_event,
        time_range=data_window,
    )
    if verify_result.get("passed"):
        n_ok = sum(1 for r in verify_result.get("results", []) if r.get("passed"))
        n_total = verify_result.get("checked", 0)
        log.info("[stage 6] 完成: %d/%d tags 验证通过", n_ok, n_total)
        ui.info(f"✅ 验证通过 ({n_ok}/{n_total} 个 tag 有数据)")
        # 列出每个 tag 的点数
        rows = [[r["tag"], r["total"], "✅" if r.get("passed") else "❌"]
                for r in verify_result.get("results", [])]
        if rows:
            ui.table(["Tag", "数据点数", "通过"], rows, kind="verify")
    else:
        log.error("[stage 6] 验证异常: %s", verify_result.get("error", verify_result))
        ui.warn(f"⚠ 验证异常: {verify_result}")

    return {
        "imported":     n_import,
        "skipped":      n_skip,
        "import_result": import_result,
        "verify":        verify_result,
    }


# ============================================================
# CLI 入口
# ============================================================

def main():
    log_config.setup_logging()
    log.info("migrate.py CLI 启动 (pid=%d)", os.getpid())

    parser = argparse.ArgumentParser(
        description="环境间数据迁移工具 (源 xlsx → 目标环境)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python migrate.py --xlsx export.xlsx \\
                   --target-url http://new-env:31501 \\
                   --target-user admin \\
                   --target-password yyy
        """,
    )
    parser.add_argument("--xlsx", required=True, help="源数据 xlsx (平台导出格式)")
    parser.add_argument("--target-url", required=True, help="目标环境 URL")
    parser.add_argument("--target-user", required=True)
    parser.add_argument("--target-password", required=True)
    parser.add_argument("--verify-wait", type=int, default=15, help="验证前等异步的秒数")
    args = parser.parse_args()
    # 密码不写日志, 仅记其他参数
    log.info(
        "args: xlsx=%s url=%s user=%s verify_wait=%ds",
        args.xlsx, args.target_url, args.target_user, args.verify_wait,
    )

    ui = CliUI()

    try:
        result = migrate(
            source_xlsx=args.xlsx,
            target_url=args.target_url,
            target_user=args.target_user,
            target_password=args.target_password,
            ui=ui,
            verify_wait=args.verify_wait,
        )
        log.info(
            "完成: 导入 %d, 跳过 %d, 退出码 0",
            result.get("imported", 0), result.get("skipped", 0),
        )
        ui.info(f"✅ 完成: 导入 {result.get('imported', 0)} 个 tag, 跳过 {result.get('skipped', 0)} 个")
    except MissingTagsError as e:
        log.error("缺位号中止 (%d 个): %s", len(e.tags), e.tags)
        ui.warn(f"已取消: {e}")
        log_config.flush_all()
        sys.exit(1)
    except MigrationCancelled as e:
        log.warning("用户取消: %s", e)
        ui.warn(f"已取消: {e}")
        log_config.flush_all()
        sys.exit(1)
    except FileNotFoundError as e:
        log.error("xlsx 文件不存在: %s", e)
        ui.error(f"文件不存在: {e}")
        log_config.flush_all()
        sys.exit(2)
    except Exception as e:
        log.exception("未捕获异常")
        ui.error(f"异常: {type(e).__name__}: {e}")
        log_config.flush_all()
        sys.exit(3)
    finally:
        log_config.flush_all()


if __name__ == "__main__":
    main()
