#!/usr/bin/env python3
"""PyQt6 GUI for migrate.py — 分阶段面板版 (v0.91).

交互模型:
  - 顶部输入卡 (xlsx / URL / 用户 / 密码) + 开始/取消
  - 6 阶段横向 stepper (v0.91: 移除决策阶段)
  - 单一 OUTPUT textarea (v0.91: 替代过去的 QStackedWidget 多页 + 折叠 log_text)
  - 底部状态行 (v0.91: 替代过去的进度条)
  - QSettings 记忆上次 URL/用户/xlsx (不存密码)
  - 协作取消 (cancel_event)
  - 生产日志: exe 同级 logs/YYYY-MM-DD.log (log_config.py)

业务逻辑全在 migrate.py, 这里只做 PyQt6 包装. UI 抽象类 (migrate.UI)
被 QtUI 实现, migrate() 不知道上面跑的是 CLI 还是 GUI.
"""
import sys
import json
import threading
import logging

from PyQt6.QtCore import (QObject, QThread, pyqtSignal, pyqtSlot,
                           QMetaObject, Qt, Q_ARG, QSettings)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QTextEdit, QFileDialog, QMessageBox,
                             QFormLayout, QLabel, QFrame, QSizePolicy,
                             QGraphicsDropShadowEffect)
from PyQt6.QtGui import QFont, QColor

import log_config                                                      # noqa: F401  setup_logging 入口
from migrate import migrate, UI, MigrationCancelled, MissingTagsError

log = logging.getLogger(__name__)

__version__ = "0.91"
APP_NAME = "hisdata-migrate"
APP_AUTHOR = "designed by @yuzechao"

# ============================================================
# 配色 & 阶段定义
# ============================================================

C_PRIMARY = "#2563eb"
C_SUCCESS = "#16a34a"
C_DANGER = "#dc2626"
C_WARN = "#d97706"
C_BG = "#f1f5f9"
C_CARD = "#ffffff"
C_BORDER = "#e2e8f0"
C_TEXT = "#1e293b"
C_MUTED = "#64748b"

# stepper 短标签 (与 migrate.py 的 stage title 对应, v0.91 缩成 6 阶段)
STAGES = ["读源数据", "连接目标", "检查 tag", "最终计划", "执行迁移", "验证"]


# ============================================================
# 全局样式
# ============================================================

GLOBAL_QSS = f"""
QMainWindow, QDialog {{ background-color: {C_BG}; }}
QWidget {{ color: {C_TEXT}; font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 13px; }}

QFrame#Card {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
}}

QLabel#PageTitle {{ font-size: 17px; font-weight: 600; color: {C_TEXT}; }}
QLabel#PageHint  {{ color: {C_MUTED}; }}
QLabel#BigStatus {{ font-size: 22px; font-weight: 600; }}

QLineEdit {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 7px 9px;
    selection-background-color: {C_PRIMARY};
}}
QLineEdit:focus {{ border: 1px solid {C_PRIMARY}; }}

QPushButton#Primary {{
    background-color: {C_PRIMARY}; color: white; font-weight: 600;
    border: none; border-radius: 6px; padding: 8px 22px;
}}
QPushButton#Primary:hover  {{ background-color: #1d4ed8; }}
QPushButton#Primary:pressed {{ background-color: #1e40af; }}
QPushButton#Primary:disabled {{ background-color: #93c5fd; }}

QPushButton#Ghost {{
    background-color: transparent; color: {C_MUTED};
    border: 1px solid {C_BORDER}; border-radius: 6px; padding: 8px 18px;
}}
QPushButton#Ghost:hover {{ color: {C_TEXT}; border-color: #cbd5e1; }}
QPushButton#Ghost:disabled {{ color: #cbd5e1; }}

QToolButton {{ background: transparent; border: none; color: {C_MUTED}; }}
QToolButton:hover {{ color: {C_PRIMARY}; }}

QTableWidget {{
    background-color: {C_CARD}; border: 1px solid {C_BORDER};
    border-radius: 6px; gridline-color: {C_BORDER};
    selection-background-color: #dbeafe; selection-color: {C_TEXT};
}}
QTableWidget::item {{ padding: 6px 8px; }}
QHeaderView::section {{
    background-color: #f8fafc; color: {C_MUTED}; font-weight: 600;
    border: none; border-bottom: 1px solid {C_BORDER}; padding: 7px 8px;
}}
QProgressBar {{
    background-color: #e2e8f0; border: none; border-radius: 5px;
    height: 8px; text-align: center; color: {C_TEXT}; font-size: 11px;
}}
QProgressBar::chunk {{ background-color: {C_PRIMARY}; border-radius: 5px; }}

QPlainTextEdit, QTextEdit {{
    background-color: #0f172a; color: #e2e8f0; border: 1px solid {C_BORDER};
    border-radius: 6px; font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px;
}}
QComboBox {{
    background-color: {C_CARD}; border: 1px solid {C_BORDER};
    border-radius: 6px; padding: 5px 9px;
}}
QComboBox:hover {{ border-color: {C_PRIMARY}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background-color: {C_CARD}; border: 1px solid {C_BORDER};
    selection-background-color: #dbeafe; selection-color: {C_TEXT};
}}
"""

