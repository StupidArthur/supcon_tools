# CLI 工具开发规范

> 基于 `qt5-version/cli/` 沉淀的交互范式，适用于所有引导式 CLI 工具。

## 技术栈

- **Python 3.11+**
- **questionary** — 交互式输入（文本、密码、确认、选择）
- **rich** — 终端美化（表格、面板、加载动画、Live 渲染）
- **PyInstaller** — 打包为单文件 exe

依赖安装：
```bash
pip install questionary rich
```

## 目录结构

```
cli/
├── __init__.py
├── common.py        # 交互框架（必须复用，不要重写）
├── sync.py          # 工具入口 1
├── publish.py       # 工具入口 2
└── ...
```

每个工具一个入口文件，共享 `common.py` 框架。

## 框架核心组件 (common.py)

### 输出

```python
from cli.common import banner, step, info, success, error, warn, divider, console

banner("工具标题", "副标题")       # 顶部横幅
step(1, 3, "步骤描述")            # Step 1/3: 步骤描述
info("普通信息")                   # 灰色
success("操作成功")                # 绿色 ✓
error("操作失败")                  # 红色 ✗
warn("警告信息")                   # 黄色 ⚠
divider()                          # 分隔线
```

### 输入

```python
from cli.common import ask_text, ask_path, confirm, choose

# 文本输入（支持默认值）
url = ask_text("服务器地址", default="http://10.16.11.1:31501")

# 密码输入（掩码）
password = ask_text("密码", password=True)

# 路径输入（循环直到不为空）
path = ask_path("算法目录", default="resource")

# Y/n 确认
if not confirm("确认开始同步"):
    sys.exit(0)

# 单选列表（上下键选择）
action = choose("选择操作", choices=["同步", "发布", "导出"])
```

### 加载状态

```python
from cli.common import spinner

with spinner("正在登录"):
    api.login(username, password)
# 自动显示: "⏳ 正在登录... ✓ (1.2s)"
# 异常时:   "⏳ 正在登录... ✗"
```

### 数据表格

```python
from cli.common import result_table

result_table(
    "匹配结果",
    ["算法名称", "ID", "状态"],
    [["algo1.zip", "1001", "已发布"]],
    styles=["", "", "bold green"],
)
```

### 流程控制 (Wizard)

```python
from cli.common import Wizard

w = Wizard("工具标题", "副标题")
w.add_step("连接配置", step_connect)    # fn(ctx: dict)
w.add_step("扫描匹配", step_scan)
w.add_step("执行同步", step_execute)
w.run()
```

每个 step 函数接收 `ctx: dict`，步骤间通过 ctx 共享数据。
Wizard 内置：步骤编号、异常捕获、失败重试（问一次）、Ctrl+C 优雅退出。

## 七种交互模式

做 CLI 工具时，根据场景选择合适的模式：

### 1. 文本输入 + 默认值
场景：收集配置信息（URL、用户名、目录路径）。
```python
ctx["url"] = ask_text("服务器地址", default="http://10.16.11.1:31501")
```

### 2. 加载动画 + 状态反馈
场景：调用 API、上传文件等耗时操作。
```python
with spinner("正在登录"):
    api.login(username, password)
info(f"已缓存 {len(api.algorithms)} 个算法")
```

### 3. 数据表格
场景：展示扫描结果、匹配结果、算法列表。
```python
result_table("匹配结果", headers, rows)
```

### 4. 单选列表
场景：让用户选择后续操作分支。
```python
action = choose("选择操作", choices=["同步", "发布", "导出"])
```

### 5. 运行中交互（后台任务 + 前台命令）
场景：长时间批量处理，用户需要中途查询状态、暂停、中止。
```python
# 后台线程跑任务，前台线程接收用户命令
# 命令: status / info <名> / vars / pause / resume / abort / help
# 回车 = 退出交互等待任务结束
```
实现要点：
- `threading.Thread(target=background_task, daemon=True)` 跑任务
- 共享 `state` dict + `threading.Lock`
- 主线程 `input(">>> ")` 接收命令
- 任务结束后打印汇总报告（成功 N 个，失败 N 个）

