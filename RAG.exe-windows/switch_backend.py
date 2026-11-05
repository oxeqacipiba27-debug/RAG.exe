"""
switch_backend.py — Утилита переключения активного бэкенда EXSCIO для Windows 10/11:
Поддерживает профили:
  1. lmstudio (порт 1234)
  2. ollama   (порт 11434)
  3. docker   (порт 11434 через контейнер Ollama в WSL2)
  4. rtx4070  (порт 8000 через LAN / Tailscale)

Использование:
  python switch_backend.py lmstudio
  python switch_backend.py ollama
  python switch_backend.py docker
  python switch_backend.py rtx4070
  или без аргументов — интерактивное меню.
"""

from __future__ import annotations

import sys
import os

# Безопасная настройка кодировки консоли Windows (Правило 5 GEMINI.md)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"

PROFILES = {
    "lmstudio": ROOT_DIR / ".env.lmstudio",
    "ollama": ROOT_DIR / ".env.ollama",
    "docker": ROOT_DIR / ".env.docker",
    "rtx4070": ROOT_DIR / ".env.rtx4070",
    "remote": ROOT_DIR / ".env.rtx4070"
}

PROFILE_NAMES = {
    "lmstudio": "LM Studio (http://localhost:1234/v1)",
    "ollama": "Ollama Native (http://localhost:11434/v1)",
    "docker": "Docker Ollama Container (http://localhost:11434/v1)",
    "rtx4070": "Remote RTX 4070 PC (Tailscale / LAN / Cloudflare :8000)",
    "remote": "Remote RTX 4070 PC (Tailscale / LAN / Cloudflare :8000)"
}


def get_current_backend() -> str:
    if not ENV_FILE.exists():
        return "Не задан (.env отсутствует)"
    with open(ENV_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip().startswith("LLM_PROVIDER="):
                prov = line.strip().split("=")[1]
                if prov == "LM_STUDIO":
                    return "LM Studio"
                elif prov == "OLLAMA_LOCAL":
                    return "Ollama Native"
                elif prov == "DOCKER":
                    return "Docker Container"
                elif prov in ("RTX4070_REMOTE", "REMOTE_PC"):
                    return "Remote RTX 4070 (ПК)"
                return prov
    return "Неизвестен"


def switch_to(profile_key: str) -> bool:
    key = profile_key.lower().strip()
    if key not in PROFILES:
        print(f"[X] Неизвестный профиль: '{profile_key}'. Доступны: lmstudio, ollama, docker, rtx4070")
        return False

    source_path = PROFILES[key]
    if not source_path.exists():
        print(f"[X] Файл конфигурации {source_path.name} не найден!")
        return False

    shutil.copyfile(source_path, ENV_FILE)
    print(f"\n[OK] Активный бэкенд успешно переключен на: {PROFILE_NAMES[key]}")
    print(f"     Конфигурация скопирована в {ENV_FILE.name}\n")
    return True


def interactive_menu():
    print("=" * 65)
    print("       МЕНЮ ПЕРЕКЛЮЧЕНИЯ БЭКЕНДА EXSCIO (WINDOWS)")
    print("=" * 65)
    print(f"  Текущий активный бэкенд: [{get_current_backend()}]")
    print("-" * 65)
    print("  [1] LM Studio             (http://localhost:1234/v1)")
    print("  [2] Ollama Native         (http://localhost:11434/v1)")
    print("  [3] Docker Container      (http://localhost:11434/v1)")
    print("  [4] Remote RTX 4070 PC    (Tailscale / LAN / Cloudflare :8000)")
    print("  [5] Запустить RAG сейчас  (run_app.py)")
    print("  [0] Выход")
    print("=" * 65)

    try:
        choice = input("Выберите вариант [0-5]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == "1":
        switch_to("lmstudio")
    elif choice == "2":
        switch_to("ollama")
    elif choice == "3":
        switch_to("docker")
    elif choice == "4":
        switch_to("rtx4070")
    elif choice == "5":
        import subprocess
        print("\n[i] Запуск приложения EXSCIO...")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        subprocess.run([sys.executable, str(ROOT_DIR / "run_app.py")])
    elif choice == "0":
        print("Отмена.")
    else:
        print("[!] Неверный выбор.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
        if target in ("1", "lm", "lmstudio", "lm_studio"):
            switch_to("lmstudio")
        elif target in ("2", "ol", "ollama", "ollama_local"):
            switch_to("ollama")
        elif target in ("3", "dk", "docker"):
            switch_to("docker")
        elif target in ("4", "rtx", "rtx4070", "remote", "pc"):
            switch_to("rtx4070")
        else:
            switch_to(target)
    else:
        interactive_menu()
