#!/usr/bin/env bash
# ==============================================================================
# EXSCIO 2.0 — Запуск Docker стека (Ollama + Open WebUI) на Arch Linux
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "===================================================================="
echo "  Запуск контейнеров Ollama + Open WebUI через Docker Compose..."
echo "===================================================================="

if ! command -v docker >/dev/null 2>&1; then
    echo "[!] Ошибка: docker не найден в PATH."
    echo "    Установите на Arch Linux: sudo pacman -S docker docker-compose"
    exit 1
fi

# Проверка активности демона Docker в systemd
if ! docker info >/dev/null 2>&1; then
    echo "[i] Демон Docker не отвечает. Попытка запуска службы docker..."
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl start docker || {
            echo "[!] Не удалось автоматически запустить службу docker."
            echo "    Запустите вручную: sudo systemctl start docker"
            exit 1
        }
    fi
fi

# Проверка поддержки docker compose (v2 плагин) или docker-compose (v1)
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo "[!] Ошибка: Не найден docker compose или docker-compose."
    echo "    Установите: sudo pacman -S docker-compose"
    exit 1
fi

$DOCKER_COMPOSE_CMD up -d

echo ""
echo "[✓] Контейнеры успешно запущены в фоне!"
echo "    - Ollama API : http://localhost:11434"
echo "    - Open WebUI : http://localhost:3000"
echo ""
