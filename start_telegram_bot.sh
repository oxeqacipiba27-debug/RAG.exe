#!/usr/bin/env bash
# ==============================================================================
# EXSCIO 2.0 — Запуск Telegram RAG Бота (Arch Linux)
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "  EXSCIO 2.0 (Arch Linux) — Запуск Telegram Бота"
echo "========================================================"
echo ""

PY_CMD="python3"
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python3"
fi

echo "[i] Интерпретатор: $PY_CMD"
echo "[i] Запуск Telegram RAG Bot..."
echo ""

exec "$PY_CMD" telegram_bot.py "$@"
