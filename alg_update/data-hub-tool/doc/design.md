# 设计

## 1. 设计原则

1. **业务与 UI 分离**：业务逻辑（migrate 7 阶段）不知道 UI 长啥样，只调抽象接口
2. **格式转换纯数据化**：xlsx_io 只管读写，convert 只管数据，逻辑不混
3. **API 集中封装**：所有 HTTP 调用走 `common_api.py` 一个类
4. **CLI / GUI 同源**：同一份 `migrate()` 函数，UI 替换零代码
5. **单文件可打包**：用 PyInstaller 打成 57MB 单 EXE，目标机器无需 Python

## 2. 架构

### 2.1 分层

```
┌──────────────────────────────────────────────────────────┐
│  入口层                                                     │
│    ├── migrate_gui.py   (PyQt6 GUI, QThread worker)        │
│    └── CLI              (命令行, 环境变量)                  │
└──────────────────┬───────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────────┐
│  业务编排层 (migrate.py)                                   │
│    ├── class UI (ABC)        UI 抽象                        │
│    ├── class CliUI           命令行实现                     │
│    ├── class QtUI            PyQt6 实现                     │
│    └── def migrate()         7 阶段流水线                    │
│         ├─ extract_tag_names                               │
│         ├─ count_data_points                                │
│         ├─ check_all_tags                                  │
│         ├─ resolve_actions                                 │
│         ├─ convert + filter_wide                           │
│         ├─ do_import                                       │
│         └─ verify                                          │
└──────────────────┬───────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────────┐
│  通用层                                                    │
│    ├── xlsx_io.py      xlsx 读写抽象                       │
│    ├── convert.py      long → wide 格式转换                │
│    └── common_api.py   AlgAPI 客户端                       │
└──────────────────┬───────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────────┐
│  平台层 (HTTP)                                             │
│    POST /tpt-admin/.../umsAdmin/login                      │
│    POST /ibd-data-hub-web-v2.2/api/tag-info/add            │
│    POST /ibd-data-hub-web-v2.2/api/tag-info/page           │
│    POST /ibd-data-hub-web-v2.2/api/tag-value/importTagValue*│
│    POST /ibd-data-hub-web-v2.2/api/tag-value/getHistoryValueFromDB │
└──────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
源 xlsx (long 格式)                    目标平台
  │                                       ↑
  │ read_all_sheets()                      │
  │   dict[tagName, list[rows]]           │
  │       │                               │
  │       ├── count_data_points()         │
  │       │   dict[tagName, int]          │  ← 显示给用户
  │       │                               │
  │       └── convert_export_to_wide_input()
  │           dict{a1, headers, rows}     │
  │               │                       │
  │               │ (filter_wide, 跳过 skip 的 tag)
  │               ↓                       │
  │           write_wide_xlsx()            │
  │           (中间文件 *_for_import.xlsx) │
  │               │                       │
  │               └── import_tag_value_history()
  │                   HTTP POST + file     │
  │                                       │
  │               └── getHistoryValueFromDB()  ← 验证
  │                   拉回数据点           │
  │                   比对总数            │
```

## 3. 模块详解

### 3.1 `common_api.py`

**职责**：所有平台 HTTP 调用的封装

**核心类**：`AlgAPI`

**封装端点**（v0.9）：
- `login(username, password)` — 登录拿 token
- `add_tag(tag_name, data_type, ...)` — 注册位号（POST /api/tag-info/add）
- `list_tags(page, page_size, data)` — 查位号列表（POST /api/tag-info/page）
- `get_all_tags(page_size, data)` — 翻页拿所有（缓存到 self.tags / self.name_map）
- `get_tag_by_name(name)` — 缓存查单个
- `import_tag_value(data, ds_id)` — JSON 批量导入（≤10000 条/次）
- `import_tag_value_history(file_path, ...)` — Excel/ZIP 导入
- `import_csv_tag_value_history(file_path)` — CSV 导入（已废弃）
- `get_history_value(tag_names, beg_time, end_time, ...)` — 查历史值（POST /api/tag-value/getHistoryValueFromDB）
- `get_all_history(tag_names, beg_time, end_time, ...)` — 翻页拉所有历史值

**数据常量**：
```python
DATA_TYPES = {
    "BOOLEAN": 1, "S_BYTE": 2, "BYTE": 3, "SHORT": 4, "U_SHORT": 5,
    "INT": 6, "U_INT": 7, "LONG": 8, "U_LONG": 9,
    "FLOAT": 10, "DOUBLE": 11,
}
```

**私有方法**：
- `_request(method, path, body, params, wrap)` — 统一 HTTP 包装
- `_is_auth_error(data)` — 检测鉴权错误
- `_parse_resp(r)` — 统一响应解析

### 3.2 `xlsx_io.py`

**职责**：xlsx 读写的纯 I/O 抽象，**不关心数据语义**