### 6. 日志折叠面板
场景：长时间运行产生大量日志，用户不想被刷屏，但需要时能查看。
```python
# Rich Live 实时渲染
# Tab 键展开/合上
# 合上时只显示摘要行 + 最近重要事件（WARN/ERROR）
# 展开时显示最近 N 条日志，DEBUG 灰色、WARN 黄色、ERROR 红色
```
实现要点：
- `from rich.live import Live`
- `msvcrt.kbhit()` + `msvcrt.getwch()` 检测单按键（无需回车）
- `transimate=True` 避免结束后残留
- 合上时显示 `+N 条新日志` 计数
- 重要事件（WARN/ERROR）折叠时也可见

### 7. 确认对话框
场景：执行不可逆操作前的最终确认。
```python
if not confirm("确认开始同步 5 个算法"):
    warn("已取消")
    sys.exit(0)
```

## 编码处理

`common.py` 已内置 UTF-8 修复，所有 CLI 工具自动受益：
- `sys.stdout.reconfigure(encoding="utf-8")`
- `ctypes.windll.kernel32.SetConsoleOutputCP(65001)`

不需要每个入口单独处理。

## 打包

创建 `.spec` 文件（参考 `demo_cli_tool.spec`）：

```python
a = Analysis(
    ['cli/your_tool.py'],
    pathex=['.'],
    hiddenimports=['common', 'common.api', 'questionary', 'prompt_toolkit', 'rich'],
    excludes=['PyQt5', 'PyQt6'],  # CLI 工具不需要 Qt
)
# ...
exe = EXE(..., console=True, name='工具名称')
```

打包命令：
```bash
venv\Scripts\python.exe -m PyInstaller your_tool.spec --distpath dist --workpath build --clean -y
```

关键：`console=True`（CLI 工具必须有控制台窗口）。

## Windows Terminal 启动器

Win10 老版本（如 1607）没有自带 Windows Terminal，CMD 体验差。
解决方案：打包便携版 `terminal/` 目录，用 `launch.bat` 做启动器。

```bat
@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
set "CLI_EXE=%SCRIPT_DIR%dist\工具名.exe"

REM 优先级: 系统 wt > 便携 wt > 直接运行
where wt.exe >nul 2>&1 && (
    start "" wt.exe -d "%SCRIPT_DIR%dist" "%CLI_EXE%"
    exit /b 0
)
if exist "%SCRIPT_DIR%terminal\wt.exe" (
    start "" "%SCRIPT_DIR%terminal\wt.exe" -d "%SCRIPT_DIR%dist" "%CLI_EXE%"
    exit /b 0
)
"%CLI_EXE%"
```

目录结构：
```
项目根/
├── terminal/          # 便携版 Windows Terminal（含 wt.exe + DLL + 字体）
├── dist/
│   └── 工具名.exe     # PyInstaller 打包产物
├── launch.bat         # 启动器
└── cli/
```

启动器行为：
1. 系统有 wt.exe → 用系统版启动（最佳体验）
2. 系统没有 → 用便携版启动（自动降级）
3. 便携版也没有 → 直接在当前窗口运行（兜底）

## 新工具开发清单

1. 创建 `cli/your_tool.py`
2. `sys.path.insert(0, ...)` 确保能导入 `common` 和 `common.api`
3. 设计步骤流程（一般 3-5 步）
4. 每步写一个 `step_xxx(ctx)` 函数
5. 选择合适的交互模式（参考上面七种）
6. `main()` 里用 Wizard 组装
7. 创建 `.spec` 文件
8. 打包测试

## 注意事项

- **复用 common.py**，不要重写交互组件
- **复用 common/api.py**，不要重写 API 调用
- 每个 step 函数只做一件事
- 长时间操作必须用 spinner 包装
- 批量操作必须有进度显示和最终汇总
- 失败时给用户选择（继续/重试/中止），不要直接崩
- Windows 兼容：路径用 `os.path.join`，不要硬编码 `/`
