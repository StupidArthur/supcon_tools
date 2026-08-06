#!/usr/bin/env python3
"""中控杯测试租户管理 GUI 工具。

从 config.yaml 加载 TPT 环境列表，提供评估配置查询/更新、成绩记录查询、
软测量评分查询、清空记录等功能。全局刷新按钮一键拉取所有数据。

评估配置为全局共享（不分租户），放在表格上方统一管理。
成绩记录和软测量评分跟随全局刷新自动更新，显示在表格中。

用法:
    python main.py [config.yaml]
"""

from __future__ import annotations

import os
import sys
from typing import Any

import yaml
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tpt_api import AlgAPI
from tpt_api import cubdata as cub

STATUS_MAP = {1: "评估中", 2: "评估完成", 3: "评估失败"}


def _find_config() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        local = os.path.join(exe_dir, "config.yaml")
        if os.path.exists(local):
            return local
        return os.path.join(sys._MEIPASS, "supcon_cup_2026", "cub_manager", "config.yaml")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def format_score_history(data: list | None) -> str:
    if not data:
        return "无记录"
    count = len(data)
    best = None
    for rec in data:
        if rec.get("isBest") and rec.get("score") is not None:
            best = rec["score"]
            break
    if best is not None:
        return f"{count}条 | 最优: {best}"
    evaluating = any(rec.get("status") == 1 for rec in data)
    if evaluating:
        return f"{count}条 | 评估中"
    failed = any(rec.get("status") == 3 for rec in data)
    if failed:
        return f"{count}条 | 有失败"
    return f"{count}条"


def format_soft_sensor_score(data: dict | None) -> str:
    if not data:
        return "未上传"
    score = data.get("score")
    if score is not None:
        return str(score)
    return "未评分"


class ApiWorker(QThread):
    """单次 API 调用的后台线程。"""

    finished = pyqtSignal(int, str, object)
    error = pyqtSignal(int, str, str)

    def __init__(self, row: int, action: str, env: dict, params: dict | None = None):
        super().__init__()
        self.row = row
        self.action = action
        self.env = env
        self.params = params or {}

    def run(self):
        try:
            api = AlgAPI(self.env["url"], timeout=60.0)
            api.login(self.env["username"], self.env["password"], self.env["tenant_id"])
            if self.action == "get_eval_config":
                result = cub.get_eval_config(api)
            elif self.action == "update_eval_config":
                result = cub.update_eval_config(api, **self.params)
            elif self.action == "get_score_history":
                result = cub.get_score_history(api)
            elif self.action == "get_soft_sensor_score":
                result = cub.get_soft_sensor_score(api)
            elif self.action == "clear_my_records":
                result = cub.clear_my_records(api)
            else:
                return
            self.finished.emit(self.row, self.action, result)
        except Exception as e:
            self.error.emit(self.row, self.action, str(e))


class ScoreHistoryDialog(QDialog):
    """成绩记录对话框。"""

    def __init__(self, name: str, data: list | None):
        super().__init__()
        self.setWindowTitle(f"成绩记录 - {name}")
        self.resize(960, 420)
        layout = QVBoxLayout(self)

        if not data:
            layout.addWidget(QLabel("暂无成绩记录"))
            return

        headers = ["状态", "评分", "类型", "工况开始", "工况结束",
                   "算法开始", "算法结束", "最优", "重试", "次数", "添加时间"]
        table = QTableWidget(len(data), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)

        for i, rec in enumerate(data):
            table.setItem(i, 0, QTableWidgetItem(STATUS_MAP.get(rec.get("status"), str(rec.get("status", "")))))
            table.setItem(i, 1, QTableWidgetItem(str(rec.get("score") or "")))
            table.setItem(i, 2, QTableWidgetItem(rec.get("algorithmType") or ""))
            table.setItem(i, 3, QTableWidgetItem(rec.get("startWorktime") or ""))
            table.setItem(i, 4, QTableWidgetItem(rec.get("endWorktime") or ""))
            table.setItem(i, 5, QTableWidgetItem(rec.get("algorithmStartTime") or ""))
            table.setItem(i, 6, QTableWidgetItem(rec.get("algorithmEndTime") or ""))
            table.setItem(i, 7, QTableWidgetItem("是" if rec.get("isBest") else "否"))
            table.setItem(i, 8, QTableWidgetItem(str(rec.get("retryCount") or 0)))
            table.setItem(i, 9, QTableWidgetItem(str(rec.get("count") or 0)))
            table.setItem(i, 10, QTableWidgetItem(rec.get("addTime") or ""))

        layout.addWidget(table)