**API**：
- `read_sheet(path, sheet_name) -> list[list]` — 读单个 sheet
- `read_all_sheets(path) -> dict[str, list[list]]` — 读全部 sheet
- `write_wide_xlsx(path, a1, headers, rows, sheet_name)` — 写 wide 格式

**设计原则**：返回值是 `dict` / `list`，不是 openpyxl 对象。调用方看不到 openpyxl。

### 3.3 `convert.py`

**职责**：平台导出格式 (long) → 平台导入格式 (wide) 的**纯数据**转换

**API**：
- `convert_export_to_wide_input(sheets) -> dict` — 主入口
- 内部辅助：
  - `_long_to_internal(sheets)` — long → 内部统一格式
  - `_internal_to_input(wide)` — 内部 → wide 输入格式
  - `_infer_frequency(times)` — 推断采样周期
  - `_parse_export_time(s)` / `_format_import_time(dt)` — 时间格式转换

**关键决策**：
- 时间格式：`yyyy-MM-dd HH:mm:ss`（导出） → `yyyy/MM/dd HH:mm:ss`（导入）
- A1 cron：固定用 `0/5 * * * * ?`（每 5 秒触发的活 cron，5 秒验证过能落库；占位 cron 不触发，PROGRESS.md 旧建议已证伪）
- 时间方向：保持原方向（V3 验证过倒序也能落地）

### 3.4 `migrate.py` (核心)

**职责**：迁移业务逻辑 + UI 抽象 + CliUI

**UI 抽象类**：
```python
class UI:
    def info(self, msg): ...
    def warn(self, msg): ...
    def error(self, msg): ...
    def section(self, title): ...
    def table(self, headers, rows): ...
    def confirm(self, msg, default=True) -> bool: ...
    def choice(self, msg, options, default=None) -> str: ...
    def progress_start(self, total, msg): ...
    def progress_update(self, current): ...
    def progress_end(self): ...
```

**CliUI** 实现：print + input

**业务函数**（无 UI 依赖）：
- `extract_tag_names(xlsx_path)` — 读 xlsx 提 tag 名
- `count_data_points(xlsx_path)` — 统计每 tag 点数
- `check_all_tags(target_api, tag_names, ui)` — 查 target 每 tag 状态
- `resolve_actions(checks, ui)` — 用户决策 has_data
- `convert_to_wide(xlsx_path)` — 转换
- `filter_wide(wide, keep_tags)` — 过滤 skip 的 tag
- `do_import(target_api, xlsx)` — 调导入 API
- `verify(target_api, tag_names, ui)` — 等异步 + 全量验证

**流水线**：`migrate(...)` 调上面这些，7 阶段流程。

**异常**：`MigrationCancelled` (用户取消)

### 3.5 `migrate_gui.py` (PyQt6)

**职责**：GUI 入口 + QtUI 实现 + 自定义对话框

**核心组件**：
- `MigrateWindow` — 主窗口（输入区、按钮、日志、进度条、footer）
- `MigrateWorker(QThread)` — 跑 `migrate()` 的后台线程
- `WorkerSignals` — 跨线程信号集
- `MainThreadProxy` — 跨线程同步弹窗代理（BlockingQueuedConnection）
- `ConfirmDialog` / `ChoiceDialog` — 自定义弹窗（绿/红按钮）
- `QtUI` — UI 抽象的 PyQt6 实现

**关键设计**：

#### 3.5.1 UI 抽象实现

```python
class QtUI(UI):
    def info(self, msg):
        self.sig.log.emit("info", msg)  # 跨线程, 非阻塞
    # ...
    
    def confirm(self, msg, default=True) -> bool:
        return QMetaObject.invokeMethod(
            self.proxy, "show_confirm",
            Qt.BlockingQueuedConnection,  # 阻塞 worker, 等用户点
            Q_ARG(str, msg), Q_ARG(bool, default),
        )
```

- 非阻塞方法（info/warn/error/section/table/progress）→ emit signal
- 阻塞方法（confirm/choice）→ BlockingQueuedConnection，等主线程弹窗返回

#### 3.5.2 自定义彩色按钮

```python
GREEN_BTN_STYLE = "background-color: #4CAF50; color: white; font-weight: bold; ..."
RED_BTN_STYLE = "background-color: #F44336; color: white; font-weight: bold; ..."

class ConfirmDialog(QDialog):
    # 是 (绿) / 否 (红) 按钮
class ChoiceDialog(QDialog):
    # 下拉 + 确定 (绿) / 取消 (红) 按钮
```

**不用 QMessageBox / QInputDialog** 的原因：要定制按钮颜色，必须用 QPushButton。

#### 3.5.3 7 阶段流水线映射

| 阶段 | UI 显示 | 用户操作 |
|---|---|---|
| 1/7 读源数据 | 日志 + 点数表 | 无 |
| 2/7 连接 | 日志 | 无 |
| 3/7 检查 | 日志 + 弹窗表格 | 关闭/不关 |
| 4/7 决策 | 日志 + 默认配置 | 弹窗（has_data 的 tag） |
| 5/7 计划 | 日志 + 弹窗表格 | 无（已去 confirm） |
| 6/7 执行 | 日志 + 进度条 | 无 |
| 7/7 验证 | 日志 + 每 tag 点数表 | 无 |

