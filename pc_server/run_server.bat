@echo off
title RTX 4070 LLM & Embedding Server
cd /d "%~dp0"

echo =================================================================
echo        Starting RTX 4070 Inference Host (Port 8000)
echo =================================================================

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Please run setup_server.ps1 first.
    pause
    exit /b 1
)

echo Activating Python virtual environment...
call venv\Scripts\activate.bat

echo Launching Uvicorn server on http://0.0.0.0:8000 ...
python server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Server process terminated with exit code %ERRORLEVEL%.
    pause
)
