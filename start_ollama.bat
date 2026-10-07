@echo off
chcp 65001 >nul
title EXSCIO (Ollama Native)
cd /d "%~dp0"

:: Проверка аргумента отладки (--console / -c)
if "%~1"=="--console" goto CONSOLE_MODE
if "%~1"=="-c" goto CONSOLE_MODE

:: Запуск в скрытом режиме без открытия консольных окон
wscript.exe "%~dp0start_ollama.vbs"
exit

:CONSOLE_MODE
set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe
echo ========================================================
echo   EXSCIO 2.0 - Запуск с бэкендом Ollama
echo ========================================================
echo [i] Переключение профиля на Ollama Native...
"%PY_CMD%" switch_backend.py ollama
echo [i] Запуск приложения EXSCIO...
"%PY_CMD%" run_app.py --console
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
