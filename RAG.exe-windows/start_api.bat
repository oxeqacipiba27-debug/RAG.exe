@echo off
chcp 65001 >nul
title EXSCIO API Server

cd /d "%~dp0"

set "PY_CMD=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
)

echo [i] Запуск интеграционного FastAPI/SSE сервера...
"%PY_CMD%" run_api.py %*
pause
