#!/usr/bin/env bash
# ==============================================================================
# EXSCIO 2.0 — Автоматический установщик для Arch Linux
# ==============================================================================
# Скрипт выполняет:
# 1. Проверку совместимости дистрибутива (Arch Linux / Manjaro / EndeavourOS).
# 2. Установку системных пакетов через pacman (Python, GTK3, WebKit2GTK-4.1, base-devel).
# 3. Развертывание виртуального окружения Python (venv) и pip-зависимостей.
# 4. Настройку исполняемых прав POSIX-скриптов.
# 5. Интеграцию в графическое окружение (Desktop Entry + High-DPI иконка).
# 6. Регистрацию пользовательских служб systemd (exscio.service, exscio-api.service).
# 7. Комплексную верификацию окружения и аппаратного ускорения (GPU).
# ==============================================================================

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${CYAN}${BOLD}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║      EXSCIO 2.0 — ИНСТАЛЛЯТОР ДЛЯ СИСТЕМ ARCH LINUX           ║"
echo "║          Enterprise RAG с поддержкой WebKit2GTK & GPU         ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 1. Проверка совместимости дистрибутива
echo -e "${BLUE}[1/7] Проверка окружения Arch Linux...${NC}"
if [ ! -f /etc/arch-release ] && ! command -v pacman >/dev/null 2>&1; then
    echo -e "${YELLOW}[!] Предупреждение: Файл /etc/arch-release или утилита pacman не обнаружены.${NC}"
    echo -e "    Данный скрипт оптимизирован для Arch Linux, Manjaro, EndeavourOS и Garudalinux."
    read -p "    Продолжить установку? [y/N]: " -r CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        echo "Установка отменена пользователем."
        exit 1
    fi
else
    echo -e "${GREEN}[✓] Система Arch Linux успешно идентифицирована.${NC}"
fi

# 2. Установка системных зависимостей через pacman
echo ""
echo -e "${BLUE}[2/7] Проверка и установка системных зависимостей pacman...${NC}"

PACMAN_DEPS=(
    "python"
    "python-pip"
    "python-virtualenv"
    "base-devel"
    "webkit2gtk-4.1"
    "gtk3"
    "python-gobject"
    "openssl"
    "lsof"
    "xdg-utils"
)

MISSING_DEPS=()
for pkg in "${PACMAN_DEPS[@]}"; do
    if ! pacman -Q "$pkg" >/dev/null 2>&1; then
        MISSING_DEPS+=("$pkg")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "${YELLOW}[i] Требуется установка недостающих пакетов: ${MISSING_DEPS[*]}${NC}"
    if [ "$EUID" -ne 0 ]; then
        echo -e "${CYAN}[i] Запрос прав sudo для выполнения: pacman -S --needed ${MISSING_DEPS[*]}${NC}"
        sudo pacman -S --needed --noconfirm "${MISSING_DEPS[@]}"
    else
        pacman -S --needed --noconfirm "${MISSING_DEPS[@]}"
    fi
else
    echo -e "${GREEN}[✓] Все необходимые системные пакеты pacman уже установлены.${NC}"
fi

# Проверка опциональных рекомендаций (Ollama, GPU, Docker)
echo ""
echo -e "${BLUE}[i] Проверка доступности ИИ-ускорителей и бэкендов...${NC}"

if command -v nvidia-smi >/dev/null 2>&1; then
    echo -e "${GREEN}[✓] Обнаружен драйвер NVIDIA CUDA: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)${NC}"
elif command -v rocm-smi >/dev/null 2>&1; then
    echo -e "${GREEN}[✓] Обнаружен драйвер AMD ROCm${NC}"
else
    echo -e "${YELLOW}[i] Дискретный GPU не обнаружен. Вычисления будут производиться на CPU.${NC}"
fi

if ! command -v ollama >/dev/null 2>&1; then
    echo -e "${YELLOW}[i] Рекомендация: Рекомендуется установить Ollama для локального инференса:${NC}"
    echo -e "    sudo pacman -S ollama"
    echo -e "    sudo systemctl enable --now ollama"
else
    echo -e "${GREEN}[✓] Ollama установлена: $(which ollama)${NC}"
fi

# 3. Настройка виртуального окружения Python
echo ""
echo -e "${BLUE}[3/7] Настройка изолированного окружения Python (venv)...${NC}"

if [ ! -d "venv" ]; then
    echo "[i] Создание виртуального окружения в $SCRIPT_DIR/venv (с доступом к системным PyGObject/WebKit2GTK)..."
    python3 -m venv --system-site-packages venv
    echo -e "${GREEN}[✓] Виртуальное окружение venv создано.${NC}"
else
    echo -e "${GREEN}[✓] Виртуальное окружение venv уже существует.${NC}"
fi

VENV_PY="$SCRIPT_DIR/venv/bin/python"
VENV_PIP="$SCRIPT_DIR/venv/bin/pip"

