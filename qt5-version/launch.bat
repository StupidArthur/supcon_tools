@echo off
chcp 65001 >nul 2>&1

REM ── 定位脚本所在目录 ──
set "SCRIPT_DIR=%~dp0"
set "CLI_EXE=%SCRIPT_DIR%dist\算法体检工具_演示版.exe"

REM ── 检查 CLI exe 是否存在 ──
if not exist "%CLI_EXE%" (
    echo [错误] 找不到 CLI 工具: %CLI_EXE%
    echo 请先打包: venv\Scripts\python.exe -m PyInstaller demo_cli_tool.spec
    pause
    exit /b 1
)

REM ── 优先级: 系统 wt > 便携 wt > 直接运行 ──

REM 1. 检查系统 Windows Terminal
where wt.exe >nul 2>&1
if %errorlevel%==0 (
    echo [启动] 使用系统 Windows Terminal
    start "" wt.exe -d "%SCRIPT_DIR%dist" "%CLI_EXE%"
    exit /b 0
)

REM 2. 检查便携版 Windows Terminal
set "PORTABLE_WT=%SCRIPT_DIR%terminal\wt.exe"
if exist "%PORTABLE_WT%" (
    echo [启动] 使用便携版 Windows Terminal
    echo [提示] 首次启动可能需要几秒加载
    start "" "%PORTABLE_WT%" -d "%SCRIPT_DIR%dist" "%CLI_EXE%"
    exit /b 0
)

REM 3. 直接在当前窗口运行
echo [启动] 直接运行（未找到 Windows Terminal）
echo.
"%CLI_EXE%"
