"""
run_client.py — Автономный десктопный загрузчик клиентской версии EXSCIO.
Обеспечивает:
- Освобождение сетевого порта 8501 (GEMINI.md Rule 3).
- Проверку связи с основным сервером инференса (без локальных команд GPU).
- Запуск веб-сервера Streamlit с графическим интерфейсом клиента.
- Отображение нативного окна (pywebview) или открытие в браузере.
- Автоматическое корректное завершение фоновых процессов при закрытии.
"""

from __future__ import annotations

import os
import sys
import time
import atexit
import signal
import threading
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional, Callable

# Безопасная настройка UTF-8 для вывода в консоли и pythonw (GEMINI.md Rule 5)
if sys.platform == "win32":
    if sys.stdout is None:
        try:
            log_file = Path(__file__).resolve().parent / "client_app.log"
            sys.stdout = open(log_file, "a", encoding="utf-8", errors="replace", buffering=1)
        except Exception:
            pass
    if sys.stderr is None:
        sys.stderr = sys.stdout

    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import httpx

try:
    import webview
    HAS_WEBVIEW = True
except Exception:
    HAS_WEBVIEW = False

APP_DIR = Path(__file__).resolve().parent
os.chdir(APP_DIR)

import dotenv
dotenv.load_dotenv(override=True)

# Переменные окружения Streamlit
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

CLIENT_PORT = int(os.getenv("CLIENT_PORT", "8501"))
APP_URL = f"http://localhost:{CLIENT_PORT}"
MAIN_SERVER_URL = os.getenv("MAIN_SERVER_URL", os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")).strip().rstrip("/")
if not MAIN_SERVER_URL.endswith("/v1"):
    MAIN_SERVER_URL += "/v1"

ICON_PATH = str(APP_DIR / "rag_icon.ico") if (APP_DIR / "rag_icon.ico").exists() else None


def free_port(port: int = CLIENT_PORT):
    """Гарантирует освобождение порта от зависших процессов перед стартом (GEMINI.md Rule 3)."""
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
                        time.sleep(0.4)
    except Exception:
        pass


# Настройка четкости High-DPI экранов Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class ClientSplashWindow:
    """Графическое окно запуска клиентской версии EXSCIO."""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self.root = None
        self.status_lbl = None
        self.detail_lbl = None
        self.progress_bar = None
        self._is_closed = False
        self._init_gui()

    def _init_gui(self):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:
            self.root = None
            return

        self.root = tk.Tk()
        self.root.title("EXSCIO Client — Запуск")
        self.root.geometry("480x250")
        self.root.resizable(False, False)
        self.root.configure(bg="#100c1b")
        self.root.protocol("WM_DELETE_WINDOW", self._on_user_close)

        if ICON_PATH and os.path.exists(ICON_PATH):
            try:
                self.root.iconbitmap(ICON_PATH)
            except Exception:
                pass

        self.root.update_idletasks()
        w, h = 480, 250
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        main_card = tk.Frame(self.root, bg="#100c1b", padx=24, pady=18)
        main_card.pack(fill="both", expand=True)

        header_row = tk.Frame(main_card, bg="#100c1b")
        header_row.pack(fill="x", anchor="w")

        title_lbl = tk.Label(
            header_row,
            text="EXSCIO Client",
            font=("Segoe UI", 16, "bold"),
            fg="#f6effa",
            bg="#100c1b"
        )
        title_lbl.pack(side="left")

        badge_lbl = tk.Label(
            header_row,
            text="  Клиентская версия  ",
            font=("Segoe UI", 9, "bold"),
            fg="#c792ff",
            bg="#221a31"
        )
        badge_lbl.pack(side="right")

        sub_lbl = tk.Label(
            main_card,
            text=f"Подключение к серверу: {self.server_url}",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#100c1b"
        )
        sub_lbl.pack(anchor="w", pady=(2, 16))

        self.status_lbl = tk.Label(
            main_card,
            text="Инициализация клиента...",
            font=("Segoe UI", 10, "bold"),
            fg="#f6effa",
            bg="#100c1b"
        )
        self.status_lbl.pack(anchor="w")

        self.detail_lbl = tk.Label(
            main_card,
            text="Очистка портов и подготовка интерфейса...",
            font=("Segoe UI", 9),
            fg="#8b949e",
            bg="#100c1b"
        )
        self.detail_lbl.pack(anchor="w", pady=(2, 10))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Client.Horizontal.TProgressbar",
            background="#9333ea",
            troughcolor="#1e192f",
            bordercolor="#382e54",
            lightcolor="#9333ea",
            darkcolor="#7e22ce"
        )

        self.progress_bar = ttk.Progressbar(
            main_card,
            orient="horizontal",
            mode="determinate",
            style="Client.Horizontal.TProgressbar",
            value=15,
            maximum=100
        )
        self.progress_bar.pack(fill="x")

    def _on_user_close(self):
        self._is_closed = True
        try:
            self.root.destroy()
        except Exception:
            pass
        cleanup()
        sys.exit(0)

    def set_progress(self, pct: int, status: str, detail: str = ""):
        if not self.root:
            print(f"[{pct}%] {status} - {detail}")
            return

        def _update():
            if self._is_closed:
                return
            if self.progress_bar:
                self.progress_bar["value"] = pct
            if self.status_lbl:
                self.status_lbl.config(text=status)
            if self.detail_lbl:
                self.detail_lbl.config(text=detail or "Пожалуйста, подождите...")

        try:
            self.root.after(0, _update)
        except Exception:
            pass

    def show_error(self, err_text: str):
        if not self.root:
            print(f"[X] Ошибка запуска клиента: {err_text}")
            return

        def _err():
            if self._is_closed:
                return
            if self.status_lbl:
                self.status_lbl.config(text="❌ Ошибка подключения", fg="#f87171")
            if self.detail_lbl:
                self.detail_lbl.config(text=err_text[:120], fg="#fca5a5")
            if self.progress_bar:
                self.progress_bar.destroy()

        try:
            self.root.after(0, _err)
        except Exception:
            pass

    def close(self):
        if self._is_closed or not self.root:
            return
        self._is_closed = True

        def _close():
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass

        try:
            self.root.after(0, _close)
        except Exception:
            pass

    def run(self, worker_func: Callable[[ClientSplashWindow], None]):
        if not self.root:
            worker_func(self)
            return
        thread = threading.Thread(target=worker_func, args=(self,), daemon=True)
        thread.start()
        self.root.mainloop()


