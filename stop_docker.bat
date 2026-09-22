@echo off
chcp 65001 >nul
title RAG - Остановка Docker стека

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;C:\Program Files\Docker\Docker\resources\bin;%PATH%"

echo ====================================================================
echo   Остановка контейнеров Docker Compose...
echo ====================================================================

docker compose down

echo.
echo [✓] Контейнеры остановлены.
echo.
pause