## 4. 关键设计决策

### 4.1 UI 抽象（最大决策）

**问题**：业务逻辑 7 阶段要展示信息、要询问用户，怎么写才能支持 CLI / GUI / 未来 TUI？

**方案**：定义 `UI` 抽象类，业务只调抽象方法：

```python
# 业务侧
ui.info("登录成功")
if not ui.confirm("执行?", default=True):
    raise MigrationCancelled()

# CLI 实现
class CliUI(UI):
    def info(self, msg): print(f"  {msg}")
    def confirm(self, msg, default=True): return input(...).lower() == 'y'

# GUI 实现
class QtUI(UI):
    def info(self, msg): self.sig.log.emit("info", msg)
    def confirm(self, msg, default=True):
        return QMetaObject.invokeMethod(..., BlockingQueuedConnection, ...)
```

**好处**：
- 业务零改动换 UI
- 加 TUI / Web UI 只需新写一个 UI 子类
- 单测容易（mock UI）

### 4.2 缺失 tag = 报错，不创建

**问题**：tag 在 target 不存在时怎么办？

**考虑过的方案**：
- A. 自动创建，用推断的 dataType
- B. 报错，让用户在平台 UI 手动建

**选 B 的理由**：
- dataType 推断不靠谱（从 tag 名后缀猜，容易错）
- 用户的典型路径是"tag 应该已存在"
- 让用户在平台 UI 手动建更安全（dataType 由用户确认）

### 4.3 活 cron（占位不行）

**问题**：A1 第 4 段 cron 怎么写？

**验证**：
- `0 0 0 1 1 ?`（每年 1/1，占位）：HTTP 200 但**不落地**
- `0/5 * * * * ?`（每 5 秒）：正常落地

**结论**：cron 必须用活的。`migrate.py` 固定写 `0/5 * * * * ?`。

### 4.4 verify 全查（不抽样）

**问题**：验证环节只查 1 个 tag 行不行？

**问题**（v0.9.1 修复前）：用户跑完 8 个 tag，验证只查 t_double_13，其他 7 个出问题也不知道。

**修复**：验证全部 tag，列出每个 tag 的数据点数。

### 4.5 时间格式横杠 vs 斜杠

**问题**：A 列时间用 `yyyy-MM-dd` 还是 `yyyy/MM/dd`？

**V1 验证**：
- `yyyy-MM-dd`（横杠）：HTTP 200 但**静默失败**，0 点落地
- `yyyy/MM/dd`（斜杠）：正常

**结论**：**只支持斜杠**。`convert.py` 强制 `-` → `/`。

## 5. 异常处理

| 异常 | 行为 |
|---|---|
| `FileNotFoundError` | xlsx 不存在，exit 2 |
| `MigrationCancelled` | 用户取消，exit 1 |
| `Exception` (其它) | 打印异常，exit 3 |
| HTTP 非 200 | `_request` 抛 `httpx.HTTPStatusError` |
| 业务 code 非 "00000" | `_request` 抛 `Exception` |
| 异步处理失败 | verify 报告，但**不**回滚已导入数据 |

## 6. 性能特征

| 操作 | 耗时 | 备注 |
|---|---|---|
| 登录 | < 1s | |
| 拉所有 tag | 2-3s | 100k tag 时 |
| 查 1 个 tag has_data | < 0.5s | |
| 检查 N 个 tag | 0.5 × N + 3s | |
| 读 xlsx (10k 行) | 1-2s | |
| 转换 | < 1s | |
| 写 xlsx | 1-2s | |
| 上传 (10k 点) | 2-5s | 异步 |
| 等异步 | 15s | 固定 |
| 验证 (10 tag) | 2-3s | |

**总耗时**：~30-40s / 10 tag / 10k 点

## 7. 安全 / 隐私

- Token 通过 `Authorization: Bearer` 头传，HTTPS 时加密（当前开发用 HTTP）
- Cookie `tpt-token` 也设了（兼容某些端点）
- 脚本中**绝不打印完整 token**，只显示长度
- 密码在 GUI 中是 `QLineEdit.EchoMode.Password`，密文显示
- 日志中**不打印** xlsx 文件内容（只打印 tag 名和点数）

## 8. 打包（PyInstaller）

```bash
pyinstaller --onefile --windowed --name hisdata-migrate-v0.9 --clean migrate_gui.py
```

- `--onefile`：单 EXE
- `--windowed`：无控制台（GUI 应用）
- `--name`：EXE 名字
- `--clean`：清旧 build

**输出**：`dist/hisdata-migrate-v0.9.exe`，约 57 MB

**注意事项**：
- 首次启动慢（1-3s）——EXE 解压到临时目录
- 杀毒软件可能误报（PyInstaller 常见问题）
- 跨机器直接拷，无需 Python
