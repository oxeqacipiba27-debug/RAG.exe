@echo off
chcp 65001 >nul
title Enterprise RAG (Ollama Native)
cd /d "%~dp0"

echo ========================================================
echo   Enterprise RAG 2.0 - Запуск с бэкендом Ollama
echo ========================================================
echo.

set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe

echo [i] Переключение профиля на Ollama Native...
"%PY_CMD%" switch_backend.py ollama

echo [i] Запуск приложения Enterprise RAG...
"%PY_CMD%" run_app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Desktop window exited with code %ERRORLEVEL%.
    echo [i] Попытка запуска в браузере по умолчанию...
    "%PY_CMD%" -m streamlit run rag_gui.py
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo [X] Критическая ошибка при запуске приложения.
        pause
    )
)
