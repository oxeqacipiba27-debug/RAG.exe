#!/usr/bin/env bash
# ==============================================================================
# EXSCIO 2.0 — Остановка Docker стека на Arch Linux
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "===================================================================="
echo "  Остановка контейнеров Docker Compose..."
echo "===================================================================="

if docker compose version >/dev/null 2>&1; then
    docker compose down
elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose down
else
    echo "[!] Docker Compose не найден."
    exit 1
fi

echo ""
echo "[✓] Контейнеры остановлены."
echo ""
