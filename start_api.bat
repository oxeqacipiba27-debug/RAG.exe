@echo off
chcp 65001 >nul
title EXSCIO API Server
cd /d "%~dp0"

:: Проверка аргумента отладки (--console / -c)
if "%~1"=="--console" goto CONSOLE_MODE
if "%~1"=="-c" goto CONSOLE_MODE

:: Запуск в скрытом режиме без открытия консольных окон
wscript.exe "%~dp0start_api.vbs"
exit

:CONSOLE_MODE
set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe

echo ========================================================
echo   EXSCIO 2.0 - Консольный режим API сервера
echo ========================================================
echo [i] Interpreter: %PY_CMD%
echo [i] Starting FastAPI server on port 8000...
echo.

"%PY_CMD%" run_api.py --port 8000 --host 0.0.0.0

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [X] Ошибка при запуске API сервера.
    pause
)
