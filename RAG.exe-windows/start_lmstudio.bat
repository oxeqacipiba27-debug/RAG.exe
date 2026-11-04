@echo off
chcp 65001 >nul
title EXSCIO - Переключение на LM Studio

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

echo =========================================================
echo   EXSCIO: Запуск с локальным бэкендом LM Studio (:1234)
echo =========================================================
echo.

echo [i] Переключение профиля на LM Studio...
"%PY_CMD%" %PY_EXTRA% switch_backend.py lmstudio
if %errorlevel% neq 0 (
    echo [!] Не удалось переключить профиль на LM Studio.
)

echo.
echo [i] Запуск EXSCIO...
"%PY_CMD%" %PY_EXTRA% run_app.py %*