GREEN_BTN_QSS = f"""
QPushButton {{ background-color: {C_SUCCESS}; color: white; font-weight: 600;
    border: none; border-radius: 6px; padding: 8px 24px; }}
QPushButton:hover  {{ background-color: #15803d; }}
QPushButton:pressed {{ background-color: #166534; }}
"""
RED_BTN_QSS = f"""
QPushButton {{ background-color: {C_DANGER}; color: white; font-weight: 600;
    border: none; border-radius: 6px; padding: 8px 24px; }}
QPushButton:hover  {{ background-color: #b91c1c; }}
QPushButton:pressed {{ background-color: #991b1b; }}
"""


def _card(parent=None):
    """一个白底卡片 QFrame + 轻阴影."""
    f = QFrame(parent)
    f.setObjectName("Card")
    sh = QGraphicsDropShadowEffect(f)
    sh.setBlurRadius(18)
    sh.setOffset(0, 2)
    sh.setColor(QColor(15, 23, 42, 30))
    f.setGraphicsEffect(sh)
    return f


# ============================================================
# Worker 线程 → 主线程 的信号
# ============================================================

class WorkerSignals(QObject):
    log = pyqtSignal(str, str)             # level, msg
    stage = pyqtSignal(int, str)           # n, title
    table = pyqtSignal(str, list, list)    # kind, headers, rows
    progress = pyqtSignal(int, int, str)   # current, total, msg
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)
    missing_tags = pyqtSignal(list)        # [tagName, ...] — 专门的位号缺失弹窗


# ============================================================
# 主线程代理: 阻塞方法走这里 (BlockingQueuedConnection)
# ============================================================

