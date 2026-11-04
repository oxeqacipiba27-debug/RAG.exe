@echo off
chcp 65001 >nul
title EXSCIO - RAG Launcher

cd /d "%~dp0"

set "PY_CMD=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
)

echo [i] Запуск RAG приложения (EXSCIO Desktop)...
"%PY_CMD%" run_app.py %*
if %errorlevel% neq 0 (
    echo [!] Ошибка запуска run_app.py. Попытка через streamlit run rag_gui.py...
    "%PY_CMD%" -m streamlit run rag_gui.py
)
