@echo off
chcp 65001 >nul
title EXSCIO (Docker Stack)
cd /d "%~dp0"

:: Проверка аргумента отладки (--console / -c)
if "%~1"=="--console" goto CONSOLE_MODE
if "%~1"=="-c" goto CONSOLE_MODE

:: Запуск в скрытом режиме без открытия консольных окон
wscript.exe "%~dp0start_docker.vbs"
exit

:CONSOLE_MODE
set "PATH=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin;C:\Program Files\Docker\Docker\resources\bin;%PATH%"

echo ====================================================================
echo   Запуск контейнеров Ollama + Open WebUI через Docker Compose...
echo ====================================================================

where wsl >nul 2>&1
if %ERRORLEVEL% equ 0 (
    wsl -l -q >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo [!] Внимание: В системе Windows не установлен компонент WSL2.
        echo     Docker Desktop требует WSL2 для работы движка контейнеров.
        echo     Выполните в PowerShell от Администратора: wsl --install
        echo.
    )
)

docker compose up -d

if %ERRORLEVEL% equ 0 (
    echo.
    echo [OK] Контейнеры успешно запущены в фоне!
    echo     - Ollama API : http://localhost:11434
    echo     - Open WebUI : http://localhost:3000
    echo.
) else (
    echo.
    echo [X] Ошибка запуска Docker Compose.
    echo     Убедитесь, что приложение Docker Desktop запущено.
    echo.
)

pause
