@echo off
chcp 65001 >nul
title EXSCIO - Переключение на Ollama

cd /d "%~dp0"

set "PY_CMD=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
)

echo =========================================================
echo   EXSCIO: Запуск с нативным бэкендом Ollama (:11434)
echo =========================================================
echo.

echo [i] Переключение профиля на Ollama...
"%PY_CMD%" switch_backend.py ollama
if %errorlevel% neq 0 (
    echo [!] Не удалось переключить профиль на Ollama.
)

echo.
echo [i] Запуск EXSCIO...
"%PY_CMD%" run_app.py %*
