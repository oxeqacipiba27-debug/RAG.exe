@echo off
chcp 65001 >nul
title EXSCIO Studio - Остановка
cd /d "%~dp0"

echo ========================================================
echo   EXSCIO 2.0 - Остановка приложения
echo ========================================================
echo.

set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe

echo [i] Остановка процессов на порту 8501...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo [i] Остановка фоновых процессов EXSCIO...
taskkill /F /IM pythonw.exe >nul 2>&1

echo [i] Освобождение памяти GPU (выгрузка моделей)...
%PY_CMD% -c "import server_manager; server_manager.unload_all_models()" >nul 2>&1

echo [OK] Приложение EXSCIO успешно остановлено. Память GPU освобождена.
timeout /t 2 >nul
