import sys
import os
import csv
import threading
import traceback
from datetime import datetime
from urllib.parse import urlparse
from PyQt6 import QtWidgets, QtCore, QtGui
from api import AlgAPI


class ConsoleEmitter(QtCore.QObject):
    signal = QtCore.pyqtSignal(str)


class MainWindow(QtWidgets.QWidget):
    confirm_ready = QtCore.pyqtSignal()
    fail_ready = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.api = None
        self.pending_found = []
        self.pending_published = []
        self.pending_dir = ""
        self.pending_url = ""
        self._confirm_dialog = None
        self._fail_error_msg = ""
        self.console_emitter = ConsoleEmitter()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("算法同步工具 v1.3  |  designed by @yuzechao")
        self.setMinimumSize(700, 600)

        layout = QtWidgets.QVBoxLayout(self)

        # === 连接配置区 ===
        group_connect = QtWidgets.QGroupBox("连接配置")
        connect_layout = QtWidgets.QGridLayout()

        connect_layout.addWidget(QtWidgets.QLabel("URL:"), 0, 0)
        self.url_input = QtWidgets.QLineEdit("http://10.16.11.1:31501")
        connect_layout.addWidget(self.url_input, 0, 1, 1, 2)

        connect_layout.addWidget(QtWidgets.QLabel("Username:"), 1, 0)
        self.username_input = QtWidgets.QLineEdit("admin")
        connect_layout.addWidget(self.username_input, 1, 1, 1, 2)

        connect_layout.addWidget(QtWidgets.QLabel("Password:"), 2, 0)
        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        connect_layout.addWidget(self.password_input, 2, 1, 1, 2)

        group_connect.setLayout(connect_layout)
        layout.addWidget(group_connect)

        # === 更新配置区 ===
        group_update = QtWidgets.QGroupBox("更新配置")
        update_layout = QtWidgets.QGridLayout()

        update_layout.addWidget(QtWidgets.QLabel("算法目录:"), 0, 0)
        self.dir_input = QtWidgets.QLineEdit("resource")
        update_layout.addWidget(self.dir_input, 0, 1)
        self.browse_btn = QtWidgets.QPushButton("浏览")
        self.browse_btn.clicked.connect(self.on_browse)
        update_layout.addWidget(self.browse_btn, 0, 2)

        self.start_btn = QtWidgets.QPushButton("开始更新")
        self.start_btn.setStyleSheet("QPushButton { background-color: #e74c3c; color: white; font-weight: bold; }")
        self.start_btn.clicked.connect(self.on_start)

        self.export_btn = QtWidgets.QPushButton("导出算法信息")
        self.export_btn.setStyleSheet("QPushButton { background-color: #3498db; color: white; font-weight: bold; }")
        self.export_btn.clicked.connect(self.on_export)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.export_btn)
        update_layout.addLayout(btn_layout, 1, 0, 1, 3)

        group_update.setLayout(update_layout)
        layout.addWidget(group_update)

        # === 控制台输出区 ===
        group_console = QtWidgets.QGroupBox("控制台输出")
        console_layout = QtWidgets.QVBoxLayout()
        self.console = QtWidgets.QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QtGui.QFont("Consolas", 10))
        console_layout.addWidget(self.console)
        group_console.setLayout(console_layout)
        layout.addWidget(group_console)

        # 信号槽跨线程必须用 QueuedConnection
        self.console_emitter.signal.connect(
            self.append_console, QtCore.Qt.ConnectionType.QueuedConnection)
        self.confirm_ready.connect(
            self._doShowConfirmDialog, QtCore.Qt.ConnectionType.QueuedConnection)
        self.fail_ready.connect(
            self._doShowFailDialog, QtCore.Qt.ConnectionType.QueuedConnection)

    def append_console(self, text: str):
        self.console.append(text)
        self.console.ensureCursorVisible()

    def log(self, text: str):
        self.console_emitter.signal.emit(text)

    def on_browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择算法目录")
        if path:
            self.dir_input.setText(path)

    def on_start(self):
        url = self.url_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        dir_path = self.dir_input.text().strip()

        if not url or not username or not password:
            self.log("[错误] 请填写完整的连接信息")
            return
        if not dir_path:
            self.log("[错误] 请填写算法目录")
            return

        self.start_btn.setEnabled(False)
        self.log("=" * 60)
        self.log("同步本地算法文件与平台发布状态")
        self.log("=" * 60)
        self.log(f"[连接配置] URL={url}, username={username}")

        def do_connect():
            try:
                api = AlgAPI(url)
                api.login(username, password)
                api.get_all_algorithms()
                self.api = api
                self.log(f"[连接成功] 登录成功，缓存 {len(api.algorithms)} 个算法")

                matched = api.match_local_files(dir_path)
                found = [item for item in matched if item["isExist"]]
                published = [item for item in found if item["isRelease"] == 1]
                self.pending_found = found
                self.pending_published = published
                self.pending_dir = dir_path
                self.pending_url = url

                QtCore.QMetaObject.invokeMethod(
                    self.start_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True))
                self.log(f"[扫描完成] 命中平台 {len(found)} 个，需取消发布 {len(published)} 个")

                self.confirm_ready.emit()

            except Exception as e:
                self.log(f"[连接失败] {e}")
                QtCore.QMetaObject.invokeMethod(
                    self.start_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True))
                self._fail_error_msg = str(e)
                self.fail_ready.emit()

        threading.Thread(target=do_connect, daemon=True).start()

    def on_export(self):
        url = self.url_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not url or not username or not password:
            self.log("[错误] 请填写完整的连接信息")
            return

        parsed = urlparse(url)
        env_name = parsed.hostname or "unknown"

        default_filename = f"{env_name}_alg_info_{datetime.now().strftime('%Y%m%d')}.csv"
        default_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        default_path = os.path.join(default_dir, default_filename)

        save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出算法信息", default_path, "CSV 文件 (*.csv)"
        )
        if not save_path:
            return

        self.export_btn.setEnabled(False)
        self.start_btn.setEnabled(False)

        reuse = self.api and self.api.algorithms
        if reuse:
            self.log(f"[导出] 使用已缓存的 {len(self.api.algorithms)} 个算法数据")
        else:
            self.log(f"[导出] 开始连接平台获取算法信息...")

        def do_export():
            try:
                if reuse:
                    algorithms = self.api.algorithms
                else:
                    api = AlgAPI(url)
                    api.login(username, password)
                    api.get_all_algorithms()
                    algorithms = api.algorithms
                    self.api = api
                self.log(f"[导出] 获取到 {len(algorithms)} 个算法")

                if not algorithms:
                    self.log("[导出] 无算法数据，跳过导出")
                    return

                all_keys = []
                seen = set()
                for algo in algorithms:
                    for k in algo.keys():
                        if k not in seen:
                            all_keys.append(k)
                            seen.add(k)

                with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
                    writer.writeheader()
                    for algo in algorithms:
                        writer.writerow(algo)

                self.log(f"[导出] 成功导出 {len(algorithms)} 个算法到: {save_path}")

            except Exception as e:
                self.log(f"[导出失败] {e}")
                self.log(traceback.format_exc())
            finally:
                QtCore.QMetaObject.invokeMethod(
                    self.export_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True))
                QtCore.QMetaObject.invokeMethod(
                    self.start_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True))

        threading.Thread(target=do_export, daemon=True).start()

    def _doShowFailDialog(self):
        try:
            error_msg = getattr(self, '_fail_error_msg', '未知错误')
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("连接失败")
            msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            msg.setText(f"连接服务器失败，请检查网络或配置是否正确。\n\n错误信息: {error_msg}")
            msg.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            msg.exec()
        except Exception as e:
            self.log(f"[失败对话框异常] {e}")
            import traceback
            self.log(traceback.format_exc())

    def _doShowConfirmDialog(self):
        try:
            found = self.pending_found
            published = self.pending_published
            url = self.pending_url
            algo_list = "<br>".join([f"  - {item['name']}  id={item['id']}" for item in found]) if found else "  无"
            unpub_list = "<br>".join([f"  - {item['name']}  id={item['id']}" for item in published]) if published else "  无"

            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("确认更新")
            dialog.setMinimumWidth(500)
            dialog.setMinimumHeight(400)

            layout = QtWidgets.QVBoxLayout(dialog)

            text_browser = QtWidgets.QTextBrowser()
            text_browser.setOpenExternalLinks(False)
            text_browser.setHtml(
                f"<b>URL:</b> {url}<hr>"
                f"<b>命中平台的算法:</b> {len(found)} 个<br>"
                f"<b>其中需取消发布再更新的:</b> {len(published)} 个<hr>"
                f"<b>算法列表:</b><br>{algo_list}<hr>"
                f"<b>需取消发布的算法:</b><br>{unpub_list}<hr>"
                f"<b>每个算法将按序执行：</b><br>"
                f"取消发布 → 上传编辑 → 重新发布（已发布算法）<hr>"
                f"<b>确认是否开始更新？</b>"
            )
            layout.addWidget(text_browser, stretch=1)

            btn_box = QtWidgets.QDialogButtonBox()
            yes_btn = btn_box.addButton("确定", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
            no_btn = btn_box.addButton("取消", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
            btn_box.accepted.connect(lambda: (dialog.accept(), self.do_sync()))
            btn_box.rejected.connect(lambda: (dialog.reject(), self._clear_pending()))
            layout.addWidget(btn_box)

            self._confirm_dialog = dialog
            dialog.exec()
        except Exception as e:
            self.log(f"[对话框异常] {e}")
            import traceback
            self.log(traceback.format_exc())

    def _clear_pending(self):
        self.pending_found = []
        self.pending_published = []
        self.pending_dir = ""
        self.pending_url = ""
        self.log("[已取消]")

    def do_sync(self):
        dir_path = self.pending_dir
        found = self.pending_found
        published = self.pending_published

        self.start_btn.setEnabled(False)
        self.log("=" * 60)
        self.log("开始执行同步任务")
        self.log("=" * 60)

        def do_task():
            try:
                published_ids = {item["id"] for item in published}
                self.log(f"[同步开始] 共 {len(found)} 个算法待处理")
                for idx, item in enumerate(found, 1):
                    is_published = item["id"] in published_ids
                    file_path = f"{dir_path}/{item['name']}"
                    self.log(f"[{idx}/{len(found)}] 处理: {item['name']}  id={item['id']}  zhName={item.get('zhName')}")

                    if is_published:
                        self.log(f"    取消发布...")
                        self.api.release_algorithm(
                            algo_id=item["id"],
                            is_release=0,
                            cores=item["cores"],
                            resource_type=item["resourceType"],
                            num_replicas=item["numReplicas"],
                        )
                        self.log("    [取消发布 OK]")

                    self.log(f"    上传文件: {file_path}...")
                    upload_res = self.api.upload_file(file_path)
                    self.log(f"    [上传 OK] {upload_res.get('message', '')}")

                    self.log(f"    编辑算法...")
                    edit_res = self.api.edit_algorithm(source_path=item["name"])
                    self.log(f"    [编辑 OK] id={edit_res.get('id')}, zhName={edit_res.get('zhName')}, isRelease={edit_res.get('isRelease')}")

                    if is_published:
                        self.log(f"    重新发布...")
                        self.api.release_algorithm(
                            algo_id=item["id"],
                            is_release=1,
                            cores=item["cores"],
                            resource_type=item["resourceType"],
                            num_replicas=item["numReplicas"],
                        )
                        self.log("    [重新发布 OK]")

                    self.log(f"    完成\n")

                self.log("=" * 60)
                self.log("任务完成")
                self.log("=" * 60)
                self.log(f"  命中平台: {len(found)} 个")
                self.log(f"  已发布待处理: {len(published)} 个")

            except Exception as e:
                self.log(f"[任务异常] {e}")
                self.log(traceback.format_exc())
            finally:
                QtCore.QMetaObject.invokeMethod(
                    self.start_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True))

        threading.Thread(target=do_task, daemon=True).start()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())