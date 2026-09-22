@echo off
chcp 65001 >nul
title Enterprise RAG Studio
cd /d "%~dp0"

echo ========================================================
echo   Enterprise RAG 2.0 - Launching Enterprise Suite
echo ========================================================
echo.

set PY_CMD=python
if exist "venv\Scripts\python.exe" set PY_CMD=venv\Scripts\python.exe

echo [i] Interpreter: %PY_CMD%
echo [i] Starting Enterprise RAG...
echo.

%PY_CMD% run_app.py

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
