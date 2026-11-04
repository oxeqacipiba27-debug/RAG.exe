@echo off
chcp 65001 >nul
title EXSCIO Telegram Bot

cd /d "%~dp0"

set "PY_CMD=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
)

echo [i] Запуск Telegram бота EXSCIO...
"%PY_CMD%" telegram_bot.py %*
pause
