"""
run_app.py — Автономный десктопный загрузчик Enterprise RAG.
Обеспечивает запуск локального бэкенда (LM Studio) при открытии RAG,
загрузку моделей в GPU, старт веб-сервера Streamlit и отображение нативного окна.
При закрытии приложения автоматически выгружает модели и освобождает память GPU.
"""

import os
import sys
import time
import atexit
import subprocess
import webbrowser
from pathlib import Path

# Безопасная настройка кодировки консоли Windows во избежание UnicodeEncodeError и задержек буферизации
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import httpx

try:
    import webview
    HAS_WEBVIEW = True
except Exception:
    HAS_WEBVIEW = False

import dotenv
dotenv.load_dotenv(override=True)

import server_manager

# Переменные окружения Streamlit
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

APP_PORT = 8501
APP_URL = f"http://localhost:{APP_PORT}"
ICON_PATH = "rag_icon.ico" if os.path.exists("rag_icon.ico") else None

active_provider = os.getenv("LLM_PROVIDER", "LM_STUDIO").upper()

print("=" * 60)
print("  Запуск автономного десктопного комплекса Enterprise RAG")
print(f"  Активный ИИ-бэкенд: [{active_provider}]")
print("=" * 60)

# 1. Загрузка моделей в память строго при открытии RAG в соответствии с выбранным бэкендом
try:
    if "OLLAMA" in active_provider:
        print("[i] Инициализация локального бэкенда Ollama (порт 11434)...")
        ok, msg = server_manager.ensure_ollama_stack(
            progress_callback=lambda text: print(f"    -> {text}")
        )
        if ok:
            print("[OK] Служба Ollama и модели успешно готовы к работе.")
        else:
            print(f"[!] Предупреждение при проверке Ollama: {msg}")

    elif "DOCKER" in active_provider:
        print("[i] Инициализация Docker-контейнеров с Ollama...")
        ok, msg = server_manager.start_docker_compose()
        if ok:
            print("[OK] Docker-стек запущен.")
        else:
            print(f"[!] Предупреждение при запуске Docker: {msg}")

    else:
        cli = server_manager.get_lms_cli_path()
        if cli:
            print("[i] Инициализация локального ИИ-бэкенда LM Studio и загрузка моделей в GPU...")
            ok, msg = server_manager.ensure_autonomous_stack(
                progress_callback=lambda text: print(f"    -> {text}")
            )
            if ok:
                print("[OK] Модели LM Studio успешно загружены в память GPU.")
            else:
                print(f"[!] Предупреждение при загрузке моделей: {msg}")
        else:
            print("[i] LM Studio CLI не найден. RAG запустится в режиме внешнего сервера.")
except Exception as e:
    print(f"[!] Ошибка при инициализации бэкенда: {e}")

# 2. Запуск Streamlit сервера
creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

def free_port(port: int = APP_PORT):
    """Гарантирует освобождение порта от зависших процессов перед запуском."""
    try:
        if sys.platform == "win32":
            res = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in res.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    if pid and pid != "0" and int(pid) != os.getpid():
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        time.sleep(0.5)
    except Exception:
        pass

free_port(APP_PORT)

print("[i] Запуск интерфейса Streamlit...")
proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "rag_gui.py", "--server.port", str(APP_PORT), "--server.headless", "true"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=creationflags
)


import signal

_cleaned_up = False


def cleanup():
    """Корректная остановка компонентов и освобождение GPU при выходе."""
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True

    print("\n[i] Завершение работы приложения...")
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    # Выгрузка моделей из памяти GPU при закрытии RAG (для LM Studio)
    if "LM_STUDIO" in active_provider:
        try:
            print("[i] Освобождение памяти GPU (выгрузка моделей LM Studio)...")
            server_manager.unload_all_models()
            print("[OK] Память GPU полностью освобождена.")
        except Exception as e:
            print(f"[!] Не удалось выгрузить модели: {e}")


def signal_handler(signum, frame):
    cleanup()
    sys.exit(0)


try:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
except Exception:
    pass

atexit.register(cleanup)

# 3. Ожидание готовности сервера Streamlit
print("[i] Ожидание готовности графического интерфейса...")
ready = False
for _ in range(30):
    try:
        with httpx.Client(timeout=1.0, trust_env=False) as client:
            resp = client.get(APP_URL)
            if resp.status_code == 200:
                ready = True
                break
    except Exception:
        pass
    time.sleep(0.5)

if ready:
    print("[OK] Графический интерфейс готов к работе.")
else:
    print("[!] Предупреждение: Сервер долго отвечает, попытка отображения окна...")

# 4. Отображение окна приложения с гарантированной выгрузкой моделей при закрытии
try:
    if HAS_WEBVIEW:
        try:
            print("[OK] Открытие нативного окна Enterprise RAG Studio...")
            window = webview.create_window(
                title="Enterprise RAG Studio",
                url=APP_URL,
                width=1220,
                height=840,
                min_size=(900, 650),
                text_select=True,
                zoomable=True
            )
            # При закрытии окна немедленно вызываем освобождение памяти
            window.events.closed += cleanup
            webview.start(icon=ICON_PATH)
        except Exception as e:
            print(f"[!] Сбой webview ({e}). Открытие в браузере по умолчанию...")
            webbrowser.open(APP_URL)
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
    else:
        print("[i] Запуск в браузере по умолчанию...")
        webbrowser.open(APP_URL)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
finally:
    cleanup()

