@echo off
chcp 65001 >nul
title EXSCIO - Остановка Docker контейнеров

cd /d "%~dp0"

echo [i] Остановка Docker-контейнеров...
docker compose down
if %errorlevel% equ 0 (
    echo [OK] Docker-контейнеры успешно остановлены.
) else (
    echo [!] Ошибка при выполнении docker compose down.
)
pause
