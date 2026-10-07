"""
run_app.py — Автономный десктопный загрузчик EXSCIO с графическим окном запуска.
Обеспечивает запуск локального бэкенда (LM Studio / Ollama / Docker) при открытии RAG,
загрузку моделей в GPU, старт веб-сервера Streamlit и отображение нативного окна.
При закрытии приложения автоматически выгружает модели и освобождает память GPU.
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

# Безопасная настройка вывода для консоли и бесконсольного режима (pythonw)
if sys.platform == "win32":
    if sys.stdout is None:
        try:
            log_file = Path(__file__).resolve().parent / "app.log"
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

provider_labels = {
    "LM_STUDIO": "🟣 LM Studio (локально)",
    "OLLAMA_LOCAL": "🦙 Ollama Native (нативно)",
    "DOCKER": "🐳 Docker Container (контейнер)",
}
active_label = provider_labels.get(active_provider, f"🌐 {active_provider}")


def free_port(port: int = APP_PORT):
    """Гарантирует освобождение порта от зависших процессов перед запуском (GEMINI.md Rule 3)."""
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


# Настройка четкости шрифтов на High-DPI экранах Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class StartupSplashWindow:
    """Современное графическое окно статуса запуска комплекса EXSCIO."""

    def __init__(self, provider_title: str):
        self.provider_title = provider_title
        self.root = None
        self.status_lbl = None
        self.detail_lbl = None
        self.progress_bar = None
        self.err_box = None
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
        self.root.title("EXSCIO 2.0 — Запуск системы")
        self.root.geometry("480x250")
        self.root.resizable(False, False)
        self.root.configure(bg="#100c1b")
        self.root.protocol("WM_DELETE_WINDOW", self._on_user_close)

        # Иконка
        if ICON_PATH and os.path.exists(ICON_PATH):
            try:
                self.root.iconbitmap(ICON_PATH)
            except Exception:
                pass

        # Центрирование окна на экране
        self.root.update_idletasks()
        w = 480
        h = 250
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # Карточка заголовка
        main_card = tk.Frame(self.root, bg="#100c1b", padx=24, pady=18)
        main_card.pack(fill="both", expand=True)

        header_row = tk.Frame(main_card, bg="#100c1b")
        header_row.pack(fill="x", anchor="w")

        title_lbl = tk.Label(
            header_row,
            text="EXSCIO 2.0",
            font=("Segoe UI", 16, "bold"),
            fg="#f6effa",
            bg="#100c1b"
        )
        title_lbl.pack(side="left")

        badge_lbl = tk.Label(
            header_row,
            text=f"  {self.provider_title}  ",
            font=("Segoe UI", 9, "bold"),
            fg="#fbbf24",
            bg="#231938"
        )
        badge_lbl.pack(side="right")

        sub_lbl = tk.Label(
            main_card,
            text="Автономный комплекс корпоративной базы знаний и ИИ-инференса",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#100c1b"
        )
        sub_lbl.pack(anchor="w", pady=(2, 16))

        # Статус
        self.status_lbl = tk.Label(
            main_card,
            text="Подготовка компонентов системы...",
            font=("Segoe UI", 10, "bold"),
            fg="#f6effa",
            bg="#100c1b"
        )
        self.status_lbl.pack(anchor="w")

        self.detail_lbl = tk.Label(
            main_card,
            text="Очистка портов и инициализация стека...",
            font=("Segoe UI", 9),
            fg="#8b949e",
            bg="#100c1b"
        )
        self.detail_lbl.pack(anchor="w", pady=(2, 10))

        # Стиль ttk для прогресс-бара
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Exscio.Horizontal.TProgressbar",
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
            style="Exscio.Horizontal.TProgressbar",
            value=10,
            maximum=100
        )
        self.progress_bar.pack(fill="x")

    def _on_user_close(self):
        """Обработка ручного закрытия окна запуска пользователем."""
        self._is_closed = True
        try:
            self.root.destroy()
        except Exception:
            pass
        cleanup()
        sys.exit(0)

    def set_progress(self, pct: int, status: str, detail: str = ""):
        """Потокобезопасное обновление статуса запуска."""
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
        """Отображает ошибку прямо в графическом окне."""
        if not self.root:
            print(f"[X] Ошибка запуска: {err_text}")
            return

        def _err():
            if self._is_closed:
                return
            if self.status_lbl:
                self.status_lbl.config(text="❌ Ошибка при запуске комплекса", fg="#f87171")
            if self.detail_lbl:
                self.detail_lbl.config(text=err_text[:120], fg="#fca5a5")
            if self.progress_bar:
                self.progress_bar.destroy()

            import tkinter as tk
            btn = tk.Button(
                self.root,
                text="Закрыть",
                command=self.close,
                font=("Segoe UI", 10, "bold"),
                fg="#ffffff",
                bg="#b91c1c",
                activebackground="#991b1b",
                activeforeground="#ffffff",
                bd=0,
                pady=5,
                padx=15
            )
            btn.pack(pady=10)

        try:
            self.root.after(0, _err)
        except Exception:
            pass

    def close(self):
        """Закрывает окно запуска."""
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

    def run(self, worker_func: Callable[[StartupSplashWindow], None]):
        """Запускает окно и выполняет worker_func в фоновом потоке."""
        if not self.root:
            worker_func(self)
            return

        thread = threading.Thread(target=worker_func, args=(self,), daemon=True)
        thread.start()
        self.root.mainloop()


# Глобальные переменные процесса
proc: Optional[subprocess.Popen] = None
_cleaned_up = False


def cleanup():
    """Корректная остановка компонентов и освобождение GPU при выходе."""
    global _cleaned_up, proc
    if _cleaned_up:
        return
    _cleaned_up = True

    print("\n[i] Завершение работы приложения...")
    if proc is not None:
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


def setup_shutdown_hooks():
    """Регистрирует обработчики сигналов и atexit только при реальном запуске приложения."""
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except Exception:
        pass
    atexit.register(cleanup)


def startup_worker(splash: StartupSplashWindow):
    """Фоновая последовательность инициализации и запуска Streamlit."""
    global proc

    try:
        # 1. Очистка порта 8501
        splash.set_progress(15, "Очистка сетевого порта 8501...", "Проверка и завершение зависших процессов...")
        free_port(APP_PORT)

        # 2. Инициализация выбранного бэкенда
        splash.set_progress(35, f"Инициализация бэкенда: {active_label}...", "Проверка службы и моделей...")

        if "OLLAMA" in active_provider:
            ok, msg = server_manager.ensure_ollama_stack(
                progress_callback=lambda text: splash.set_progress(45, "Подготовка стека Ollama...", text)
            )
            if not ok:
                splash.set_progress(50, "Предупреждение Ollama", msg)

        elif "DOCKER" in active_provider:
            splash.set_progress(40, "Запуск Docker Compose...", "Проверка WSL2 и запуск контейнеров...")
            ok, msg = server_manager.start_docker_compose()
            if not ok:
                splash.set_progress(50, "Предупреждение Docker", msg)

        else:
            cli = server_manager.get_lms_cli_path()
            if cli:
                splash.set_progress(40, "Проверка моделей LM Studio...", "Загрузка модели в память GPU...")
                ok, msg = server_manager.ensure_autonomous_stack(
                    progress_callback=lambda text: splash.set_progress(55, "Загрузка моделей в GPU...", text)
                )
                if not ok:
                    splash.set_progress(60, "Предупреждение LM Studio", msg)
            else:
                splash.set_progress(55, "LM Studio CLI не найден", "Работа в режиме внешнего сервера...")

        # 3. Запуск веб-сервера Streamlit
        splash.set_progress(70, "Запуск веб-сервера Streamlit...", f"Порт: {APP_PORT}")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "rag_gui.py", "--server.port", str(APP_PORT), "--server.headless", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )

        # 4. Ожидание готовности сервера
        splash.set_progress(85, "Ожидание готовности графического интерфейса...", "Подключение к http://localhost:8501...")
        ready = False
        for i in range(35):
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
            splash.set_progress(100, "✅ Готово!", "Открытие интерфейса...")
            time.sleep(0.4)
            splash.close()
        else:
            splash.set_progress(95, "Сервер долго отвечает...", "Попытка открытия окна...")
            time.sleep(0.5)
            splash.close()

    except Exception as e:
        splash.show_error(f"Сбой при запуске: {e}")


def main():
    setup_shutdown_hooks()
    args = [a.lower() for a in sys.argv[1:]]
    use_console = ("--console" in args or "-c" in args)
    no_splash = ("--no-splash" in args or os.environ.get("EXSCIO_NO_SPLASH") == "1")

    print("=" * 60)
    print("  Запуск автономного десктопного комплекса EXSCIO")
    print(f"  Активный ИИ-бэкенд: [{active_provider}]")
    print("=" * 60)

    if use_console or no_splash:
        # Консольный режим запуска (для отладки и тестов)
        free_port(APP_PORT)
        global proc
        if "OLLAMA" in active_provider:
            server_manager.ensure_ollama_stack(progress_callback=print)
        elif "DOCKER" in active_provider:
            server_manager.start_docker_compose()
        else:
            if server_manager.get_lms_cli_path():
                server_manager.ensure_autonomous_stack(progress_callback=print)

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "rag_gui.py", "--server.port", str(APP_PORT), "--server.headless", "true"],
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
        # Графический режим запуска (Splash Window)
        splash = StartupSplashWindow(provider_title=active_label)
        splash.run(startup_worker)

    # 5. Отображение окна приложения с гарантированной выгрузкой моделей при закрытии
    try:
        if HAS_WEBVIEW:
            try:
                print("[OK] Открытие нативного окна EXSCIO...")
                window = webview.create_window(
                    title="EXSCIO",
                    url=APP_URL,
                    width=1220,
                    height=840,
                    min_size=(900, 650),
                    text_select=True,
                    zoomable=True
                )
                window.events.closed += cleanup
                webview.start(icon=ICON_PATH)
            except Exception as e:
                print(f"[!] Сбой webview ({e}). Открытие в браузере по умолчанию...")
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
