@echo off
chcp 65001 >nul
title EXSCIO - Запуск через Docker (WSL2)

cd /d "%~dp0"

set "PY_CMD=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
)

echo =========================================================
echo   EXSCIO: Запуск в Docker-контейнере (WSL2 / Ollama)
echo =========================================================
echo.

REM Проверка наличия подсистемы WSL2 (Правило 4 GEMINI.md)
echo [i] Проверка доступности подсистемы WSL2...
wsl -l -q >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] ПРЕДУПРЕЖДЕНИЕ: Подсистема WSL2 не обнаружена или не настроена.
    echo [!] Для работы Docker Desktop на Windows требуется WSL2.
    echo [i] Рекомендация: откройте PowerShell от имени администратора и выполните:
    echo     wsl --install
    echo.
    set /p "PROCEED=Попробовать продолжить запуск Docker вслепую? [y/N]: "
    if /i not "%PROCEED%"=="y" (
        echo [X] Запуск Docker отменен пользователем.
        pause
        exit /b 1
    )
) else (
    echo [OK] Подсистема WSL2 доступна.
)

echo.
echo [i] Переключение профиля на Docker...
"%PY_CMD%" switch_backend.py docker

echo.
echo [i] Запуск Docker Compose...
docker compose up -d
if %errorlevel% neq 0 (
    echo [!] Не удалось запустить Docker Compose. Убедитесь, что Docker Desktop запущен.
)

echo.
echo [i] Запуск EXSCIO...
"%PY_CMD%" run_app.py %*
