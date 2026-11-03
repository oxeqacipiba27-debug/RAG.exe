#!/usr/bin/env bash
# ==============================================================================
# setup_laptop.sh: Automated Arch Linux Client Setup for Remote RTX 4070 RAG+LLM
# ==============================================================================

set -euo pipefail

# ANSI Color Codes
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}    Arch Linux Client Setup: Distributed RAG + RTX 4070 LLM     ${NC}"
echo -e "${CYAN}================================================================${NC}"

# 1. Package Dependency Check
echo -e "\n${YELLOW}[1/5] Checking required Arch Linux system & Python packages...${NC}"

SYSTEM_PKGS=("curl" "jq" "wol" "libnotify")
MISSING_PKGS=()

for pkg in "${SYSTEM_PKGS[@]}"; do
    if ! pacman -Qi "${pkg}" >/dev/null 2>&1 && ! command -v "${pkg}" >/dev/null 2>&1; then
        MISSING_PKGS+=("${pkg}")
    else
        echo -e "  ✔ System package found: ${GREEN}${pkg}${NC}"
    fi
done

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    echo -e "  Installing missing system packages via pacman: ${MISSING_PKGS[*]}..."
    sudo pacman -S --needed --noconfirm "${MISSING_PKGS[@]}"
fi

# Check Python libraries
PYTHON_MODULES=("openai" "httpx" "fastapi" "uvicorn")
MISSING_PY=()

for mod in "${PYTHON_MODULES[@]}"; do
    if ! python3 -c "import ${mod}" >/dev/null 2>&1; then
        MISSING_PY+=("${mod}")
    else
        echo -e "  ✔ Python module found: ${GREEN}${mod}${NC}"
    fi
done

if [[ ${#MISSING_PY[@]} -gt 0 ]]; then
    echo -e "  Installing missing Python modules (${MISSING_PY[*]})..."
    # Try pacman first, fallback to pip
    for mod in "${MISSING_PY[@]}"; do
        pacman_name="python-${mod}"
        if sudo pacman -S --needed --noconfirm "${pacman_name}" 2>/dev/null; then
            echo -e "  ✔ Installed ${pacman_name} via pacman"
        else
            echo -e "  Installing ${mod} via pip..."
            python3 -m pip install --break-system-packages "${mod}" 2>/dev/null || pip install "${mod}"
        fi
    done
fi

# 2. Directory Creation
echo -e "\n${YELLOW}[2/5] Creating configuration and binary directories...${NC}"
mkdir -p "${HOME}/.config/llm-remote"
mkdir -p "${HOME}/.local/bin"
mkdir -p "${HOME}/.local/share/llm-remote"
echo -e "  ✔ Directories ensured: ~/.config/llm-remote, ~/.local/bin, ~/.local/share/llm-remote"

# 3. Detect Preferred Wayland/X11 Launcher
echo -e "\n${YELLOW}[3/5] Detecting application launcher...${NC}"
DETECTED_LAUNCHER="rofi -dmenu -i -p 'RTX 4070'"
if command -v rofi >/dev/null 2>&1; then
    DETECTED_LAUNCHER="rofi -dmenu -i -p 'RTX 4070'"
    echo -e "  ✔ Detected launcher: ${GREEN}rofi${NC}"
elif command -v fuzzel >/dev/null 2>&1; then
    DETECTED_LAUNCHER="fuzzel --dmenu -p 'RTX 4070 > '"
    echo -e "  ✔ Detected launcher: ${GREEN}fuzzel${NC}"
elif command -v wofi >/dev/null 2>&1; then
    DETECTED_LAUNCHER="wofi --dmenu -p 'RTX 4070'"
    echo -e "  ✔ Detected launcher: ${GREEN}wofi${NC}"
else
    echo -e "  ${YELLOW}! No dmenu launcher found. Defaulting to rofi.${NC}"
fi

# 4. Generate ~/.config/llm-remote/config.env
CONFIG_FILE="${HOME}/.config/llm-remote/config.env"
echo -e "\n${YELLOW}[4/5] Configuring environment in ${CONFIG_FILE}...${NC}"

if [[ -f "${CONFIG_FILE}" ]]; then
    echo -e "  Existing config found at ${CONFIG_FILE}. Preserving existing values."
else
    cat <<EOF > "${CONFIG_FILE}"
# ==============================================================================
# LLM Remote Infrastructure Configuration (Arch Laptop <-> Windows 11 PC)
# ==============================================================================

# Active Target Server Connection
# Defaulted to 127.0.0.1 for local mock server testing while PC is turned off.
# When turning on the real PC, simply change LLM_SERVER_IP to your LAN/Tailscale IP!
LLM_SERVER_IP="127.0.0.1"
LLM_SERVER_PORT="8000"
LLM_SERVER_MAC="00:11:22:33:44:55"

# Secondary / Real PC LAN or Tailscale IP (used for quick toggling via menu)
REAL_SERVER_IP="192.168.1.100"

# Default context size for switching models (8192, 16384, 32768)
LLM_DEFAULT_CTX="16384"

# Application launcher command (auto-detected)
LAUNCHER_CMD="${DETECTED_LAUNCHER}"
EOF
    echo -e "  ✔ Created ${GREEN}${CONFIG_FILE}${NC}"
fi

# 5. Install binaries and mock server
echo -e "\n${YELLOW}[5/5] Deploying scripts and setting executable permissions...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Deploy mock server
if [[ -f "${SCRIPT_DIR}/mock_pc_server.py" ]]; then
    cp "${SCRIPT_DIR}/mock_pc_server.py" "${HOME}/.local/share/llm-remote/mock_pc_server.py"
    chmod +x "${HOME}/.local/share/llm-remote/mock_pc_server.py"
    echo -e "  ✔ Installed ${GREEN}~/.local/share/llm-remote/mock_pc_server.py${NC}"
fi

# Deploy control plane script
if [[ -f "${SCRIPT_DIR}/llm-ctl" ]]; then
    cp "${SCRIPT_DIR}/llm-ctl" "${HOME}/.local/bin/llm-ctl"
    chmod +x "${HOME}/.local/bin/llm-ctl"
    echo -e "  ✔ Installed ${GREEN}~/.local/bin/llm-ctl${NC}"
fi

# Check PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "\n${YELLOW}Adding ~/.local/bin to ~/.bashrc PATH...${NC}"
    if ! grep -q 'PATH="$HOME/.local/bin:$PATH"' "${HOME}/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${HOME}/.bashrc"
    fi
    export PATH="$HOME/.local/bin:$PATH"
    echo -e "  ✔ Added ~/.local/bin to PATH"
fi

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}    Installation Complete! System is ready for testing.         ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "Quick verification test:"
echo -e "  1. Test Offline Waybar Status:"
echo -e "     ${CYAN}llm-ctl status${NC}"
echo -e "  2. Start Local Mock Server in background:"
echo -e "     ${CYAN}python3 ~/.local/share/llm-remote/mock_pc_server.py &${NC}"
echo -e "  3. Test Online Waybar Status:"
echo -e "     ${CYAN}llm-ctl status${NC}"
echo -e "  4. Open Interactive Control Menu:"
echo -e "     ${CYAN}llm-ctl menu${NC}"
echo -e ""
