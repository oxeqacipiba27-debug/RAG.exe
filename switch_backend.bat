@echo off
chcp 65001 >nul
title EXSCIO - Диспетчер бэкендов
cd /d "%~dp0"

:: Проверка аргумента отладки (--console / -c / --cli)
if "%~1"=="--console" goto CONSOLE_MODE
if "%~1"=="-c" goto CONSOLE_MODE
if "%~1"=="--cli" goto CONSOLE_MODE

:: Запуск графического окна диспетчера без терминала
wscript.exe "%~dp0switch_backend.vbs"
exit

:CONSOLE_MODE
set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe
"%PY_CMD%" switch_backend.py --cli
