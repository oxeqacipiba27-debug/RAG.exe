@echo off
chcp 65001 >nul
title Enterprise RAG API Server
cd /d "%~dp0"

echo ========================================================
echo   Enterprise RAG 2.0 - Launching API Server
echo ========================================================
echo.

set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe

echo [i] Interpreter: %PY_CMD%
echo [i] Starting FastAPI server on port 8000...
echo.

%PY_CMD% run_api.py --port 8000 --host 0.0.0.0

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [X] Fatal: Failed to launch API server.
    pause
)
