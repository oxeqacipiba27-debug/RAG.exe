@echo off
chcp 65001 >nul
title EXSCIO - Переключение бэкенда

cd /d "%~dp0"

set "PY_CMD=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
)

"%PY_CMD%" switch_backend.py %*
if "%~1"=="" pause