class SoftSensorScoreDialog(QDialog):
    """软测量评分对话框。"""

    def __init__(self, name: str, data: dict | None):
        super().__init__()
        self.setWindowTitle(f"软测量评分 - {name}")
        self.resize(500, 250)
        layout = QFormLayout(self)

        if not data:
            layout.addRow(QLabel("暂无上传文件"))
            return

        layout.addRow("文件名:", QLabel(data.get("fileName") or ""))
        layout.addRow("上传时间:", QLabel(data.get("uploadTime") or ""))
        score = data.get("score")
        layout.addRow("评分:", QLabel(str(score) if score is not None else "未评分"))
        layout.addRow("文件路径:", QLabel(data.get("filePath") or ""))
        layout.addRow("用户ID:", QLabel(str(data.get("userId") or "")))


class MainWindow(QMainWindow):
    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.envs: list[dict] = []
        self.workers: list[ApiWorker] = []
        self.score_labels: list[QLabel] = []
        self.soft_labels: list[QLabel] = []
        self.eval_label: QLabel | None = None
        self.prac_spin: QSpinBox | None = None
        self.exam_spin: QSpinBox | None = None
        self.duration_spin: QSpinBox | None = None
        self.pending_count = 0
        self.pending_total = 0

        self.load_config()
        self.init_ui()

    def load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.envs = data.get("environments", [])

    def init_ui(self):
        self.setWindowTitle(f"中控杯测试租户管理 - {self.config_path}")
        self.resize(1000, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- 顶栏 ---
        top = QHBoxLayout()
        title = QLabel("中控杯测试租户管理")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        top.addWidget(title)
        top.addStretch()

        self.refresh_btn = QPushButton("全局刷新")
        self.refresh_btn.setFont(QFont("", 12))
        self.refresh_btn.setMinimumWidth(140)
        self.refresh_btn.clicked.connect(self.refresh_all)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        # --- 评估配置（全局）---
        eval_frame = QFrame()
        eval_frame.setFrameShape(QFrame.Shape.StyledPanel)
        eval_layout = QHBoxLayout(eval_frame)
        eval_layout.setContentsMargins(8, 4, 8, 4)

        eval_layout.addWidget(QLabel("评估配置（全局）:"))
        self.eval_label = QLabel("未查询")
        self.eval_label.setMinimumWidth(160)
        eval_layout.addWidget(self.eval_label)

        eval_query_btn = QPushButton("查询")
        eval_query_btn.clicked.connect(self.query_eval_config)
        eval_layout.addWidget(eval_query_btn)

        eval_layout.addSpacing(20)

        self.prac_spin = QSpinBox()
        self.prac_spin.setRange(0, 1)
        self.prac_spin.setValue(0)
        self.exam_spin = QSpinBox()
        self.exam_spin.setRange(0, 1)
        self.exam_spin.setValue(0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 999)
        self.duration_spin.setValue(120)
        eval_layout.addWidget(QLabel("练习"))
        eval_layout.addWidget(self.prac_spin)
        eval_layout.addWidget(QLabel("考试"))
        eval_layout.addWidget(self.exam_spin)
        eval_layout.addWidget(QLabel("时长"))
        eval_layout.addWidget(self.duration_spin)

        eval_update_btn = QPushButton("更新")
        eval_update_btn.clicked.connect(self.do_update_eval_config)
        eval_layout.addWidget(eval_update_btn)
        eval_layout.addStretch()

        layout.addWidget(eval_frame)

        # --- 表格 ---
        headers = ["URL", "账号", "密码", "成绩记录", "软测量评分", "操作"]
        self.table = QTableWidget(len(self.envs), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        widths = [250, 120, 100, 200, 120, 80]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)

        for row, env in enumerate(self.envs):
            self.setup_row(row, env)

        layout.addWidget(self.table)
        self.statusBar().showMessage("就绪")

    def setup_row(self, row: int, env: dict):
        self.table.setVerticalHeaderItem(row, QTableWidgetItem(env.get("name", f"row{row}")))

        # Col 0-2: URL / 账号 / 密码
        self.table.setItem(row, 0, QTableWidgetItem(env["url"]))
        self.table.setItem(row, 1, QTableWidgetItem(env["username"]))
        self.table.setItem(row, 2, QTableWidgetItem(env["password"]))

        # Col 3: 成绩记录（文本显示）
        w3 = QWidget()
        l3 = QHBoxLayout(w3)
        l3.setContentsMargins(4, 2, 4, 2)
        score_label = QLabel("未查询")
        l3.addWidget(score_label)
        detail_btn = QPushButton("详情")
        detail_btn.setFixedWidth(50)
        detail_btn.clicked.connect(lambda _, r=row, e=env: self.show_score_detail(r, e))
        l3.addWidget(detail_btn)
        l3.addStretch()
        self.table.setCellWidget(row, 3, w3)
        self.score_labels.append(score_label)

        # Col 4: 软测量评分（文本显示）
        w4 = QWidget()
        l4 = QHBoxLayout(w4)
        l4.setContentsMargins(4, 2, 4, 2)
        soft_label = QLabel("未查询")
        l4.addWidget(soft_label)
        detail_btn2 = QPushButton("详情")
        detail_btn2.setFixedWidth(50)
        detail_btn2.clicked.connect(lambda _, r=row, e=env: self.show_soft_detail(r, e))
        l4.addWidget(detail_btn2)
        l4.addStretch()
        self.table.setCellWidget(row, 4, w4)
        self.soft_labels.append(soft_label)

        # Col 5: 清空记录按钮
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda _, r=row, e=env: self.clear_records(r, e))
        self.table.setCellWidget(row, 5, clear_btn)

    # --- 后台任务管理 ---

    def create_worker(self, row: int, action: str, env: dict, params: dict | None = None):
        worker = ApiWorker(row, action, env, params)
        worker.finished.connect(self.on_worker_finished)
        worker.error.connect(self.on_worker_error)
        self.workers.append(worker)
        worker.start()

    def _decrement_pending(self):
        if self.pending_count > 0:
            self.pending_count -= 1
            done = self.pending_total - self.pending_count
            self.refresh_btn.setText(f"刷新中 ({done}/{self.pending_total})")
            if self.pending_count == 0:
                self.refresh_btn.setEnabled(True)
                self.refresh_btn.setText("全局刷新")
                self.statusBar().showMessage("全局刷新完成", 3000)

    # --- 全局刷新 ---

    def refresh_all(self):
        if self.pending_count > 0:
            return
        if not self.envs:
            return

        self.refresh_btn.setEnabled(False)
        # 1 eval config + N score history + N soft sensor score
        self.pending_total = 1 + 2 * len(self.envs)
        self.pending_count = self.pending_total
        self.refresh_btn.setText(f"刷新中 (0/{self.pending_total})")

        # 评估配置（全局，用第一个环境查询）
        self.eval_label.setText("查询中...")
        self.eval_label.setStyleSheet("")
        self.create_worker(0, "get_eval_config", self.envs[0])

        # 每行：成绩记录 + 软测量评分
        for row, env in enumerate(self.envs):
            self.score_labels[row].setText("查询中...")
            self.score_labels[row].setStyleSheet("")
            self.create_worker(row, "get_score_history", env)
            self.soft_labels[row].setText("查询中...")
            self.soft_labels[row].setStyleSheet("")
            self.create_worker(row, "get_soft_sensor_score", env)

    # --- 评估配置（全局）---

    def query_eval_config(self):
        if not self.envs:
            return
        self.eval_label.setText("查询中...")
        self.eval_label.setStyleSheet("")
        self.statusBar().showMessage("正在查询评估配置...")
        self.create_worker(0, "get_eval_config", self.envs[0])

    def do_update_eval_config(self):
        if not self.envs:
            return
        self.statusBar().showMessage("正在更新评估配置...")
        self.create_worker(0, "update_eval_config", self.envs[0], {
            "prac_load_enabled": self.prac_spin.value(),
            "exam_load_enabled": self.exam_spin.value(),
            "eval_duration_minutes": self.duration_spin.value(),
        })

    def _apply_eval_config(self, result: Any):
        if not isinstance(result, dict) or result.get("code") != 200:
            msg = result.get("message", str(result)) if isinstance(result, dict) else str(result)
            self.eval_label.setText(f"错误: {msg[:30]}")
            self.eval_label.setStyleSheet("color: red;")
            return
        cfg = result.get("data")
        if not cfg:
            self.eval_label.setText("无数据")
            return
        text = f"练习:{cfg.get('pracLoadEnabled', '?')} 考试:{cfg.get('examLoadEnabled', '?')} 时长:{cfg.get('evalDurationMinutes', '?')}"
        self.eval_label.setText(text)
        self.eval_label.setStyleSheet("")
        self.prac_spin.setValue(cfg.get("pracLoadEnabled", 0))
        self.exam_spin.setValue(cfg.get("examLoadEnabled", 0))
        self.duration_spin.setValue(cfg.get("evalDurationMinutes", 120))

    # --- 成绩记录 ---

    def show_score_detail(self, row: int, env: dict):
        label_text = self.score_labels[row].text()
        if label_text in ("未查询", "查询中..."):
            QMessageBox.information(self, "提示", "请先刷新数据")
            return
        self.statusBar().showMessage(f"正在查询 {env.get('name', '')} 的成绩记录...")
        self.create_worker(row, "get_score_history", env)

    def _apply_score_history(self, row: int, result: Any):
        if not isinstance(result, dict) or result.get("code") != 200:
            msg = result.get("message", str(result)) if isinstance(result, dict) else str(result)
            self.score_labels[row].setText(f"错误: {msg[:20]}")
            self.score_labels[row].setStyleSheet("color: red;")
            return
        data = result.get("data")
        self.score_labels[row].setText(format_score_history(data))
        self.score_labels[row].setStyleSheet("")
        self._cached_score_data = getattr(self, "_cached_score_data", {})
        self._cached_score_data[row] = data

    # --- 软测量评分 ---

    def show_soft_detail(self, row: int, env: dict):
        label_text = self.soft_labels[row].text()
        if label_text in ("未查询", "查询中..."):
            QMessageBox.information(self, "提示", "请先刷新数据")
            return
        self.statusBar().showMessage(f"正在查询 {env.get('name', '')} 的软测量评分...")
        self.create_worker(row, "get_soft_sensor_score", env)

    def _apply_soft_sensor_score(self, row: int, result: Any):
        if not isinstance(result, dict) or result.get("code") != 200:
            msg = result.get("message", str(result)) if isinstance(result, dict) else str(result)
            self.soft_labels[row].setText(f"错误: {msg[:20]}")
            self.soft_labels[row].setStyleSheet("color: red;")
            return
        data = result.get("data")
        self.soft_labels[row].setText(format_soft_sensor_score(data))
        self.soft_labels[row].setStyleSheet("")
        self._cached_soft_data = getattr(self, "_cached_soft_data", {})
        self._cached_soft_data[row] = data

    # --- 清空记录 ---

    def clear_records(self, row: int, env: dict):
        name = env.get("name", "")
        reply = QMessageBox.question(
            self, "确认清空", f"确定要清空 {name} 的成绩记录和上传文件吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.statusBar().showMessage(f"正在清空 {name} 的记录...")
        self.create_worker(row, "clear_my_records", env)

    # --- 回调 ---

    def on_worker_finished(self, row: int, action: str, result: Any):
        name = self.envs[row].get("name", "") if row < len(self.envs) else ""

        if action == "get_eval_config":
            self._apply_eval_config(result)
            self._decrement_pending()
            if self.pending_count == 0 and self.pending_total > 0:
                pass
            else:
                self.statusBar().showMessage("评估配置查询成功", 2000)

        elif action == "update_eval_config":
            self._apply_eval_config(result)
            self.statusBar().showMessage("评估配置更新成功", 3000)

        elif action == "get_score_history":
            self._apply_score_history(row, result)
            self._decrement_pending()
            # 如果是详情查询（非全局刷新），弹窗
            if self.pending_count == 0 and self.pending_total == 0:
                data = result.get("data") if isinstance(result, dict) else None
                dlg = ScoreHistoryDialog(name, data)
                dlg.exec()
                self.statusBar().showMessage("就绪")

        elif action == "get_soft_sensor_score":
            self._apply_soft_sensor_score(row, result)
            self._decrement_pending()
            if self.pending_count == 0 and self.pending_total == 0:
                data = result.get("data") if isinstance(result, dict) else None
                dlg = SoftSensorScoreDialog(name, data)
                dlg.exec()
                self.statusBar().showMessage("就绪")

        elif action == "clear_my_records":
            if isinstance(result, dict) and result.get("code") == 200 and result.get("data"):
                self.statusBar().showMessage(f"{name} 记录已清空", 3000)
                # 刷新该行
                self.score_labels[row].setText("查询中...")
                self.create_worker(row, "get_score_history", self.envs[row])
                self.soft_labels[row].setText("查询中...")
                self.create_worker(row, "get_soft_sensor_score", self.envs[row])
            else:
                msg = result.get("message", str(result)) if isinstance(result, dict) else str(result)
                QMessageBox.warning(self, "错误", f"{name} 清空失败: {msg}")

    def on_worker_error(self, row: int, action: str, error: str):
        name = self.envs[row].get("name", "") if row < len(self.envs) else ""

        if action == "get_eval_config":
            self.eval_label.setText(f"错误: {error[:30]}")
            self.eval_label.setStyleSheet("color: red;")
            self._decrement_pending()
        elif action == "get_score_history":
            self.score_labels[row].setText(f"错误: {error[:20]}")
            self.score_labels[row].setStyleSheet("color: red;")
            self._decrement_pending()
        elif action == "get_soft_sensor_score":
            self.soft_labels[row].setText(f"错误: {error[:20]}")
            self.soft_labels[row].setStyleSheet("color: red;")
            self._decrement_pending()
        else:
            QMessageBox.warning(self, "错误", f"{name} {action} 失败:\n{error}")

        self.statusBar().showMessage(f"{name} 操作失败: {error[:50]}", 5000)


def main():
    config_path = _find_config()
    if not os.path.exists(config_path):
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setFont(QFont("", 10))
    window = MainWindow(config_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