proc: Optional[subprocess.Popen] = None
_cleaned_up = False


def cleanup():
    global _cleaned_up, proc
    if _cleaned_up:
        return
    _cleaned_up = True

    print("\n[i] Завершение работы клиента...")
    if proc is not None:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    free_port(CLIENT_PORT)


def signal_handler(signum, frame):
    cleanup()
    sys.exit(0)


def setup_shutdown_hooks():
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except Exception:
        pass
    atexit.register(cleanup)


def startup_worker(splash: ClientSplashWindow):
    global proc
    try:
        # 1. Очистка порта
        splash.set_progress(20, f"Очистка сетевого порта {CLIENT_PORT}...", "Проверка занятости порта...")
        free_port(CLIENT_PORT)

        # 2. Проверка доступности основного сервера
        splash.set_progress(45, "Проверка связи с основным сервером...", f"Адрес: {MAIN_SERVER_URL}")
        server_ok = False
        try:
            with httpx.Client(timeout=4.0, trust_env=False) as client:
                r = client.get(f"{MAIN_SERVER_URL}/models")
                if r.status_code == 200:
                    server_ok = True
        except Exception:
            server_ok = False

        if server_ok:
            splash.set_progress(60, "✅ Основной сервер доступен", "Подготовка графического интерфейса...")
        else:
            splash.set_progress(60, "⚠️ Предупреждение: Сервер не ответил", "Интерфейс запустится в режиме ожидания...")

        # 3. Запуск веб-сервера Streamlit
        splash.set_progress(75, "Запуск клиентского интерфейса Streamlit...", f"Порт: {CLIENT_PORT}")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(APP_DIR / "rag_gui.py"), "--server.port", str(CLIENT_PORT), "--server.headless", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(APP_DIR),
            creationflags=creationflags
        )

        # 4. Ожидание готовности
        splash.set_progress(88, "Ожидание готовности интерфейса...", "Подключение к http://localhost:8501...")
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

        splash.set_progress(100, "✅ Интерфейс готов!", "Открытие окна приложения...")
        time.sleep(0.3)
        splash.close()

    except Exception as e:
        splash.show_error(f"Сбой при запуске: {e}")


