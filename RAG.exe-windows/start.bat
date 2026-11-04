@echo off
chcp 65001 >nul
title EXSCIO 2.0 - Запуск автономного комплекса (Windows)

echo =========================================================
echo   EXSCIO 2.0 (Windows 10/11) - Запуск автономного комплекса
echo =========================================================
echo.

cd /d "%~dp0"

REM 1. Определение интерпретатора Python
set "PY_CMD=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        where py >nul 2>nul
        if %errorlevel% equ 0 (
            set "PY_CMD=py -3"
        ) else (
            echo [X] Ошибка: Python не найден в системе. Установите Python 3.10+ и добавьте его в PATH.
            pause
            exit /b 1
        )
    )
)

REM 2. Проверка и автоматическое создание .env из шаблона .env.example
if not exist "%~dp0.env" (
    if exist "%~dp0.env.example" (
        echo [i] Файл .env не найден. Создание из шаблона .env.example...
        copy /y "%~dp0.env.example" "%~dp0.env" >nul
        echo [OK] Файл .env успешно создан.
    )
)

echo [i] Интерпретатор: %PY_CMD%
echo [i] Запуск EXSCIO...
echo.

REM 3. Запуск десктопного приложения через run_app.py
"%PY_CMD%" run_app.py %*
set "EXIT_CODE=%errorlevel%"

if %EXIT_CODE% neq 0 (
    if %EXIT_CODE% neq 130 (
        echo.
        echo [!] Десктопное окно pywebview завершилось с кодом %EXIT_CODE%.
        echo [i] Попытка запуска напрямую через Streamlit в браузере по умолчанию...
        "%PY_CMD%" -m streamlit run rag_gui.py
        if %errorlevel% neq 0 (
            echo.
            echo [X] Критическая ошибка: Не удалось запустить интерфейс EXSCIO.
            pause
            exit /b 1
        )
    )
)

echo.
echo [OK] Работа EXSCIO завершена.
