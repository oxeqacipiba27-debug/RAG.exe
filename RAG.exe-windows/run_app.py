"""
run_app.py — Автономный десктопный загрузчик EXSCIO для Windows 10/11 (Cross-Platform).
Обеспечивает запуск локального бэкенда (LM Studio / Ollama / Docker) при открытии RAG,
загрузку моделей в GPU, старт веб-сервера Streamlit и отображение нативного окна (pywebview Microsoft Edge WebView2 / WinForms).
При закрытии приложения автоматически выгружает модели и освобождает память GPU.
В headless-окружении или при отсутствии графического движка обеспечивает плавный fallback в стандартный веб-браузер.
"""

from __future__ import annotations

import os
import sys

# Безопасная настройка кодировки консоли во избежание UnicodeEncodeError на Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import time
import atexit
import signal
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional

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
    """Возвращает корректный путь к иконке окна (.ico для Windows pywebview / WinForms)."""
    for candidate_name in ["rag_icon.ico", "rag_icon.png", "static/exscio.png"]:
        candidate_path = APP_DIR / candidate_name
        if candidate_path.exists():
            return str(candidate_path.resolve())
    return None


def has_display() -> bool:
    """Проверяет наличие активной графической подсистемы."""
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def notify_desktop(title: str, message: str):
    """Отправляет нативное уведомление (на Windows через PowerShell BalloonTip, на Linux через notify-send)."""
    if sys.platform == "win32":
        try:
            ps_cmd = (
                "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null; "
                "[reflection.assembly]::loadwithpartialname('System.Drawing') | Out-Null; "
                "$notify = new-object system.windows.forms.notifyicon; "
                "$notify.icon = [System.Drawing.SystemIcons]::Information; "
                "$notify.visible = $true; "
                f"$notify.showballoontip(3000, '{title}', '{message}', [system.windows.forms.tooltipicon]::Info)"
            )
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd], creationflags=creationflags)
        except Exception:
            pass
        return

    # Linux notify-send fallback
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
    На Windows 10/11 отдает приоритет Microsoft Edge WebView2 ('edgechromium'),
    обеспечивающему аппаратное ускорение и совместимость с современными веб-стандартами.
    """
    if sys.platform == "win32":
        return "edgechromium"

    # Cross-platform / Linux fallback
    is_wayland = bool(os.getenv("WAYLAND_DISPLAY") or os.getenv("HYPRLAND_INSTANCE_SIGNATURE"))
    has_qt = False
    try:
        from PyQt6 import QtWebEngineWidgets  # noqa: F401
        has_qt = True
    except Exception:
        pass

    has_gtk = False
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('WebKit2', '4.1')
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
    """
    Гарантирует освобождение порта перед запуском.
    На Windows использует netstat -ano и taskkill /F /PID (согласно правилу 3 GEMINI.md).
    На Linux использует lsof / fuser / ss.
    """
    try:
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            res = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                creationflags=creationflags
            )
            for line in res.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.strip().split()
                    try:
                        pid = parts[-1]
                        if pid and pid != "0" and int(pid) != os.getpid():
                            subprocess.run(
                                ["taskkill", "/F", "/PID", pid],
                                capture_output=True,
                                creationflags=creationflags
                            )
                            time.sleep(0.5)
                    except (ValueError, IndexError):
                        continue
        else:
            # Linux fallback
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
    print("  EXSCIO 2.0 — Автономный комплекс искусственного интеллекта (Windows)")
    print(f"  Платформа: [{sys.platform.upper()}]  |  Бэкенд: [{active_provider}]")
    gpu_status = server_manager.get_gpu_summary()
    print(f"  Аппаратное ускорение: {gpu_status}")
    print("=" * 65)

    # 1. Инициализация и подготовка ИИ-бэкенда
    try:
        # Автоматический запуск автономной службы LLM Engine (C:\llm_engine\service.py на порту 8000)
        if sys.platform == "win32" and server_manager.get_llm_engine_service_path():
            ok_engine, msg_engine = server_manager.ensure_llm_engine_service(
                progress_callback=lambda text: print(f"    -> {text}")
            )
            if ok_engine:
                print(f"[OK] {msg_engine}")
            else:
                print(f"[!] {msg_engine}")

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
            print("[i] Инициализация Docker-контейнеров с Ollama под WSL2...")
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
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
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

        # Выгрузка моделей из памяти GPU при закрытии RAG (для LM Studio согласно правилу 1 GEMINI.md)
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

    # 4. Отображение окна приложения (pywebview Edge WebView2 / WinForms / Браузер Fallback)
    is_headless = any(arg in sys.argv for arg in ("--headless", "-h", "--no-gui"))
    prefer_browser = "--browser" in sys.argv

    def run_browser_fallback(reason: str):
        print(f"[i] {reason}")
        if has_display():
            print(f"[i] Открытие в веб-браузере по умолчанию: {APP_URL}")
            try:
                webbrowser.open(APP_URL)
            except Exception:
                pass
        else:
            print(f"[i] Headless-режим: Графический интерфейс недоступен.")
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
            run_browser_fallback("Графический дисплей не обнаружен.")
        elif not HAS_WEBVIEW:
            run_browser_fallback("Библиотека pywebview не найдена, открываем в системном браузере.")
        else:
            gui_backend = get_available_gui_backend()
            backend_label = (gui_backend or "edgechromium").upper()
            print(f"[OK] Открытие нативного окна EXSCIO [{backend_label}]...")

            window = webview.create_window(
                title="EXSCIO 2.0 — Корпоративный RAG",
                url=APP_URL,
                width=1240,
                height=860,
                min_size=(540, 420),
                text_select=True,
                zoomable=True
            )
            window.events.closed += cleanup

            def on_gui_ready():
                notify_desktop("EXSCIO 2.0", "Автономный RAG готов к работе")

            try:
                if sys.platform == "win32":
                    try:
                        webview.start(func=on_gui_ready, gui="edgechromium", icon=icon_path)
                    except Exception as e_edge:
                        print(f"[!] Сбой Edge WebView2 ({e_edge}), переключение на WinForms...")
                        webview.start(func=on_gui_ready, gui="winforms", icon=icon_path)
                else:
                    webview.start(func=on_gui_ready, gui=gui_backend, icon=icon_path)
            except Exception as e:
                run_browser_fallback(f"Сбой графического движка окна ({e}).")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
