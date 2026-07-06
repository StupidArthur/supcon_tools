import sys
import os
import threading
import time
import traceback

from PyQt6 import QtWidgets, QtCore, QtGui
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)
from api import AlgAPI


class ConsoleEmitter(QtCore.QObject):
    signal = QtCore.pyqtSignal(str)


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.api = None
        self.published_algos = []
        self.console_emitter = ConsoleEmitter()
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("算法重发布工具 v1.2  |  designed by @yuzechao")
        self.setMinimumSize(700, 650)

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

        connect_layout.addWidget(QtWidgets.QLabel("Tenant ID:"), 3, 0)
        self.tenant_id_input = QtWidgets.QLineEdit()
        self.tenant_id_input.setPlaceholderText("HTTPS模式租户ID，HTTP模式可不填")
        connect_layout.addWidget(self.tenant_id_input, 3, 1, 1, 2)

        group_connect.setLayout(connect_layout)
        layout.addWidget(group_connect)

        self._tenant_id_label = connect_layout.itemAtPosition(3, 0).widget()
        self._tenant_id_input = self.tenant_id_input
        self.url_input.textChanged.connect(self._on_url_changed)
        self._on_url_changed()

        # === 操作按钮区 ===
        btn_layout = QtWidgets.QHBoxLayout()

        self.view_btn = QtWidgets.QPushButton("查看已发布算法")
        self.view_btn.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; font-weight: bold; }"
        )
        self.view_btn.clicked.connect(self.on_view)
        btn_layout.addWidget(self.view_btn)

        self.exec_btn = QtWidgets.QPushButton("执行发布流程")
        self.exec_btn.setEnabled(False)
        self.exec_btn.setStyleSheet(
            "QPushButton { background-color: #e74c3c; color: white; font-weight: bold; }"
        )
        self.exec_btn.clicked.connect(self.on_exec)
        btn_layout.addWidget(self.exec_btn)

        layout.addLayout(btn_layout)

        # === 已发布算法展示区 ===
        group_list = QtWidgets.QGroupBox("已发布算法列表")
        list_layout = QtWidgets.QVBoxLayout()
        self.algo_list_widget = QtWidgets.QTextEdit()
        self.algo_list_widget.setReadOnly(True)
        self.algo_list_widget.setFont(QtGui.QFont("Consolas", 10))
        list_layout.addWidget(self.algo_list_widget)
        group_list.setLayout(list_layout)
        layout.addWidget(group_list)

        # === 日志输出区 ===
        group_log = QtWidgets.QGroupBox("操作日志")
        log_layout = QtWidgets.QVBoxLayout()
        self.log_console = QtWidgets.QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFont(QtGui.QFont("Consolas", 10))
        log_layout.addWidget(self.log_console)
        group_log.setLayout(log_layout)
        layout.addWidget(group_log)

        self.console_emitter.signal.connect(
            self._append_log, QtCore.Qt.ConnectionType.QueuedConnection)

    def _append_log(self, text: str):
        self.log_console.append(text)
        self.log_console.ensureCursorVisible()

    def _log(self, text: str):
        self.console_emitter.signal.emit(text)

    def _on_url_changed(self):
        url = self.url_input.text().strip()
        is_https = url.startswith("https://")
        self._tenant_id_label.setVisible(is_https)
        self._tenant_id_input.setVisible(is_https)

    def on_view(self):
        url = self.url_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        tenant_id = self.tenant_id_input.text().strip()

        if not url or not username or not password:
            self._log("[错误] 请填写完整的连接信息")
            return

        self.view_btn.setEnabled(False)
        self.exec_btn.setEnabled(False)
        self.algo_list_widget.clear()
        self._log("=" * 60)
        self._log("正在连接平台并获取算法列表...")
        self._log("=" * 60)

        def do_fetch():
            try:
                api = AlgAPI(url)
                api.login(username, password, tenant_id)
                api.get_all_algorithms()
                self.api = api

                released = [a for a in api.algorithms if a.get("isRelease") == 1]
                self.published_algos = released

                self._log(f"[成功] 共获取 {len(api.algorithms)} 个算法，其中已发布 {len(released)} 个")

                # 展示列表
                lines = []
                for a in released:
                    name = a.get("zhName", "") or a.get("name", "")
                    alg_id = a.get("id", "")
                    resource_type = a.get("resourceType", 1)
                    cpu_gpu = "GPU" if resource_type == 2 else "CPU"
                    cores = a.get("cores", 1)
                    replicas = a.get("numReplicas", 1)
                    lines.append(
                        f"  {name}  |  id={alg_id}  |  {cpu_gpu}  |  核数={cores}  |  副本={replicas}"
                    )

                QtCore.QMetaObject.invokeMethod(
                    self.algo_list_widget, "setPlainText", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, "\n".join(lines) if lines else "  无已发布的算法"))

                if released:
                    self._log("[提示] 点击「执行发布流程」开始逐个重新发布")
                    QtCore.QMetaObject.invokeMethod(
                        self.exec_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(bool, True))
                else:
                    self._log("[提示] 没有已发布的算法，无需处理")

            except Exception as e:
                auth_msg = "（可能是登录已过期，请重新登录）" if getattr(e, "is_auth_error", False) else ""
                self._log(f"[错误] {e} {auth_msg}")
            finally:
                QtCore.QMetaObject.invokeMethod(
                    self.view_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True))

        threading.Thread(target=do_fetch, daemon=True).start()

    def on_exec(self):
        if not self.published_algos:
            self._log("[错误] 没有已发布的算法可处理")
            return

        self.exec_btn.setEnabled(False)
        self.view_btn.setEnabled(False)
        self._log("=" * 60)
        self._log("开始执行发布流程")
        self._log("=" * 60)

        def do_task():
            total = len(self.published_algos)
            for idx, algo in enumerate(self.published_algos, 1):
                name = algo.get("zhName", "") or algo.get("name", "")
                alg_id = algo.get("id")
                cores = int(algo.get("cores", 1))
                resource_type = algo.get("resourceType", 1)
                replicas = algo.get("numReplicas", 1)
                cpu_gpu = "GPU" if resource_type == 2 else "CPU"

                self._log(f"\n[{idx}/{total}] ========== 开始处理: {name} ==========")
                self._log(f"  id={alg_id}  {cpu_gpu}  核数={cores}  副本={replicas}")

                # 取消发布
                self._log(f"  >> 取消发布...")
                try:
                    self.api.release_algorithm(
                        algo_id=alg_id,
                        is_release=0,
                        cores=cores,
                        resource_type=resource_type,
                        num_replicas=replicas,
                    )
                    self._log(f"  << 取消发布成功")
                except Exception as e:
                    auth_msg = "（可能是登录已过期，请重新登录）" if getattr(e, "is_auth_error", False) else ""
                    self._log(f"  << 取消发布失败: {e} {auth_msg}")
                    continue

                # 等待 1 秒
                self._log(f"  >> 等待 1 秒...")
                time.sleep(1)
                self._log(f"  << 等待结束")

                # 重新发布
                self._log(f"  >> 重新发布...")
                try:
                    self.api.release_algorithm(
                        algo_id=alg_id,
                        is_release=1,
                        cores=cores,
                        resource_type=resource_type,
                        num_replicas=replicas,
                    )
                    self._log(f"  << 重新发布成功")
                except Exception as e:
                    auth_msg = "（可能是登录已过期，请重新登录）" if getattr(e, "is_auth_error", False) else ""
                    self._log(f"  << 重新发布失败: {e} {auth_msg}")

                self._log(f"[{idx}/{total}] ========== 处理结束 ==========")

            self._log("\n" + "=" * 60)
            self._log("全部处理完成")
            self._log("=" * 60)

            QtCore.QMetaObject.invokeMethod(
                self.exec_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, True))
            QtCore.QMetaObject.invokeMethod(
                self.view_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, True))

        threading.Thread(target=do_task, daemon=True).start()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