class MainThreadProxy(QObject):
    """运行在主线程, 提供 worker 线程的阻塞调用."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window

    @pyqtSlot(str, bool, result=bool)
    def show_confirm(self, msg: str, default: bool) -> bool:
        from PyQt6.QtWidgets import QMessageBox as _MB
        return _MB.question(self.window, "确认", msg) == _MB.StandardButton.Yes

    @pyqtSlot(str, str, str, result=str)
    def show_choice(self, msg: str, options_json: str, default: str) -> str:
        # 兼容 UI.choice (pipeline 当前未用)
        return default


# ============================================================
# QtUI: 实现 migrate.UI 抽象
# ============================================================

class QtUI(UI):
    """PyQt6 实现. 业务逻辑 (migrate) 看不到 UI 实现, 调抽象方法即可."""

    def __init__(self, signals: WorkerSignals, proxy: MainThreadProxy):
        self.sig = signals
        self.proxy = proxy

    # ---- 非阻塞: emit signal ----
    def info(self, msg):  self.sig.log.emit("info", msg)
    def warn(self, msg):  self.sig.log.emit("warn", msg)
    def error(self, msg): self.sig.log.emit("error", msg)
    def stage(self, n, title): self.sig.stage.emit(n, title)
    def table(self, headers, rows, kind=None):
        self.sig.table.emit(kind or "", headers, rows)

    def progress_start(self, total, msg):
        self._p_total, self._p_msg = total, msg
        self.sig.progress.emit(0, total, msg)

    def progress_update(self, current):
        self.sig.progress.emit(current, self._p_total, self._p_msg)

    def progress_end(self):
        self.sig.progress.emit(self._p_total, self._p_total, "完成")

    # ---- 阻塞: 跨线程同步调用主线程 ----
    def confirm(self, msg, default=True):
        return QMetaObject.invokeMethod(
            self.proxy, "show_confirm",
            Qt.ConnectionType.BlockingQueuedConnection,
            Q_ARG(str, msg), Q_ARG(bool, default),
        )

    def choice(self, msg, options, default=None):
        return QMetaObject.invokeMethod(
            self.proxy, "show_choice",
            Qt.ConnectionType.BlockingQueuedConnection,
            Q_ARG(str, msg), Q_ARG(str, json.dumps(options, ensure_ascii=False)),
            Q_ARG(str, default or ""),
        )


# ============================================================
# Worker 线程
# ============================================================

class MigrateWorker(QThread):
    def __init__(self, xlsx, url, user, password, signals, proxy, cancel_event):
        super().__init__()
        self.xlsx, self.url, self.user, self.password = xlsx, url, user, password
        self.signals, self.proxy = signals, proxy
        self.cancel_event = cancel_event
        self.qt_ui = QtUI(signals, proxy)

    def run(self):
        log.info("Worker thread 启动 xlsx=%s url=%s user=%s", self.xlsx, self.url, self.user)
        try:
            result = migrate(
                source_xlsx=self.xlsx,
                target_url=self.url,
                target_user=self.user,
                target_password=self.password,
                ui=self.qt_ui,
                cancel_event=self.cancel_event,
            )
            log.info("Worker thread migrate() 返回: %s", result)
            self.signals.finished.emit(result)
        except MissingTagsError as e:
            log.warning("Worker thread: 缺位号 (%d 个)", len(e.tags))
            self.signals.missing_tags.emit(e.tags)         # 走专用弹窗
        except MigrationCancelled as e:
            log.warning("Worker thread: 已取消: %s", e)
            self.signals.failed.emit(f"已取消：{e}")
        except Exception as e:
            log.exception("Worker thread: 未捕获异常")
            self.signals.failed.emit(f"异常：{type(e).__name__}: {e}")
        finally:
            log_config.flush_all()


# ============================================================
# StageStepper: 横向 7 阶段指示器
# ============================================================

class StepItem(QPushButton):
    """单个阶段 pill: 序号圆 + 标签. 状态 pending/active/done/failed."""

    def __init__(self, n: int, label: str):
        super().__init__()
        self.n = n
        self.label = label
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(False)
        self.set_state("pending")

    def set_state(self, state: str):
        self.state = state
        # active 显示序号, done 显示 ✓, failed 显示 ✕, pending 显示序号
        if state == "done":
            mark = "✓"
        elif state == "failed":
            mark = "✕"
        else:
            mark = str(self.n)
        self.setText(f"  {mark}  {self.label}  ")
        # 直接在本 widget 上设属性, 不用嵌套 selector (selector 在部分 Qt 版本里不可靠)
        palette = {
            "pending": ("#ffffff", C_MUTED, C_BORDER, "normal"),
            "active":  (C_PRIMARY, "white",  C_PRIMARY, "600"),
            "done":    ("#f0fdf4", C_SUCCESS, C_SUCCESS, "600"),
            "failed":  (C_DANGER, "white",   C_DANGER,  "600"),
        }
        bg, fg, border, fw = palette[state]
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {border};"
            f" border-radius:16px; padding:6px 14px; font-weight:{fw};"
        )


class StageStepper(QWidget):
    clicked_stage = pyqtSignal(int)  # 点某个已完成阶段回看

    def __init__(self):
        super().__init__()
        self.items = []
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for i, label in enumerate(STAGES, 1):
            it = StepItem(i, label)
            it.clicked.connect(lambda _, n=i: self.clicked_stage.emit(n))
            self.items.append(it)
            h.addWidget(it)
            if i < len(STAGES):
                line = QFrame()
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                line.setStyleSheet(f"background:{C_BORDER};")
                h.addWidget(line)
        self._current = 0

    def set_active(self, n: int):
        """标记 1..n-1 为 done, n 为 active, 其余 pending."""
        self._current = n
        for it in self.items:
            if it.n < n:
                it.set_state("done")
            elif it.n == n:
                it.set_state("active")
            else:
                it.set_state("pending")

    def mark_all_done(self):
        for it in self.items:
            it.set_state("done")

    def mark_failed(self, n: int):
        if 1 <= n <= len(self.items):
            self.items[n - 1].set_state("failed")


# ============================================================
# 阶段页面 (QStackedWidget 的 7 页)
# ============================================================

def _ascii_table(headers: list[str], rows: list[list[str]]) -> str:
    """表格 → 等宽 ASCII, 喂给 OUTPUT textarea."""
    if not rows:
        return "  (无数据)"
    cols = len(headers)
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(str(row[i]) if i < len(row) else ""))
    sep = "  "
    fmt = sep.join(f"{{:<{w}}}" for w in widths)
    lines = []
    lines.append("  " + fmt.format(*[str(h) for h in headers]))
    lines.append("  " + sep.join("-" * w for w in widths))
    for row in rows:
        cells = [str(c) if c is not None else "" for c in row]
        # 截断超长单元格, 避免撑爆窗口
        cells = [c[:max(40, widths[i])] for i, c in enumerate(cells)]
        # 保证每行 cells 长度等于 cols
        cells = (cells + [""] * cols)[:cols]
        lines.append("  " + fmt.format(*cells))
    return "\n".join(lines)


# ============================================================
# 主窗口
# ============================================================

class MigrateWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1180, 900)                        # 默认更大, 防止输入框被压
        self.settings = QSettings("yuzechao", "hisdata-migrate")

        self.signals = WorkerSignals()
        self.proxy = MainThreadProxy(self, self)
        self.worker = None
        self.cancel_event = None
        self._cur_stage = 0

        self._build_ui()
        self._wire_signals()
        self._restore_inputs()

    # ---------- UI 构建 ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(14)

        # 输入卡
        incard = _card()
        flay = QFormLayout(incard)
        flay.setContentsMargins(18, 16, 18, 16)
        flay.setSpacing(10)
        flay.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        h1 = QHBoxLayout()
        self.xlsx_edit = QLineEdit(); self.xlsx_edit.setPlaceholderText("选择导出的 xlsx 文件")
        browse = QPushButton("浏览…"); browse.setObjectName("Ghost")
        browse.clicked.connect(self._on_browse)
        h1.addWidget(self.xlsx_edit, 1); h1.addWidget(browse)
        w1 = QWidget(); w1.setLayout(h1); flay.addRow("源 xlsx", w1)

        self.url_edit = QLineEdit(); self.url_edit.setPlaceholderText("http://target:31501")
        flay.addRow("目标 URL", self.url_edit)
        self.user_edit = QLineEdit(); flay.addRow("用户名", self.user_edit)
        self.pwd_edit = QLineEdit(); self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        flay.addRow("密码", self.pwd_edit)
        root.addWidget(incard)

        # 操作按钮
        btnrow = QHBoxLayout()
        self.run_btn = QPushButton("开始迁移"); self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._on_run)
        self.cancel_btn = QPushButton("取消"); self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setVisible(False)
        btnrow.addWidget(self.run_btn)
        btnrow.addWidget(self.cancel_btn)
        btnrow.addStretch()
        root.addLayout(btnrow)

        # stepper
        self.stepper = StageStepper()
        root.addWidget(self.stepper)

        # OUTPUT: 单一 textarea, 替代过去的 QStackedWidget 多页 + 折叠 log_text
        # 所有阶段 / 表格 / 日志 都打到这一个区域, 滚动看历史
        output_card = _card()
        out_lay = QVBoxLayout(output_card)
        out_lay.setContentsMargins(14, 12, 14, 12)
        out_lay.setSpacing(8)
        out_title = QLabel("OUTPUT")
        out_title.setObjectName("PageTitle")
        out_lay.addWidget(out_title)
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setMinimumHeight(450)
        # 等宽字体, ASCII 表对得齐
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.output_text.setFont(mono)
        self.output_text.setStyleSheet(
            f"QTextEdit {{ background:#0f172a; color:#e2e8f0;"
            f" border:1px solid {C_BORDER}; border-radius:6px;"
            f" padding:8px; }}"
        )
        out_lay.addWidget(self.output_text, 1)
        root.addWidget(output_card, 1)

        # 状态行 (替代进度条)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(f"color:{C_MUTED};")
        root.addWidget(self.status_label)

        # footer
        foot = QHBoxLayout(); foot.addStretch()
        fl = QLabel(f"v{__version__}  {APP_AUTHOR}")
        fl.setStyleSheet(f"color:#94a3b8; font-size:9pt;")
        foot.addWidget(fl); root.addLayout(foot)

    def _wire_signals(self):
        self.signals.log.connect(self._on_log)
        self.signals.stage.connect(self._on_stage)
        self.signals.table.connect(self._on_table)
        self.signals.progress.connect(self._on_progress)
        self.signals.finished.connect(self._on_finished)
        self.signals.failed.connect(self._on_failed)
        self.signals.missing_tags.connect(self._on_missing_tags)

    def _restore_inputs(self):
        self.xlsx_edit.setText(self.settings.value("xlsx", "", type=str))
        self.url_edit.setText(self.settings.value("url", "http://10.10.58.179:31501", type=str))
        self.user_edit.setText(self.settings.value("user", "admin", type=str))

    def _save_inputs(self):
        self.settings.setValue("xlsx", self.xlsx_edit.text().strip())
        self.settings.setValue("url", self.url_edit.text().strip())
        self.settings.setValue("user", self.user_edit.text().strip())

    # ---------- 输入 ----------
    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 xlsx", "", "Excel (*.xlsx *.xls)")
        if path:
            self.xlsx_edit.setText(path)

    # ---------- OUTPUT textarea 工具 ----------
    def _clear_output(self):
        self.output_text.clear()

    def _append_output(self, text: str, color: str = None):
        """写一行到 OUTPUT. color=None 用默认色."""
        if color is None:
            color = "#e2e8f0"           # 默认浅灰白
        self.output_text.append(f'<span style="color:{color}">{text}</span>')

    def _append_html(self, html: str):
        """直接写 HTML 片段 (用于彩色)."""
        self.output_text.append(html)

    def _scroll_output_bottom(self):
        sb = self.output_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------- 运行 / 取消 ----------
    def _on_run(self):
        xlsx = self.xlsx_edit.text().strip()
        url = self.url_edit.text().strip()
        user = self.user_edit.text().strip()
        pwd = self.pwd_edit.text()
        if not all([xlsx, url, user, pwd]):
            QMessageBox.warning(self, "缺少输入", "请填写所有字段。")
            return
        self._save_inputs()

        # 重置 UI
        self._clear_output()
        self.stepper.set_active(0)
        self._cur_stage = 0
        self._set_running(True)
        self.status_label.setText("迁移中…")
        self._append_output("▶ 开始迁移", color="#60a5fa")

        self.cancel_event = threading.Event()
        self.worker = MigrateWorker(xlsx, url, user, pwd, self.signals,
                                    self.proxy, self.cancel_event)
        self.worker.start()

    def _on_cancel(self):
        if self.cancel_event:
            self.cancel_event.set()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("正在取消…")

    def _set_running(self, running: bool):
        for w in [self.xlsx_edit, self.url_edit, self.user_edit, self.pwd_edit,
                  self.run_btn]:
            w.setEnabled(not running)
        self.cancel_btn.setVisible(running)
        self.cancel_btn.setEnabled(running)

    # ---------- 信号槽 ----------
    def _on_log(self, level, msg):
        colors = {"info": "#94a3b8", "warn": "#fbbf24", "error": "#f87171"}
        self._append_output(f"  [{level}] {msg}", colors.get(level, "#94a3b8"))
        self._scroll_output_bottom()

    def _on_stage(self, n, title):
        self._cur_stage = n
        self.stepper.set_active(n)
        self.status_label.setText(f"[{n}/6] {title}")
        sep = "═" * 64
        # 蓝绿渐变标识一下当前阶段
        self._append_output("")
        self._append_output(sep, color="#475569")
        self._append_output(f"  ▸ [{n}/6] {title}", color="#60a5fa")
        self._append_output(sep, color="#475569")
        self._scroll_output_bottom()

    def _on_table(self, kind, headers, rows):
        titles = {
            "points": "源 xlsx 位号与点数",
            "check":  "目标环境位号状态",
            "plan":   "最终导入计划",
            "verify": "验证结果",
        }
        summary = {
            "points": "",
            "check":  "",
            "plan":   "",
            "verify": "",
        }
        if kind == "points":
            total = sum(int(r[1]) for r in rows if str(r[1]).isdigit())
            summary["points"] = f"  → 共 {len(rows)} 个位号，{total} 个数据点。"
        elif kind == "plan":
            n_imp = sum(1 for r in rows if r[1] in ("导入", "覆盖导入"))
            n_skip = sum(1 for r in rows if r[1] == "跳过")
            summary["plan"] = f"  → 将导入 {n_imp} 个位号，跳过 {n_skip} 个。"
        elif kind == "verify":
            n_ok = sum(1 for r in rows if r[2] == "✅")
            summary["verify"] = f"  → {n_ok}/{len(rows)} 个位号有数据，验证通过。"

        self._append_output(f"  {titles.get(kind, kind)}:", color="#fbbf24")
        self._append_html("<pre style='color:#e2e8f0; margin:0;'>" +
                          _ascii_table(headers, rows).replace("\n", "<br>") +
                          "</pre>")
        if summary.get(kind):
            self._append_output(summary[kind], color="#86efac")
        self._scroll_output_bottom()

    def _on_progress(self, current, total, msg):
        # 阶段 3 的检查进度, 写到 OUTPUT
        if total > 0 and self._cur_stage == 3:
            pct = int(current * 100 / total)
            self._append_output(f"  {msg} {current}/{total} ({pct}%)", color="#94a3b8")
            self._scroll_output_bottom()

    def _on_finished(self, result):
        self.stepper.mark_all_done()
        n = result.get("imported", 0); s = result.get("skipped", 0)
        self.status_label.setText(f"完成: 导入 {n} 个，跳过 {s} 个")
        self._set_running(False)
        self._append_output("")
        self._append_output("✅ 迁移完成", color="#22c55e")
        self._append_output(f"  导入 {n} 个位号, 跳过 {s} 个", color="#86efac")
        self._scroll_output_bottom()
        # v0.91: 不再弹完成通知弹窗

    def _on_failed(self, msg):
        if self._cur_stage:
            self.stepper.mark_failed(self._cur_stage)
        self.status_label.setText("失败")
        self._set_running(False)
        self._append_output(f"  ✗ {msg}", color="#f87171")
        self._scroll_output_bottom()
        QMessageBox.critical(self, "失败", msg)

    def _on_missing_tags(self, tags: list):
        """位号缺失专用弹窗: 列出全部, 引导去平台 UI 手动建."""
        log.error("缺位号中止 (%d 个): %s", len(tags), tags)
        if self._cur_stage:
            self.stepper.mark_failed(self._cur_stage)
        self.status_label.setText(f"位号缺失 ({len(tags)} 个)")
        self._set_running(False)
        self._append_output("")
        self._append_output(f"⚠ 位号缺失, 中止 ({len(tags)} 个):", color="#fbbf24")
        for t in tags:
            self._append_output(f"    • {t}", color="#fbbf24")
        self._scroll_output_bottom()
        body = "目标环境缺少以下位号，无法继续迁移：\n\n" + \
               "\n".join(f"  • {t}" for t in tags) + \
               "\n\n请先在平台 UI 手动创建这些位号（注意 dataType 匹配），然后重跑迁移。"
        QMessageBox.warning(self, "位号缺失", body)


# ============================================================
# 入口
# ============================================================

def main():
    log_config.setup_logging()
    log.info("migrate_gui.py 启动 (pid=%d)", __import__("os").getpid())
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)
    window = MigrateWindow()
    window.show()
    log.info("QApplication 进入事件循环")
    try:
        sys.exit(app.exec())
    finally:
        log_config.flush_all()


if __name__ == "__main__":
    main()
