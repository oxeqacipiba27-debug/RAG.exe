"""
run_app.py — Автономный десктопный загрузчик EXSCIO (Arch Linux / Cross-platform).
Обеспечивает запуск локального бэкенда (LM Studio / Ollama / Docker) при открытии RAG,
загрузку моделей в GPU, старт веб-сервера Streamlit и отображение нативного окна (pywebview WebKit2GTK).
При закрытии приложения автоматически выгружает модели и освобождает память GPU.
В headless-окружении (без $DISPLAY / $WAYLAND_DISPLAY) или при отсутствии WebKit2GTK
обеспечивает плавный fallback в стандартный веб-браузер.
"""

from __future__ import annotations

import os
import sys
import time
import atexit
import signal
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional

# Безопасная настройка кодировки консоли во избежание UnicodeEncodeError
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

# Конфигурационные параметры по умолчанию
APP_DIR = Path(__file__).resolve().parent
APP_PORT = int(os.getenv("EXSCIO_PORT", "8501"))
APP_URL = f"http://localhost:{APP_PORT}"


def get_window_icon() -> Optional[str]:
    """Возвращает корректный путь к иконке окна: .ico для Windows WinForms, .png для Linux GTK."""
    if sys.platform == "win32":
        candidate = APP_DIR / "rag_icon.ico"
        if candidate.exists():
            return str(candidate.resolve())
        return None

    # Linux / Arch GTK WebKit2
    for candidate_name in ["rag_icon.png", "static/exscio.png", "rag_icon.ico"]:
        candidate_path = APP_DIR / candidate_name
        if candidate_path.exists():
            return str(candidate_path.resolve())
    return None


