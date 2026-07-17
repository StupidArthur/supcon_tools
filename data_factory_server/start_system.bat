@echo off
title Data Factory Next - Full Stack Starter
setlocal enabledelayedexpansion

:: 设置根目录
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

echo ====================================================
echo    Data Factory Next - V2.0 一键启动脚本
echo ====================================================
echo 项目根目录: %cd%
echo.

:: 检查 Python 依赖 (可选)
:: python -c "import fastapi, redis, pandas, numpy" >nul 2>&1
:: if %errorlevel% neq 0 (
::     echo [ERROR] 缺少核心 Python 依赖，请运行: pip install -r doc/requirements.txt
::     pause
::     exit /b
:: )

:: 1. 启动后端服务
echo [1/2] 正在启动后端服务 (FastAPI + Engines)...
start "DF-Backend" cmd /k "python -m uvicorn web_backend.main:app --host 0.0.0.0 --port 8000"

:: 等待几秒确保后端初始化
timeout /t 3 /nobreak > nul

:: 2. 启动前端服务
echo [2/2] 正在启动前端服务 (Vite + React)...
if exist "web_frontend" (
    cd web_frontend
    start "DF-Frontend" cmd /k "npm run dev"
) else (
    echo [WARNING] 未找到 web_frontend 目录，跳过前端启动。
)

echo.
echo ====================================================
echo 系统启动指令已下发:
echo - 后端 API: http://localhost:8000
echo - 前端 界面: http://localhost:5173
echo - 管理 账号: admin / admin (如有)
echo.
echo 提示: 请不要关闭弹出的两个控制台窗口。
echo ====================================================
pause
