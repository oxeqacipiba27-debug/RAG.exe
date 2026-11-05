@echo off
chcp 65001 >nul
title EXSCIO - RAG Launcher

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

echo [i] Запуск RAG приложения (EXSCIO Desktop)...
"%PY_CMD%" %PY_EXTRA% run_app.py %*
set "EXIT_CODE=%errorlevel%"
if %EXIT_CODE% neq 0 (
    if %EXIT_CODE% neq 130 (
        if %EXIT_CODE% neq 3221225786 (
            if %EXIT_CODE% neq -1073741510 (
                echo [!] Ошибка запуска run_app.py. Попытка через streamlit run rag_gui.py...
                "%PY_CMD%" %PY_EXTRA% -m streamlit run rag_gui.py
            )
        )
    )
)
