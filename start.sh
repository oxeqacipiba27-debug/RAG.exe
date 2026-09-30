#!/usr/bin/env bash
# ==============================================================================
# EXSCIO 2.0 — Главный скрипт запуска автономного комплекса (Arch Linux)
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "  EXSCIO 2.0 (Arch Linux) — Запуск автономного комплекса"
echo "========================================================"
echo ""

PY_CMD="python3"
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
fi

echo "[i] Интерпретатор: $PY_CMD"
echo "[i] Запуск EXSCIO..."
echo ""

# Запуск десктопного приложения с авто-фоллбэком на веб-браузер
if ! "$PY_CMD" run_app.py "$@"; then
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 130 ] || [ "$EXIT_CODE" -eq 143 ]; then
        echo ""
        echo "[i] Работа EXSCIO завершена пользователем (код $EXIT_CODE)."
        exit 0
    fi
    echo ""
    echo "[!] Десктопное окно завершилось с кодом $EXIT_CODE."
    echo "[i] Попытка запуска напрямую через Streamlit в браузере по умолчанию..."
    if ! "$PY_CMD" -m streamlit run rag_gui.py; then
        echo ""
        echo "[X] Критическая ошибка: Не удалось запустить приложение EXSCIO."
        exit 1
    fi
fi

