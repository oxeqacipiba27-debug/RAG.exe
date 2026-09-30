#!/usr/bin/env bash
# ==============================================================================
# EXSCIO 2.0 — Запуск Enterprise FastAPI сервера (Arch Linux)
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "  EXSCIO 2.0 (Arch Linux) — Запуск FastAPI Сервера"
echo "========================================================"
echo ""

PY_CMD="python3"
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PY_CMD="$SCRIPT_DIR/venv/bin/python3"
fi

PORT="${EXSCIO_API_PORT:-8000}"
HOST="${EXSCIO_API_HOST:-0.0.0.0}"

echo "[i] Интерпретатор: $PY_CMD"
echo "[i] Запуск FastAPI сервера на $HOST:$PORT..."
echo ""

exec "$PY_CMD" run_api.py --port "$PORT" --host "$HOST" "$@"
