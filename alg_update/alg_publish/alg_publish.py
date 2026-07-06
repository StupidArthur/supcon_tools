import sys
import os
import csv
import glob
import threading
import traceback
from datetime import datetime
from PyQt6 import QtWidgets, QtCore, QtGui

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.api import AlgAPI


class ConsoleEmitter(QtCore.QObject):
    signal = QtCore.pyqtSignal(str)


class PublishWindow(QtWidgets.QWidget):
    confirm_ready = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.api = None
        self.csv_path = ""
        self.csv_data = []
        self.console_emitter = ConsoleEmitter()
        self.init_ui()
        self.load_default_csv()

    def init_ui(self):
        self.setWindowTitle("算法发布工具 v1.2  |  designed by @yuzechao")
        self.setMinimumSize(700, 650)

        layout = QtWidgets.QVBoxLayout(self)

        # === CSV 文件选择区 ===
        group_csv = QtWidgets.QGroupBox("CSV 配置")
        csv_layout = QtWidgets.QHBoxLayout()

        self.csv_input = QtWidgets.QLineEdit()
        self.csv_input.setReadOnly(True)
        csv_layout.addWidget(self.csv_input)

        self.csv_browse_btn = QtWidgets.QPushButton("浏览")
        self.csv_browse_btn.clicked.connect(self.on_browse_csv)
        csv_layout.addWidget(self.csv_browse_btn)

        group_csv.setLayout(csv_layout)
        layout.addWidget(group_csv)

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

        connect_layout.addWidget(QtWidgets.QLabel("并发数:"), 4, 0)
        self.concurrent_input = QtWidgets.QLineEdit("3")
        connect_layout.addWidget(self.concurrent_input, 4, 1, 1, 2)

        group_connect.setLayout(connect_layout)
        layout.addWidget(group_connect)

        self._tenant_id_label = connect_layout.itemAtPosition(3, 0).widget()
        self._tenant_id_input = self.tenant_id_input
        self.url_input.textChanged.connect(self._on_url_changed)
        self._on_url_changed()

        # === 发布按钮 ===
        self.publish_btn = QtWidgets.QPushButton("开始发布")
        self.publish_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; font-weight: bold; }"
        )
        self.publish_btn.clicked.connect(self.on_publish)
        layout.addWidget(self.publish_btn)

        # === 控制台输出区 ===
        group_console = QtWidgets.QGroupBox("发布日志")
        console_layout = QtWidgets.QVBoxLayout()
        self.console = QtWidgets.QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QtGui.QFont("Consolas", 10))
        console_layout.addWidget(self.console)
        group_console.setLayout(console_layout)
        layout.addWidget(group_console)

        self.console_emitter.signal.connect(
            self.append_console, QtCore.Qt.ConnectionType.QueuedConnection)
        self.confirm_ready.connect(
            self._doShowConfirmDialog, QtCore.Qt.ConnectionType.QueuedConnection)

    def append_console(self, text: str):
        self.console.append(text)
        self.console.ensureCursorVisible()

    def log(self, text: str):
        self.console_emitter.signal.emit(text)

    def _on_url_changed(self):
        url = self.url_input.text().strip()
        is_https = url.startswith("https://")
        self._tenant_id_label.setVisible(is_https)
        self._tenant_id_input.setVisible(is_https)

    def load_default_csv(self):
        self.csv_path = self.find_latest_csv()
        if self.csv_path:
            self.csv_input.setText(self.csv_path)
            self.load_csv()
        else:
            self.csv_data = []

    def find_latest_csv(self) -> str:
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        pattern = os.path.join(base_dir, "publish_list_*.csv")
        files = glob.glob(pattern)
        if not files:
            return ""
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        return files[0]

    def on_browse_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 CSV 文件", "", "CSV 文件 (*.csv)")
        if path:
            self.csv_path = path
            self.csv_input.setText(path)
            self.load_csv()

    def load_csv(self):
        # 按优先级尝试常见中文编码：UTF-8 BOM / UTF-8 / GBK / GB18030
        # GB18030 是 GBK 超集，兼容所有 GBK/GB2312/GB18030 中文字符
        last_err = None
        for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
            try:
                with open(self.csv_path, "r", encoding=enc) as f:
                    reader = csv.DictReader(f)
                    self.csv_data = list(reader)
                self.log(f"[加载] CSV 已加载: {len(self.csv_data)} 条记录 (编码: {enc})")
                return
            except UnicodeDecodeError as e:
                last_err = e
                continue
            except Exception as e:
                self.log(f"[错误] CSV 加载失败: {e}")
                return
        self.log(f"[错误] CSV 加载失败: 无法识别文件编码（已尝试 utf-8-sig/utf-8/gbk/gb18030），最后错误: {last_err}")
        self.csv_data = []


    def on_publish(self):
        url = self.url_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        tenant_id = self.tenant_id_input.text().strip()
        csv_path = self.csv_input.text().strip()

        if not csv_path:
            self.log("[错误] 请先选择 CSV 文件")
            return
        if not url or not username or not password:
            self.log("[错误] 请填写完整的连接信息")
            return

        try:
            concurrent = int(self.concurrent_input.text().strip())
            if concurrent <= 0:
                raise ValueError
        except ValueError:
            self.log("[错误] 并发数必须为正整数")
            return

        self.publish_btn.setEnabled(False)
        self.log("=" * 60)
        self.log("开始发布任务")
        self.log("=" * 60)

        def do_publish():
            try:
                api = AlgAPI(url)
                api.login(username, password, tenant_id)
                api.get_all_algorithms()
                self.api = api
                self.log(f"[连接成功] 缓存 {len(api.algorithms)} 个算法")

                self._do_compare_and_confirm(api, concurrent)

            except Exception as e:
                auth_msg = "（可能是登录已过期，请重新登录）" if getattr(e, "is_auth_error", False) else ""
                self.log(f"[连接失败] {e} {auth_msg}")
                self._show_error_dialog(f"无法连接到服务器:\n{e}")
            finally:
                QtCore.QMetaObject.invokeMethod(
                    self.publish_btn, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True))

        threading.Thread(target=do_publish, daemon=True).start()

    def _do_compare_and_confirm(self, api: AlgAPI, concurrent: int):
        # 读取 CSV
        csv_records = self.csv_data

        # 用 zhName 构建平台算法映射（大小写不敏感）
        platform_map = {}
        for a in api.algorithms:
            zh_name = a.get("zhName", "")
            if zh_name:
                platform_map[zh_name.lower()] = a

        # 比对差异
        differences = []
        to_release = []
        already_released = []
        not_in_platform = []
        should_not_release_but_released = []

        for row in csv_records:
            alg_name = row.get("算法名称", "").strip()
            if not alg_name:
                continue
            lower_name = alg_name.lower()

            if lower_name not in platform_map:
                differences.append(f"  - {alg_name} (CSV 中存在，平台中未找到)")
                not_in_platform.append(alg_name)
                continue

            platform_algo = platform_map[lower_name]
            algo_id = platform_algo.get("id")
            is_release = platform_algo.get("isRelease", 0)
            csv_release = row.get("是否发布", "否").strip()

            # 检查平台已有信息
            platform_cores = platform_algo.get("cores", 1)
            platform_replicas = platform_algo.get("numReplicas", 1)
            csv_cores = row.get("核数", "").strip()
            csv_replicas = row.get("副本数", "").strip()
            csv_position = row.get("发布位置", "").strip()

            if csv_cores and float(csv_cores) != float(platform_cores):
                differences.append(
                    f"  - {alg_name}: 核数差异 (平台: {platform_cores}, CSV: {csv_cores})")
            if csv_replicas and int(csv_replicas) != int(platform_replicas):
                differences.append(
                    f"  - {alg_name}: 副本数差异 (平台: {platform_replicas}, CSV: {csv_replicas})")
            if csv_position:
                csv_mode = 2 if csv_position == "GPU" else 1
                platform_mode = platform_algo.get("resourceType", 1)
                if csv_mode != platform_mode:
                    differences.append(
                        f"  - {alg_name}: 发布位置差异 (平台: {'GPU' if platform_mode == 2 else 'CPU'}, CSV: {csv_position})")

            # 判断是否发布
            if csv_release != "是":
                # CSV 设置为不发布，检查平台当前状态
                if is_release == 1:
                    should_not_release_but_released.append(alg_name)
                continue

            if is_release == 1:
                already_released.append(alg_name)
            else:
                to_release.append({
                    "id": algo_id,
                    "name": alg_name,
                    "cores": float(csv_cores) if csv_cores else float(platform_cores),
                    "numReplicas": int(csv_replicas) if csv_replicas else int(platform_replicas),
                    "resourceType": 2 if csv_position == "GPU" else 1,
                })

        diff_text = "\n".join(differences) if differences else "  无"
        released_text = "\n".join([f"  - {n}" for n in already_released]) if already_released else "  无"
        pending_text = "\n".join([f"  - {n['name']}" for n in to_release]) if to_release else "  无"
        warn_text = "\n".join([f"  - {n}" for n in should_not_release_but_released]) if should_not_release_but_released else "  无"

        dialog_html = (
            f"<b>已发现差异:</b><br>"
            f"<pre style='color:{'#e74c3c' if differences else '#27ae60'}'>{diff_text}</pre>"
            f"<hr>"
            f"<b>发布统计:</b><br>"
            f"  已发布 (无需操作): {len(already_released)} 个<br>"
            f"  待发布: {len(to_release)} 个<br>"
            f"  CSV设置不发布但平台已发布: {len(should_not_release_but_released)} 个<br>"
            f"<hr>"
            f"<b>待发布列表:</b><br><pre>{pending_text}</pre>"
            f"<hr>"
            f"<b>已发布列表:</b><br><pre>{released_text}</pre>"
            f"<hr>"
            f"<b>CSV设置不发布但平台已发布（建议取消发布）:</b><br>"
            f"<pre style='color:#e74c3c'>{warn_text}</pre>"
            f"<hr>"
            f"<b>确认是否开始发布 ({len(to_release)} 个)？</b>"
        )

        self._pending_to_release = to_release
        self._pending_concurrent = concurrent
        self._pending_dialog_html = dialog_html
        self.confirm_ready.emit()

    def _doShowConfirmDialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("确认发布")
        dialog.setMinimumWidth(550)
        dialog.setMinimumHeight(450)

        layout = QtWidgets.QVBoxLayout(dialog)
        text_browser = QtWidgets.QTextBrowser()
        text_browser.setOpenExternalLinks(False)
        text_browser.setHtml(self._pending_dialog_html)
        layout.addWidget(text_browser, stretch=1)

        btn_box = QtWidgets.QDialogButtonBox()
        yes_btn = btn_box.addButton("确定", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        no_btn = btn_box.addButton("取消", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        btn_box.accepted.connect(lambda: (dialog.accept(), self._do_release()))
        btn_box.rejected.connect(lambda: (dialog.reject(), self._clear_pending()))
        layout.addWidget(btn_box)

        dialog.exec()

    def _clear_pending(self):
        self._pending_to_release = []
        self._pending_concurrent = 3
        self.log("[已取消发布]")

    def _show_error_dialog(self, msg: str):
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle("连接失败")
        msg_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        msg_box.setText(msg)
        msg_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def _do_release(self):
        to_release = getattr(self, "_pending_to_release", [])
        concurrent = getattr(self, "_pending_concurrent", 3)

        if not to_release:
            self.log("[提示] 没有需要发布的算法")
            return

        self.log(f"[发布] 开始发布 {len(to_release)} 个算法，并发数: {concurrent}")

        def do_release():
            try:
                self._batch_release(to_release, concurrent)
                self.log("[发布] 批次发布完成，等待最终校验...")

                # 重新获取算法列表进行校验
                self.log("[校验] 重新获取平台算法列表...")
                self.api.get_all_algorithms()

                still_pending = []
                for item in to_release:
                    algo = self.api.get_by_id(item["id"])
                    if algo and algo.get("isRelease") == 1:
                        self.log(f"  ✓ {item['name']} 已发布成功")
                    else:
                        self.log(f"  ✗ {item['name']} 发布失败或状态异常")
                        still_pending.append(item["name"])

                self.log("=" * 60)
                if still_pending:
                    self.log(f"[校验完成] {len(still_pending)} 个未发布成功:")
                    for name in still_pending:
                        self.log(f"  - {name}")
                else:
                    self.log("[校验完成] 全部发布成功")
                self.log("=" * 60)

            except Exception as e:
                self.log(f"[发布异常] {e}")
                self.log(traceback.format_exc())

        threading.Thread(target=do_release, daemon=True).start()

    def _batch_release(self, items: list, concurrent: int):
        total = len(items)
        for i in range(0, total, concurrent):
            batch = items[i:i + concurrent]
            batch_num = i // concurrent + 1
            batch_total = (total + concurrent - 1) // concurrent
            self.log(f"\n[批次 {batch_num}/{batch_total}] 正在发布: {[x['name'] for x in batch]}")

            threads = []
            results = [None] * len(batch)

            def release_one(index, item):
                try:
                    self.api.release_algorithm(
                        algo_id=item["id"],
                        is_release=1,
                        cores=int(item["cores"]),
                        resource_type=item["resourceType"],
                        num_replicas=item["numReplicas"],
                    )
                    results[index] = True
                    self.log(f"  ✓ {item['name']} 发布成功")
                except Exception as e:
                    results[index] = False
                    self.log(f"  ✗ {item['name']} 发布失败: {e}")

            for idx, item in enumerate(batch):
                t = threading.Thread(target=release_one, args=(idx, item))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            self.log(f"[批次 {batch_num}/{batch_total}] 完成")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = PublishWindow()
    w.show()
    sys.exit(app.exec())