@echo off
chcp 65001 >nul
title EXSCIO Studio
cd /d "%~dp0"

:: Проверка аргумента отладки (--console / -c)
if "%~1"=="--console" goto CONSOLE_MODE
if "%~1"=="-c" goto CONSOLE_MODE

:: Запуск в скрытом режиме без открытия консольных окон
wscript.exe "%~dp0start.vbs"
exit

:CONSOLE_MODE
set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe
echo ========================================================
echo   EXSCIO 2.0 - Консольный режим отладки
echo ========================================================
echo [i] Interpreter: %PY_CMD%
echo [i] Starting EXSCIO in foreground...
echo.
%PY_CMD% run_app.py --console
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Desktop window exited with code %ERRORLEVEL%.
    echo [i] Attempting to launch in default browser mode...
    %PY_CMD% -m streamlit run rag_gui.py
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo [X] Fatal: Failed to launch application.
        pause
    )
)
