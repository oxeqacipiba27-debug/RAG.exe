#!/usr/bin/env bash
# ==============================================================================
# EXSCIO 2.0 — Запуск с бэкендом Ollama Native (Arch Linux)
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "  EXSCIO 2.0 (Arch Linux) — Запуск с бэкендом Ollama"
echo "========================================================"
echo ""

PY_CMD="python3"
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python3"
fi

# Проверка и запуск службы systemd на Arch Linux при наличии
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet ollama 2>/dev/null; then
        echo "[✓] Systemd-служба ollama.service активна."
    elif systemctl --user is-active --quiet ollama 2>/dev/null; then
        echo "[✓] Пользовательская systemd-служба ollama активна."
    elif systemctl is-enabled --quiet ollama 2>/dev/null; then
        echo "[i] Запуск systemd-службы ollama..."
        sudo systemctl start ollama || true
    fi
fi

echo "[i] Переключение профиля на Ollama Native..."
"$PY_CMD" switch_backend.py ollama

echo "[i] Запуск приложения EXSCIO..."
if ! "$PY_CMD" run_app.py "$@"; then
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 130 ] || [ "$EXIT_CODE" -eq 143 ]; then
        echo ""
        echo "[i] Работа EXSCIO завершена пользователем (код $EXIT_CODE)."
        exit 0
    fi
    echo ""
    echo "[!] Десктопное окно завершилось с кодом $EXIT_CODE."
    echo "[i] Попытка запуска в браузере по умолчанию..."
    if ! "$PY_CMD" -m streamlit run rag_gui.py; then
        echo ""
        echo "[X] Критическая ошибка при запуске приложения."
        exit 1
    fi
fi

