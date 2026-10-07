@echo off
chcp 65001 >nul
title SchoolX Telegram RAG Bot
cd /d "%~dp0"

:: Проверка аргумента отладки (--console / -c)
if "%~1"=="--console" goto CONSOLE_MODE
if "%~1"=="-c" goto CONSOLE_MODE

:: Запуск в скрытом режиме без открытия консольных окон
wscript.exe "%~dp0start_telegram_bot.vbs"
exit

:CONSOLE_MODE
set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe

echo ========================================================
echo   SchoolX 2.0 - Консольный режим Telegram-бота
echo ========================================================
echo [i] Python Interpreter: %PY_CMD%
echo [i] Starting Telegram Bot thin client...
echo.

"%PY_CMD%" telegram_bot.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Процесс бота завершился с кодом %ERRORLEVEL%.
    pause
)
