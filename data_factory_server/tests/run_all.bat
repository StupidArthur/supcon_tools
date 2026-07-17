@echo off
title Data Factory Next - Full Stack Starter
setlocal enabledelayedexpansion

:: 获取项目根目录 (当前脚本在 tests 目录下，所以向上走一级)
set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"

echo ====================================================
echo    Data Factory Next - 一键启动脚本
echo ====================================================
echo 项目根目录: %cd%
echo.

:: 1. 启动后端服务
echo [1/2] 正在启动后端服务 (FastAPI + Engines)...
start "DF-Backend" cmd /k "python -m uvicorn web_backend.main:app --host 0.0.0.0 --port 8000"

:: 等待几秒确保后端初始化
timeout /t 3 /nobreak > nul

:: 2. 启动前端服务
echo [2/2] 正在启动前端服务 (Vite + React)...
cd web_frontend
start "DF-Frontend" cmd /k "npm run dev"

echo.
echo ====================================================
echo 系统启动指令已下发:
echo - 后端 API: http://localhost:8000
echo - 前端 界面: http://localhost:5173 (请以命令提示符输出为准)
echo.
echo 提示: 请不要关闭弹出的两个控制台窗口。
echo ====================================================
pause
