# 记忆：alg_update 项目

## 项目概述
算法同步工具系列，包含两个独立工具：

- **alg_sync** — 算法同步：上传文件 + 编辑信息 + 发布/取消发布
- **alg_publish** — 算法发布：基于 CSV 批量发布/取消发布算法

GUI 基于 PyQt6，打包为单文件 exe。共享 `common/api.py` 模块。

## 目录结构
```
alg_update/
├── common/
│   └── api.py              # AlgAPI 类，alg_sync 和 alg_publish 共用
├── alg_sync/               # 算法同步工具
│   ├── ui.py               # PyQt6 GUI（当前主界面）
│   ├── task.py             # 命令行版同步任务流程
│   ├── alg_sync_tool.spec  # PyInstaller spec 文件
│   └── dist/               # 打包输出
│       └── 算法同步工具v1.3.exe  # 当前版本
├── alg_publish/            # 算法发布工具
│   ├── alg_publish.py       # PyQt6 GUI
│   ├── algdevp3.py          # 旧版命令行脚本（已废弃，requests 写法）
│   ├── publish_list_20260423.csv  # 发布配置 CSV
│   ├── alg_publish_tool.spec  # PyInstaller spec 文件
│   └── dist/
│       └── 算法发布工具v1.0.exe  # 当前版本
├── resource/               # 本地算法文件目录（.zip / .py）
└── memory.md               # 本文件
```

## 当前版本
- alg_sync: v1.3
- alg_publish: v1.0

## 登录凭证
- URL: `http://10.16.11.1:31501`
- Username: `admin`
- Password: （为空，用户填写）
- Token 类型: `Bearer Token`，从 login 响应 `content.token` 字段获取

## common/api.py — AlgAPI 类
封装所有平台 API 调用：

| 方法 | 功能 |
|------|------|
| `login()` | 登录获取 Bearer Token |
| `get_all_algorithms()` | 自动翻页获取所有算法，缓存到 `self.algorithms` 列表和 `self.source_map` 字典 |
| `upload_file()` | 上传 zip 文件到 MinIO |
| `edit_algorithm()` | 提交算法信息（multipart/form-data） |
| `release_algorithm()` | 发布/取消发布（is_release: 0=取消, 1=发布） |
| `match_local_files()` | 用本地文件名匹配平台 sourcePath |
| `get_by_id()` / `get_by_source_path()` | 从缓存中查询 |

## 跨线程通信（关键）
- `confirm_ready = QtCore.pyqtSignal()` / `fail_ready = QtCore.pyqtSignal(str)` — 后台线程 emit，主线程 slot 接收并弹对话框
- 不用 `invokeMethod` 调度（Qt 无法找到非 slot 方法名）
- 控制台日志通过 `ConsoleEmitter.signal` + `QueuedConnection` 跨线程传递

## API 关键约定
- **algorithm/list 分页**：`path=/page/1`，分页由 `requestBase.page = "N-M"` 控制
- **algorithm/edit 接口**：需 `multipart/form-data`，字段名 `algorithm`，值为 JSON 字符串
- **type 字段**：`edit_algorithm` 自动从 `categoryOne-categoryTwo` 拼接

---

## alg_sync — 算法同步工具

### UI 界面设计（v1.3）
- 窗口标题：算法同步工具 v1.3 | designed by @yuzechao
- 三个区域：连接配置（URL/用户名/密码）、更新配置（算法目录/浏览/按钮行）、控制台输出
- 按钮行：左侧红色"开始更新" + 右侧蓝色"导出算法信息"

### 开始更新流程
1. 用户填 URL + 用户名 + 密码 + 算法目录，点"开始更新"
2. 后台线程连接平台，登录，获取算法列表，扫描本地文件匹配
3. 弹出确认对话框（`QTextBrowser` 滚动区域显示算法列表），点确定执行同步
4. 按算法逐个处理：已发布算法执行"取消发布→上传编辑→重新发布"，未发布执行"上传编辑"
5. 控制台实时输出每步结果

### 导出算法信息（v1.3 新增）
1. 用户点蓝色"导出算法信息"按钮
2. 弹出文件保存对话框，默认文件名：`{环境名}_alg_info_{YYYYMMDD}.csv`，默认目录为 exe 同级
3. 若已有缓存（`self.api` 且有 `algorithms`），直接复用数据导出；否则重新登录拉取并缓存
4. 自动收集所有算法记录的 key 作为 CSV 列头，用 `utf-8-sig` 编码写入（Excel 兼容中文）
5. 导出期间两个按钮都禁用，完成后恢复

### 核心同步流程（task.py）
1. 登录 → 2. 获取所有算法 → 3. 扫描本地文件 → 4. 匹配 sourcePath → 5. 筛选已发布 → 6. 逐个取消发布 → 7. 逐个上传编辑 → 8. 逐个重新发布

---

## alg_publish — 算法发布工具

### UI 界面设计（v1.0）
- 窗口标题：算法发布工具 v1.0 | designed by @yuzechao
- CSV 配置区：自动加载同级目录 `publish_list_*.csv` 中日期最新的文件，支持手动浏览
- 连接配置区：URL / Username / Password / 并发数（默认 3）
- 绿色"开始发布"按钮
- 发布日志区：大文本框，多时出现滚动条

### 发布流程
1. 用户填连接信息，点"开始发布"
2. 后台线程登录平台，调用 `get_all_algorithms()` 获取所有算法
3. 用 CSV 算法名称（zhName，大小写不敏感）匹配平台算法
4. 弹出确认对话框，显示：
   - **差异**：平台与 CSV 在核数/副本数/发布位置不一致的算法
   - **已发布**：CSV 设置"是"且平台已发布的（跳过）
   - **待发布**：CSV 设置"是"且平台未发布的
   - **警告**：CSV 设置"否"但平台已发布的（建议取消发布）
5. 用户确认后，按并发数分批发布（多线程并行，批间顺序）
6. 发布完成后重新 `get_all_algorithms()` 校验每个待发布算法的状态
7. 日志输出最终结果：全部成功 / 哪些失败

### CSV 格式（publish_list_*.csv）
| 列名 | 说明 |
|------|------|
| 算法名称 | 匹配平台 zhName |
| 是否发布 | 是/否 |
| 核数 | 可不填，用平台已有值 |
| 副本数 | 可不填，用平台已有值 |
| 发布位置 | CPU/GPU，可不填，用平台已有值 |