echo "[i] Обновление pip, wheel, setuptools..."
"$VENV_PIP" install --upgrade pip wheel setuptools --quiet

if [ -f "requirements.txt" ]; then
    echo "[i] Установка зависимостей из requirements.txt..."
    "$VENV_PIP" install -r requirements.txt
    echo -e "${GREEN}[✓] Python-зависимости успешно установлены в venv.${NC}"
else
    echo -e "${RED}[!] Файл requirements.txt не найден!${NC}"
    exit 1
fi

# 4. Установка прав на исполнение скриптов
echo ""
echo -e "${BLUE}[4/7] Установка прав на исполнение shell-скриптов...${NC}"
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true
echo -e "${GREEN}[✓] Права на исполнение успешно применены (chmod +x *.sh).${NC}"

# 5. FreeDesktop интеграция (Иконка и Desktop Entry)
echo ""
echo -e "${BLUE}[5/7] Интеграция в графическое меню приложений (FreeDesktop)...${NC}"

APPS_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$APPS_DIR" "$ICONS_DIR" "$BIN_DIR"

if [ -f "$SCRIPT_DIR/rag_icon.png" ]; then
    cp "$SCRIPT_DIR/rag_icon.png" "$ICONS_DIR/exscio.png"
elif [ -f "$SCRIPT_DIR/static/exscio.png" ]; then
    cp "$SCRIPT_DIR/static/exscio.png" "$ICONS_DIR/exscio.png"
fi

cat > "$BIN_DIR/exscio" <<EOF
#!/usr/bin/env bash
TARGET_DIR="$SCRIPT_DIR"
if [ ! -d "\$TARGET_DIR" ]; then
    echo "[X] Ошибка: Директория EXSCIO '\$TARGET_DIR' не найдена." >&2
    exit 1
fi
cd "\$TARGET_DIR"
exec "\$TARGET_DIR/start.sh" "\$@"
EOF
chmod +x "$BIN_DIR/exscio"

cat > "$APPS_DIR/exscio.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=EXSCIO
GenericName=Интеллектуальный RAG-ассистент
GenericName[en]=Enterprise RAG AI Assistant
GenericName[ru]=Интеллектуальный RAG-ассистент
Comment=Автономная корпоративная RAG-система с локальными LLM и поиском по документам
Comment[en]=Autonomous Enterprise RAG System with local LLM and vector search
Comment[ru]=Автономная корпоративная RAG-система с локальными LLM и поиском по документам
Exec=$BIN_DIR/exscio
Icon=exscio
Path=$SCRIPT_DIR
Terminal=false
Categories=Office;Development;ArtificialIntelligence;Utility;
Keywords=exscio;EXSCIO;RAG;AI;LLM;Search;Ollama;LMStudio;ИИ;Поиск;Документы;Ассистент;
StartupNotify=true
StartupWMClass=EXSCIO
EOF

chmod +x "$APPS_DIR/exscio.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
echo -e "${GREEN}[✓] Ярлык приложения создан: $APPS_DIR/exscio.desktop${NC}"
echo -e "${GREEN}[✓] Командная строка: $BIN_DIR/exscio${NC}"

# 6. Регистрация пользовательских служб systemd
echo ""
echo -e "${BLUE}[6/7] Настройка пользовательских служб systemd...${NC}"

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

cat > "$SYSTEMD_USER_DIR/exscio.service" <<EOF
[Unit]
Description=EXSCIO Enterprise RAG Desktop Service
After=network.target ollama.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/start.sh --headless
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=STREAMLIT_SERVER_HEADLESS=true

[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER_DIR/exscio-api.service" <<EOF
[Unit]
Description=EXSCIO Enterprise RAG FastAPI Server
After=network.target ollama.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/start_api.sh
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    echo -e "${GREEN}[✓] Службы systemd зарегистрированы в $SYSTEMD_USER_DIR${NC}"
    echo -e "    - Для запуска API сервера в фоне: systemctl --user start exscio-api.service"
    echo -e "    - Для автозапуска при входе в систему: systemctl --user enable exscio-api.service"
fi

# 7. Финальная проверка работоспособности
echo ""
echo -e "${BLUE}[7/7] Комплексная диагностика установленного окружения...${NC}"
"$VENV_PY" test_backends.py || true

echo ""
echo -e "${GREEN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✅ Установка EXSCIO на Arch Linux успешно завершена!          ${NC}"
echo -e "${GREEN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "  Способы запуска:"
echo -e "  1. Из терминала:           ${CYAN}./start.sh${NC}"
echo -e "  2. Выбор бэкенда ИИ:       ${CYAN}./switch_backend.sh${NC}"
echo -e "  3. Запуск FastAPI сервера: ${CYAN}./start_api.sh${NC}"
echo -e "  4. Из меню приложений:     ${CYAN}EXSCIO (в категории 'Офис' или 'Разработка')${NC}"
echo ""