def has_display() -> bool:
    """Проверяет наличие активной графической подсистемы (X11 или Wayland)."""
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def notify_desktop(title: str, message: str):
    """Отправляет нативное уведомление в Hyprland или системный демон уведомлений Linux."""
    if sys.platform == "win32":
        return
    if os.getenv("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        try:
            subprocess.run(
                ["hyprctl", "notify", "1", "3500", "rgb(c792ff)", f"{title}: {message}"],
                capture_output=True,
                timeout=2
            )
            return
        except Exception:
            pass
    if shutil.which("notify-send"):
        try:
            icon = get_window_icon()
            cmd = ["notify-send", title, message]
            if icon:
                cmd.extend(["-i", icon])
            subprocess.run(cmd, capture_output=True, timeout=2)
        except Exception:
            pass


def get_available_gui_backend() -> Optional[str]:
    """
    Определяет оптимальный графический бэкенд для pywebview.
    На Wayland / Hyprland отдает приоритет Qt (PyQt6-WebEngine) для нативной отрисовки,
    жестов тачпада, корректного масштабирования и защиты от сбоев DMA-BUF WebKitGTK.
    """
    if sys.platform == "win32":
        return None

    is_wayland = bool(os.getenv("WAYLAND_DISPLAY") or os.getenv("HYPRLAND_INSTANCE_SIGNATURE"))

    # 1. Проверка доступности Qt (PyQt6 / qtpy)
    has_qt = False
    try:
        from PyQt6 import QtWebEngineWidgets  # noqa: F401
        has_qt = True
    except Exception:
        try:
            import qtpy  # noqa: F401
            has_qt = True
        except Exception:
            pass

    # 2. Проверка доступности WebKit2GTK
    has_gtk = False
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('WebKit2', '4.1')
        from gi.repository import Gtk, WebKit2  # noqa: F401
        has_gtk = True
    except Exception:
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            gi.require_version('WebKit2', '4.0')
            from gi.repository import Gtk, WebKit2  # noqa: F401
            has_gtk = True
        except Exception:
            pass

    if is_wayland:
        if has_qt:
            os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
            return "qt"
        if has_gtk:
            os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
            return "gtk"
    else:
        if has_gtk:
            return "gtk"
        if has_qt:
            return "qt"

    return None


def free_port(port: int = APP_PORT):
    """Гарантирует освобождение порта перед запуском как на Linux (lsof/fuser/ss), так и на Windows."""
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
        else:
            # Linux Arch / POSIX
            if shutil.which("lsof"):
                res = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    for pid_str in res.stdout.strip().split():
                        try:
                            if int(pid_str) != os.getpid():
                                subprocess.run(["kill", "-9", pid_str], capture_output=True)
                        except ValueError:
                            pass
            elif shutil.which("fuser"):
                subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
            elif shutil.which("ss"):
                res = subprocess.run(["ss", "-lptn", f"sport = :{port}"], capture_output=True, text=True)
                if res.returncode == 0 and res.stdout:
                    import re
                    for pid_match in re.finditer(r"pid=(\d+)", res.stdout):
                        p = pid_match.group(1)
                        if p and int(p) != os.getpid():
                            subprocess.run(["kill", "-9", p], capture_output=True)
    except Exception:
        pass


def main():
    # Настройка переменных окружения Streamlit
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    active_provider = os.getenv("LLM_PROVIDER", "LM_STUDIO").upper()

    print("=" * 65)
    print("  EXSCIO 2.0 — Автономный комплекс искусственного интеллекта")
    print(f"  Платформа: [{sys.platform.upper()}]  |  Бэкенд: [{active_provider}]")
    gpu_status = server_manager.get_gpu_summary()
    print(f"  Аппаратное ускорение: {gpu_status}")
    print("=" * 65)

    # 1. Инициализация и подготовка ИИ-бэкенда
    try:
        if "OLLAMA" in active_provider:
            print("[i] Инициализация локального бэкенда Ollama (порт 11434)...")
            ok, msg = server_manager.ensure_ollama_stack(
                progress_callback=lambda text: print(f"    -> {text}")
            )
            if ok:
                print("[OK] Служба Ollama и модели готовы к работе.")
            else:
                print(f"[!] Предупреждение при проверке Ollama: {msg}")

        elif "DOCKER" in active_provider:
            print("[i] Инициализация Docker-контейнеров с Ollama...")
            ok, msg = server_manager.start_docker_compose()
            if ok:
                print("[OK] Docker-стек запущен.")
            else:
                print(f"[!] Предупреждение при запуске Docker: {msg}")

        elif "RTX" in active_provider or "REMOTE" in active_provider:
            print("[i] Проверка подключения к Remote RTX 4070 PC (:8000)...")
            online = server_manager.is_rtx4070_online(timeout=0.6, force=True)
            if online:
                health = server_manager.get_rtx4070_health(force=True)
                loaded = health.get("loaded_llm") or "IDLE (VRAM свободна)"
                print(f"[OK] Remote RTX 4070 в сети. Активная модель: {loaded}")
            else:
                print("[i] Remote RTX 4070 оффлайн. В GUI доступны кнопки Wake-on-LAN и старта локального Mock-сервера.")

        else:
            cli = server_manager.get_lms_cli_path()
            if cli:
                print("[i] Инициализация локального ИИ-бэкенда LM Studio и загрузка моделей...")
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

    # 2. Освобождение порта и запуск Streamlit сервера
    free_port(APP_PORT)

    print(f"[i] Запуск интерфейса Streamlit на порту {APP_PORT}...")
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(APP_DIR / "rag_gui.py"),
            "--server.port", str(APP_PORT),
            "--server.headless", "true"
        ],
        cwd=str(APP_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags
    )

    cleaned_up = False

    def cleanup():
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True

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
            except Exception as exc:
                print(f"[!] Не удалось выгрузить модели: {exc}")

    def signal_handler(signum, frame):
        cleanup()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except Exception:
        pass

    atexit.register(cleanup)

    # 3. Ожидание готовности веб-сервера Streamlit
    print("[i] Ожидание готовности интерфейса RAG...")
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
        print(f"[OK] Интерфейс готов: {APP_URL}")
    else:
        print("[!] Предупреждение: Сервер отвечает дольше обычного, попытка открытия окна...")

    # 4. Отображение окна приложения (WebKit2GTK / WebBrowser Fallback / Headless)
    is_headless = any(arg in sys.argv for arg in ("--headless", "-h", "--no-gui"))
    prefer_browser = "--browser" in sys.argv

    def run_browser_fallback(reason: str):
        print(f"[i] {reason}")
        if has_display():
            print(f"[i] Открытие в браузере по умолчанию: {APP_URL}")
            try:
                webbrowser.open(APP_URL)
            except Exception:
                pass
        else:
            print(f"[i] Headless-режим: Графический сервер недоступен.")
            print(f"[i] Подключитесь через веб-браузер по адресу: {APP_URL}")
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass

    icon_path = get_window_icon()

    try:
        if is_headless:
            print(f"[OK] EXSCIO запущен в автономном headless-режиме (без GUI/браузера).")
            print(f"[i] Сервис доступен по адресу: {APP_URL}")
            print("[i] Для завершения работы нажмите Ctrl+C.")
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
        elif prefer_browser:
            run_browser_fallback("Запрошен режим работы через веб-браузер (--browser).")
        elif not has_display():
            run_browser_fallback("Графический дисплей ($DISPLAY / $WAYLAND_DISPLAY) не обнаружен (Headless / SSH режим).")
        elif not HAS_WEBVIEW:
            run_browser_fallback("Библиотека pywebview не установлена в текущем окружении.")
        else:
            gui_backend = get_available_gui_backend()
            if not gui_backend and sys.platform != "win32":
                run_browser_fallback("Не найден поддерживаемый графический движок (PyQt6 или WebKit2GTK).")
            else:
                try:
                    backend_label = (gui_backend or "winforms").upper()
                    print(f"[OK] Открытие нативного окна EXSCIO [{backend_label}]...")
                    window = webview.create_window(
                        title="EXSCIO",
                        url=APP_URL,
                        width=1220,
                        height=840,
                        min_size=(540, 420),
                        text_select=True,
                        zoomable=True
                    )
                    window.events.closed += cleanup

                    def on_gui_ready():
                        if gui_backend == "qt":
                            try:
                                from PyQt6.QtWidgets import QApplication
                                app = QApplication.instance()
                                if app:
                                    app.setApplicationName("EXSCIO")
                                    app.setDesktopFileName("exscio")
                            except Exception:
                                pass
                        elif gui_backend == "gtk":
                            try:
                                from gi.repository import GLib
                                GLib.set_prgname("exscio")
                                GLib.set_application_name("EXSCIO")
                            except Exception:
                                pass
                        notify_desktop("EXSCIO", "Автономный RAG готов к работе")

                    webview.start(func=on_gui_ready, gui=gui_backend, icon=icon_path)
                except Exception as e:
                    run_browser_fallback(f"Сбой графического движка окна ({e}).")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
