"""
test_backends.py — Диагностика и проверка доступности всех бэкендов:
1. LM Studio (порт 1234)
2. Ollama Native (порт 11434)
3. Docker Ollama Container (порт 11434 / docker CLI)
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

# UTF-8 вывод для Windows консоли
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx
from openai import OpenAI

DOCKER_CANDIDATE_PATHS = [
    "docker",
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe")
]


def find_docker_bin() -> str | None:
    for path in DOCKER_CANDIDATE_PATHS:
        found = shutil.which(path) or (path if Path(path).exists() else None)
        if found:
            return str(found)
    return None


def test_lm_studio():
    print("\n" + "=" * 65)
    print("🟣 [1/3] Проверка бэкенда: LM STUDIO (http://localhost:1234/v1)")
    print("=" * 65)
    url = "http://localhost:1234/v1"
    try:
        import server_manager
        client = OpenAI(base_url=url, api_key="lm-studio", timeout=3.0)
        models = [m.id for m in client.models.list().data]
        print(f"  Статус HTTP      : 🟢 В СЕТИ")
        print(f"  Доступные модели : {models}")

        # Проверка эмбеддингов
        if any("nomic" in m.lower() or "embed" in m.lower() for m in models):
            emb_model = next(m for m in models if "nomic" in m.lower() or "embed" in m.lower())
            emb = client.embeddings.create(model=emb_model, input="search_query: тест")
            print(f"  Эмбеддинги       : 🟢 ОК (размерность {len(emb.data[0].embedding)}) через {emb_model}")
        else:
            print("  Эмбеддинги       : 🟡 Модель эмбеддингов не обнаружена в списке.")

        # Проверка генерации
        loaded = server_manager.get_loaded_models()
        llm_model = next((m for m in models if "qwen" in m.lower() or "instruct" in m.lower()), models[0] if models else None)
        if llm_model:
            if any(llm_model in m for m in loaded):
                resp = client.chat.completions.create(
                    model=llm_model,
                    messages=[{"role": "user", "content": "Скажи одно слово: Работает"}],
                    max_tokens=10,
                    timeout=10.0
                )
                print(f"  Генерация        : 🟢 ОК (загружена в GPU: {llm_model}) -> '{resp.choices[0].message.content.strip()}'")
            else:
                print(f"  Генерация        : 🟢 ГОТОВ ({llm_model} доступна; загружается в GPU при запуске RAG с -c 8192)")
        return True
    except Exception as e:
        print(f"  Статус HTTP      : 🔴 НЕ ДОСТУПЕН ({e})")
        print("  Рекомендация     : Откройте LM Studio -> Local Server -> Start Server")
        return False


def test_ollama_native():
    print("\n" + "=" * 65)
    print("🦙 [2/3] Проверка бэкенда: OLLAMA NATIVE (http://localhost:11434/v1)")
    print("=" * 65)
    url = "http://localhost:11434/v1"
    try:
        client = OpenAI(base_url=url, api_key="ollama", timeout=20.0)
        models = [m.id for m in client.models.list().data]
        print(f"  Статус HTTP      : 🟢 В СЕТИ")
        print(f"  Доступные модели : {models}")

        # Проверка эмбеддингов
        if any("nomic" in m.lower() or "embed" in m.lower() for m in models):
            emb_model = next(m for m in models if "nomic" in m.lower() or "embed" in m.lower())
            emb = client.embeddings.create(model=emb_model, input="search_query: тест")
            print(f"  Эмбеддинги       : 🟢 ОК (размерность {len(emb.data[0].embedding)}) через {emb_model}")
        else:
            print("  Эмбеддинги       : 🟡 Запустите 'ollama pull nomic-embed-text'")

        # Проверка генерации
        llm_model = next((m for m in models if "qwen" in m.lower()), models[0] if models else None)
        if llm_model:
            resp = client.chat.completions.create(
                model=llm_model,
                messages=[{"role": "user", "content": "Скажи одно слово: Работает"}],
                max_tokens=10,
                timeout=20.0
            )
            print(f"  Генерация        : 🟢 ОК ({llm_model}) -> '{resp.choices[0].message.content.strip()}'")
        return True
    except Exception as e:
        print(f"  Статус HTTP      : 🔴 НЕ ДОСТУПЕН ({e})")
        print("  Рекомендация     : Запустите службу в консоли командой: ollama serve")
        return False


def test_docker():
    print("\n" + "=" * 65)
    print("🐳 [3/3] Проверка бэкенда: DOCKER DESKTOP / DOCKER COMPOSE")
    print("=" * 65)
    docker_bin = find_docker_bin()
    if not docker_bin:
        print("  Docker CLI       : 🔴 Не найден в PATH или стандартных директориях.")
        print("  Рекомендация     : Убедитесь, что Docker Desktop установлен.")
        return False

    print(f"  Docker CLI       : 🟢 Найден ({docker_bin})")

    # Быстрая проверка наличия WSL2 в Windows
    wsl_bin = shutil.which("wsl") or shutil.which("wsl.exe")
    if wsl_bin:
        try:
            res_wsl = subprocess.run([wsl_bin, "-l", "-q"], capture_output=True, text=True, timeout=2)
            if res_wsl.returncode != 0 or "not installed" in res_wsl.stderr.lower():
                print("  Docker Daemon    : 🟡 Docker установлен, но в Windows отсутствует WSL2.")
                print("  Рекомендация     : Для работы Docker Engine выполните в терминале Администратора: wsl --install")
                return False
        except Exception:
            pass

    try:
        res = subprocess.run([docker_bin, "ps"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            print("  Docker Daemon    : 🟢 ДЕМОН АКТИВЕН И ГОТОВ К РАБОТЕ")
            lines = res.stdout.strip().split("\n")
            containers = lines[1:] if len(lines) > 1 else []
            print(f"  Активных контейнеров: {len(containers)}")
            for c in containers:
                print(f"    - {c}")
            return True
        else:
            print(f"  Docker Daemon    : 🟡 Установлен, но движок остановлен или стартует.")
            return False
    except subprocess.TimeoutExpired:
        print("  Docker Daemon    : 🟡 Таймаут опроса. Движок Docker Desktop ожидает инициализации WSL2.")
        return False
    except Exception as e:
        print(f"  Docker Daemon    : 🔴 Ошибка опроса: {e}")
        return False


if __name__ == "__main__":
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║     RAG BACKENDS HEALTH DIAGNOSTICS & STATUS MONITOR          ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    lm_ok = test_lm_studio()
    ol_ok = test_ollama_native()
    dk_ok = test_docker()

    print("\n" + "=" * 65)
    print("ИТОГОВЫЙ СТАТУС БЭКЕНДОВ:")
    print(f"  1. LM Studio     : {'ГОТОВ 🟢' if lm_ok else 'ОФФЛАЙН 🔴'}")
    print(f"  2. Ollama Native : {'ГОТОВ 🟢' if ol_ok else 'ОФФЛАЙН 🔴'}")
    print(f"  3. Docker Stack  : {'ГОТОВ 🟢' if dk_ok else 'ТРЕБУЕТСЯ СТАРТ ДЕМОНА 🟡'}")
    print("=" * 65)
