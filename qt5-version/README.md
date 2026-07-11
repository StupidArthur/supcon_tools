# 算法管理工具集

> ## ⚠️ 本目录是 PyQt5 低系统版本分支
>
> 原版（`../alg_update/`）基于 **PyQt6 6.11 / Qt 6.11**，在 Windows Server 2016 1607 等老系统上会报 `DLL load failed while importing QtWidgets`——Qt6 最低要求 Win10 1809（内核 17763），1607 内核 14393 不达标。Wails 版 `alg_toolbox` 用 WebView2，同样要 1809+，也救不了 1607。
>
> 本分支改用 **PyQt5 5.15.11 / Qt 5.15.2**（支持 Win7+），用于老系统兼容。功能与原版一致，仅 GUI 栈不同。
>
> **与原版的差异**：
> - 4 个工具去掉版本号、统一加 `_低系统版本` 后缀（exe 文件名 + 窗口标题都改）
> - 打包改用本目录 `venv/`（原版用系统 Python）
> - 代码迁移点：`from PyQt6`→`from PyQt5`、枚举去中间命名空间（`QLineEdit.EchoMode.Password`→`QLineEdit.Password`、`Qt.ConnectionType.QueuedConnection`→`Qt.QueuedConnection`、`QMessageBox.Icon.Warning`→`QMessageBox.Warning`、`StandardButton.Ok`→`Ok`、`ButtonRole.AcceptRole/RejectRole`→`AcceptRole/RejectRole`）、`app.exec()`→`app.exec_()`；`pyqtSignal`/`QMetaObject.invokeMethod`/`Q_ARG` 不变
> - `alg_republish_tool.spec` 入口已修正为 `alg_republish/ui.py`（原版 spec 误指根 `ui.py`=alg_sync v1.3 旧版，本分支已修，原版未动）
>
> | 工具 | exe |
> |---|---|
> | 同步 | `算法同步工具_低系统版本.exe` |
> | 发布 | `算法发布工具_低系统版本.exe` |
> | 不编辑同步 | `算法同步工具_不编辑_低系统版本.exe` |
> | 重发布 | `算法重发布工具_低系统版本.exe` |
>
> **打包**：
> ```bash
> venv\Scripts\python.exe -m PyInstaller <spec> --distpath dist --workpath build --clean -y
> ```
> 产物在 `dist/`。
>
> 以下章节继承自原版 PyQt6 文档（描述 PyQt6），本分支差异以上方为准；`user_guide.md` 同理。

本目录包含一组算法管理工具，基于 PyQt6 GUI + httpx API 通信。

---

## 环境说明

- **Python**: 3.11+（系统默认 Python）
- **虚拟环境**: `venv/`（尚未用于打包，推荐后续迁移）
- **核心依赖**: `httpx`（HTTP 客户端）、`PyQt6`（GUI 框架）

打包及开发均使用系统 Python，当前系统 Python 路径：`D:\Python311`

---

## 目录结构

```
alg_update/
├── venv/                        # Python 虚拟环境（推荐用于开发和打包）
├── common/
│   └── api.py                   # 共享 API 封装（AlgAPI 类），被各工具复用
├── alg_sync/                    # 算法同步工具（alg_sync_tool）
│   ├── ui.py                   # PyQt6 主界面
│   ├── task.py                 # 同步任务逻辑（无 GUI 版本）
│   └── alg_sync_tool.spec      # PyInstaller 打包配置
├── alg_publish/                 # 算法发布工具（alg_publish_tool）
│   ├── alg_publish.py           # PyQt6 主界面
│   └── alg_publish_tool.spec    # PyInstaller 打包配置
├── alg_republish/               # 算法重发布工具（alg_republish_tool）
│   ├── ui.py                   # PyQt6 主界面
│   ├── api.py                 # 从 common/api.py 复制，解除跨目录依赖
│   └── alg_republish_tool.spec # PyInstaller 打包配置
├── dist/                        # 打包输出目录
│   ├── alg_sync_tool.exe
│   ├── alg_publish_tool.exe
│   └── alg_republish_tool.exe
└── build/                       # PyInstaller 临时构建目录
```

---

## 工具说明

### 1. 算法同步工具（alg_sync_tool）
- **功能**：将本地 `resource/` 目录下的算法文件与平台发布状态同步
- **流程**：扫描本地文件 → 匹配平台算法 → 已发布者先取消再重新上传编辑
- **使用**：填写 URL/用户名/密码 → 选择本地算法目录 → 开始更新
- **spec 位置**: `alg_sync/alg_sync_tool.spec`

### 2. 算法发布工具（alg_publish_tool）
- **功能**：基于 CSV 配置文件批量发布算法
- **流程**：加载 CSV → 与平台比对差异 → 用户确认 → 并发批量发布
- **使用**：填写连接信息 → 选择/自动加载 CSV → 查看比对结果 → 确认发布
- **spec 位置**: `alg_publish/alg_publish_tool.spec`

### 3. 算法重发布工具（alg_republish_tool）
- **功能**：对平台已发布的算法逐一执行「取消发布 → 等待1秒 → 重新发布」
- **使用**：填写连接信息 → 点击「查看已发布算法」→ 查看列表 → 点击「执行发布流程」
- **spec 位置**: `alg_republish_tool.spec`（位于项目根目录）

---

## API 封装（common/api.py）

各工具通过 `AlgAPI` 类与平台通信：

| 方法 | 说明 |
|------|------|
| `login(username, password)` | 登录，获取 token |
| `get_all_algorithms()` | 自动翻页获取全部算法，缓存到 `self.algorithms` |
| `release_algorithm(algo_id, is_release, ...)` | 发布(is_release=1) 或取消发布(is_release=0) |
| `upload_file(file_path)` | 上传算法 zip 文件到 MinIO |
| `edit_algorithm(source_path)` | 提交算法信息 |
| `match_local_files(resource_dir)` | 将本地文件名与平台 sourcePath 匹配 |

---

## 打包说明

### 当前打包方式
使用 PyInstaller + `upx=True`，打包为单文件 exe。

### 推荐的虚拟环境打包方式
```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活并安装依赖
venv\Scripts\python.exe -m pip install httpx PyQt6

# 3. 使用 venv 中的 pyinstaller 打包（以 alg_republish 为例）
venv\Scripts\python.exe -m PyInstaller alg_republish_tool.spec --clean
```

打包产物输出到 `dist/` 目录。

### 打包注意事项
- `alg_republish/` 模块独立性强，`ui.py` 已在开头通过 `sys.path.insert` 解决 `api.py` 的跨目录导入问题
- `alg_sync` 和 `alg_publish` 依赖 `common/api.py`，spec 的 `pathex` 配置需正确指向项目根目录
- `PyQt6` 的 DLL 依赖较多，单文件模式务必确保 `hiddenimports` 覆盖完整（当前已通过 hooks 自动处理）

---

## 开发调试

直接运行 GUI（需先安装依赖）：
```bash
# 系统 Python
python alg_republish/ui.py

# 或通过 venv
venv\Scripts\python.exe alg_republish/ui.py
```

命令行任务（无 GUI）：
```bash
python alg_sync/task.py
```
