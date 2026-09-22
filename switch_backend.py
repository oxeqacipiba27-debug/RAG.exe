"""
switch_backend.py — Утилита переключения активного бэкенда RAG:
Поддерживает профили:
  1. lmstudio (порт 1234)
  2. ollama   (порт 11434)
  3. docker   (порт 11434 через контейнер)

Использование:
  python switch_backend.py lmstudio
  python switch_backend.py ollama
  python switch_backend.py docker
  или без аргументов — интерактивное меню.
"""

import sys
import os
import shutil
from pathlib import Path

# UTF-8 вывод для Windows консоли
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"

PROFILES = {
    "lmstudio": ROOT_DIR / ".env.lmstudio",
    "ollama": ROOT_DIR / ".env.ollama",
    "docker": ROOT_DIR / ".env.docker"
}

PROFILE_NAMES = {
    "lmstudio": "LM Studio (http://localhost:1234/v1)",
    "ollama": "Ollama Native (http://localhost:11434/v1)",
    "docker": "Docker Ollama Container (http://localhost:11434/v1)"
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
                return prov
    return "Неизвестен"


def switch_to(profile_key: str) -> bool:
    key = profile_key.lower().strip()
    if key not in PROFILES:
        print(f"❌ Неизвестный профиль: '{profile_key}'. Доступны: lmstudio, ollama, docker")
        return False

    source_path = PROFILES[key]
    if not source_path.exists():
        print(f"❌ Файл профиля {source_path.name} не найден!")
        return False

    shutil.copyfile(source_path, ENV_FILE)
    print(f"\n[OK] Активный бэкенд успешно переключен на: {PROFILE_NAMES[key]}")
    print(f"     Конфигурация скопирована в {ENV_FILE.name}\n")
    return True


def interactive_menu():
    print("=" * 65)
    print("       МЕНЮ ПЕРЕКЛЮЧЕНИЯ БЭКЕНДА ENTERPRISE RAG")
    print("=" * 65)
    print(f"  Текущий активный бэкенд: [{get_current_backend()}]")
    print("-" * 65)
    print("  [1] LM Studio             (http://localhost:1234/v1)")
    print("  [2] Ollama Native         (http://localhost:11434/v1)")
    print("  [3] Docker Container      (http://localhost:11434/v1)")
    print("  [4] Проверить доступность (test_backends.py)")
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
        from test_backends import test_lm_studio, test_ollama_native, test_docker
        test_lm_studio()
        test_ollama_native()
        test_docker()
    elif choice == "5":
        import subprocess
        print("\n[i] Запуск приложения Enterprise RAG...")
        subprocess.run([sys.executable, str(ROOT_DIR / "run_app.py")])
    elif choice == "0":
        print("Отмена.")
    else:
        print("Неверный выбор.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
        if target in ("1", "lm", "lmstudio", "lm_studio"):
            switch_to("lmstudio")
        elif target in ("2", "ol", "ollama", "ollama_local"):
            switch_to("ollama")
        elif target in ("3", "dk", "docker"):
            switch_to("docker")
        else:
            switch_to(target)
    else:
        interactive_menu()
