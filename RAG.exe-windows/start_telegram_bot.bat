@echo off
chcp 65001 >nul
title EXSCIO Telegram Bot

cd /d "%~dp0"

set "PY_CMD="
set "PY_EXTRA="

if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
    goto :python_found
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
    goto :python_found
)

where python >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_found
)

where py >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py"
    set "PY_EXTRA=-3"
    goto :python_found
)

echo [X] Ошибка: Python не найден в системе. Установите Python 3.10+ и добавьте его в PATH.
pause
exit /b 1

:python_found

echo [i] Запуск Telegram бота EXSCIO...
"%PY_CMD%" %PY_EXTRA% telegram_bot.py %*
pause