def main():
    setup_shutdown_hooks()
    args = [a.lower() for a in sys.argv[1:]]
    use_console = ("--console" in args or "-c" in args)
    no_splash = ("--no-splash" in args or os.environ.get("EXSCIO_NO_SPLASH") == "1")

    index_path = APP_DIR / os.getenv("INDEX_FILE", "rag_index.json")

    print("=" * 60)
    print("  EXSCIO RAG Client Edition")
    print(f"  Основной сервер инференса: [{MAIN_SERVER_URL}]")
    if index_path.exists():
        print(f"  База знаний: [{index_path.name}] ({index_path.stat().st_size / (1024*1024):.1f} МБ) [Read-Only 🔒]")
    else:
        print(f"  [!] База знаний: [{index_path.name}] отсутствует в каталоге")
    print("=" * 60)

    if use_console or no_splash:
        free_port(CLIENT_PORT)
        # Проверка доступности основного сервера в консольном режиме
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                r = client.get(f"{MAIN_SERVER_URL}/models")
                if r.status_code == 200:
                    models = [m["id"] for m in r.json().get("data", []) if "id" in m]
                    print(f"  [OK] Связь с основным сервером установлена (моделей: {len(models)})")
                else:
                    print(f"  [!] Основной сервер ответил кодом: {r.status_code}")
        except Exception as e:
            print(f"  [!] Предупреждение: Сервер {MAIN_SERVER_URL} не ответил ({e})")

        global proc
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(APP_DIR / "rag_gui.py"), "--server.port", str(CLIENT_PORT), "--server.headless", "true"],
            cwd=str(APP_DIR),
            creationflags=creationflags
        )

        ready = False
        for _ in range(30):
            try:
                with httpx.Client(timeout=1.0, trust_env=False) as client:
                    if client.get(APP_URL).status_code == 200:
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(0.5)

        if not ready:
            print("[!] Предупреждение: Сервер долго отвечает...")
        else:
            print(f"  [OK] Веб-сервер Streamlit готов: {APP_URL}")
    else:
        splash = ClientSplashWindow(server_url=MAIN_SERVER_URL)
        splash.run(startup_worker)

    # Отображение окна приложения
    no_gui = ("--headless" in args or os.environ.get("EXSCIO_NO_GUI") == "1")
    force_browser = ("--browser" in args or os.environ.get("EXSCIO_BROWSER") == "1")

    if no_gui:
        print("[i] Работа в фоновом/headless режиме (без открытия окна GUI)...")
        try:
            if proc:
                proc.wait()
        except KeyboardInterrupt:
            pass
        return

    try:
        if HAS_WEBVIEW and not force_browser:
            try:
                print("[OK] Открытие нативного окна EXSCIO Client...")
                window = webview.create_window(
                    title="EXSCIO Client",
                    url=APP_URL,
                    width=1200,
                    height=820,
                    min_size=(900, 650),
                    text_select=True,
                    zoomable=True
                )
                window.events.closed += cleanup
                webview.start(icon=ICON_PATH)
            except Exception as e:
                print(f"[!] Сбой webview ({e}). Открытие в браузере...")
                webbrowser.open(APP_URL)
                try:
                    if proc:
                        proc.wait()
                except KeyboardInterrupt:
                    pass
        else:
            print("[i] Запуск в браузере по умолчанию...")
            webbrowser.open(APP_URL)
            try:
                if proc:
                    proc.wait()
            except KeyboardInterrupt:
                pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
