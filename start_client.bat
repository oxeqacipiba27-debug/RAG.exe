@echo off
chcp 65001 >nul
title EXSCIO Client Edition
cd /d "%~dp0"

:: Проверка аргумента отладки (--console / -c)
if "%~1"=="--console" goto CONSOLE_MODE
if "%~1"=="-c" goto CONSOLE_MODE

:: Запуск в скрытом режиме без открытия черного окна консоли
if exist "%~dp0start_client.vbs" (
    wscript.exe "%~dp0start_client.vbs"
    exit
)

:CONSOLE_MODE
set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe
echo ========================================================
echo   EXSCIO Client Edition - Запуск приложения
echo ========================================================
echo [i] Python: %PY_CMD%
echo [i] Запуск клиента...
echo.
%PY_CMD% run_client.py --console
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Завершение работы с кодом %ERRORLEVEL%.
    pause
)
