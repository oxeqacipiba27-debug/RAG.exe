"""
switch_backend.py — Графический диспетчер и CLI утилита переключения активного бэкенда EXSCIO:
Поддерживает профили:
  1. lmstudio (порт 1234)
  2. ollama   (порт 11434)
  3. docker   (порт 11434 через контейнер)

Использование:
  python switch_backend.py              — графическое окно диспетчера (GUI)
  python switch_backend.py --cli        — интерактивное меню в консоли
  python switch_backend.py lmstudio     — переключить на LM Studio через CLI
  python switch_backend.py ollama --launch — переключить и сразу запустить RAG
"""

from __future__ import annotations

import sys
import os
import shutil
import threading
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict

# UTF-8 вывод для Windows консоли и безопасная переадресация при pythonw
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

PROFILE_SHORT_NAMES = {
    "lmstudio": "LM Studio",
    "ollama": "Ollama Native",
    "docker": "Docker Container"
}


def get_current_backend_key() -> str:
    """Возвращает ключ активного профиля ('lmstudio', 'ollama', 'docker')."""
    if not ENV_FILE.exists():
        return "lmstudio"
    try:
        with open(ENV_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip().startswith("LLM_PROVIDER="):
                    prov = line.strip().split("=")[1].upper()
                    if "LM" in prov:
                        return "lmstudio"
                    elif "OLLAMA" in prov:
                        return "ollama"
                    elif "DOCKER" in prov:
                        return "docker"
    except Exception:
        pass
    return "lmstudio"


def get_current_backend() -> str:
    """Возвращает читаемое имя текущего бэкенда."""
    if not ENV_FILE.exists():
        return "Не задан (.env отсутствует)"
    key = get_current_backend_key()
    return PROFILE_SHORT_NAMES.get(key, "LM Studio")


def switch_to(profile_key: str) -> bool:
    """Переключает активный файл .env на указанный профиль."""
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


def launch_app():
    """Запускает комплекс EXSCIO (run_app.py) в фоновом режиме без блокировки."""
    pyw = ROOT_DIR / "venv" / "Scripts" / "pythonw.exe"
    exe = str(pyw) if pyw.exists() else sys.executable
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    cmd = [exe, str(ROOT_DIR / "run_app.py")]
    subprocess.Popen(cmd, cwd=str(ROOT_DIR), creationflags=creationflags)


def check_backend_quick(key: str) -> Tuple[bool, str]:
    """Быстрая проверка доступности конкретного бэкенда."""
    import httpx

    if key == "lmstudio":
        try:
            with httpx.Client(timeout=1.2, trust_env=False) as client:
                resp = client.get("http://127.0.0.1:1234/v1/models")
                if resp.status_code == 200:
                    models = resp.json().get("data", [])
                    return True, f"В сети ({len(models)} моделей)"
        except Exception:
            pass
        return False, "Не запущен (порт 1234)"

    elif key == "ollama":
        try:
            with httpx.Client(timeout=1.2, trust_env=False) as client:
                resp = client.get("http://127.0.0.1:11434/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return True, f"В сети ({len(models)} моделей)"
        except Exception:
            pass
        return False, "Не запущен (порт 11434)"

    elif key == "docker":
        if sys.platform == "win32":
            try:
                res = subprocess.run(
                    ["wsl", "-l", "-q"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=2
                )
                if res.returncode != 0:
                    return False, "Требуется WSL2"
            except Exception:
                return False, "WSL2 не найдена"
        try:
            with httpx.Client(timeout=1.2, trust_env=False) as client:
                resp = client.get("http://127.0.0.1:11434/api/tags")
                if resp.status_code == 200:
                    return True, "Контейнер активен"
        except Exception:
            pass
        return False, "Остановлен (compose)"

    return False, "Неизвестно"


def run_gui():
    """Запускает современное графическое окно переключения бэкенда."""
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        print("[!] Tkinter не установлен, запуск консольного меню...")
        interactive_menu()
        return

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

    root = tk.Tk()
    root.title("EXSCIO 2.0 — Диспетчер бэкендов")
    root.geometry("540x510")
    root.minsize(500, 480)
    root.configure(bg="#100c1b")

    # Иконка окна
    ico_path = ROOT_DIR / "rag_icon.ico"
    if ico_path.exists():
        try:
            root.iconbitmap(str(ico_path))
        except Exception:
            pass

    # Центрирование окна
    root.update_idletasks()
    w = 540
    h = 510
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")

    current_key = get_current_backend_key()
    selected_var = tk.StringVar(value=current_key)

    # 1. Заголовок
    header_frame = tk.Frame(root, bg="#100c1b", pady=14, padx=20)
    header_frame.pack(fill="x")

    title_lbl = tk.Label(
        header_frame,
        text="EXSCIO 2.0",
        font=("Segoe UI", 17, "bold"),
        fg="#f6effa",
        bg="#100c1b"
    )
    title_lbl.pack(anchor="w")

    subtitle_lbl = tk.Label(
        header_frame,
        text="Диспетчер инференс-бэкендов и быстрый запуск комплекса",
        font=("Segoe UI", 9),
        fg="#94a3b8",
        bg="#100c1b"
    )
    subtitle_lbl.pack(anchor="w", pady=(2, 0))

    # 2. Карточка текущего статуса
    status_card = tk.Frame(root, bg="#1b1428", bd=1, relief="solid", highlightthickness=1, highlightbackground="#382e54", padx=14, pady=10)
    status_card.pack(fill="x", padx=20, pady=(0, 12))

    cur_lbl_title = tk.Label(status_card, text="АКТИВНЫЙ ПРОФИЛЬ В .ENV:", font=("Segoe UI", 9, "bold"), fg="#fbbf24", bg="#1b1428")
    cur_lbl_title.pack(anchor="w")

    active_name_lbl = tk.Label(
        status_card,
        text=f"● {PROFILE_SHORT_NAMES.get(current_key, current_key)}  ({PROFILES[current_key].name})",
        font=("Segoe UI", 11, "bold"),
        fg="#10b981",
        bg="#1b1428"
    )
    active_name_lbl.pack(anchor="w", pady=(3, 0))

    # 3. Выбор бэкенда
    options_frame = tk.LabelFrame(
        root,
        text="  Выберите целевой ИИ-бэкенд:  ",
        font=("Segoe UI", 10, "bold"),
        fg="#f6effa",
        bg="#100c1b",
        bd=1,
        relief="solid",
        padx=14,
        pady=10
    )
    options_frame.pack(fill="x", padx=20, pady=(0, 10))

    backends_info = [
        ("lmstudio", "🟣 LM Studio (локально)", "http://localhost:1234/v1 — Рекомендуемый автономный бэкенд на GPU"),
        ("ollama", "🦙 Ollama Native (нативно)", "http://localhost:11434/v1 — Системная служба Ollama Windows"),
        ("docker", "🐳 Docker Container (контейнер)", "http://localhost:11434/v1 — Docker Compose стек с Open WebUI")
    ]

    status_labels: Dict[str, tk.Label] = {}

    for key, name, desc in backends_info:
        row = tk.Frame(options_frame, bg="#100c1b", pady=4)
        row.pack(fill="x", anchor="w")

        rb = tk.Radiobutton(
            row,
            text=name,
            value=key,
            variable=selected_var,
            font=("Segoe UI", 10, "bold"),
            fg="#f6effa",
            bg="#100c1b",
            activebackground="#100c1b",
            activeforeground="#fbbf24",
            selectcolor="#1e192f",
            cursor="hand2"
        )
        rb.pack(anchor="w")

        desc_row = tk.Frame(row, bg="#100c1b")
        desc_row.pack(fill="x", padx=(24, 0))

        desc_lbl = tk.Label(desc_row, text=desc, font=("Segoe UI", 9), fg="#8b949e", bg="#100c1b")
        desc_lbl.pack(side="left")

        st_lbl = tk.Label(desc_row, text="[опрос...]", font=("Segoe UI", 9, "bold"), fg="#8b949e", bg="#100c1b")
        st_lbl.pack(side="right")
        status_labels[key] = st_lbl

    # 4. Фоновая проверка доступности
    def refresh_status_async():
        def worker():
            for b_key in ("lmstudio", "ollama", "docker"):
                ok, text = check_backend_quick(b_key)
                color = "#10b981" if ok else ("#fbbf24" if "WSL" in text else "#f87171")
                icon = "🟢" if ok else ("🟡" if "WSL" in text else "🔴")
                def update(k=b_key, t=f"{icon} {text}", c=color):
                    try:
                        lbl = status_labels.get(k)
                        if lbl and lbl.winfo_exists():
                            lbl.config(text=t, fg=c)
                    except Exception:
                        pass
                try:
                    root.after(0, update)
                except Exception:
                    break
        threading.Thread(target=worker, daemon=True).start()

    refresh_status_async()

    # 5. Кнопка ручной диагностики
    diag_row = tk.Frame(root, bg="#100c1b", padx=20)
    diag_row.pack(fill="x", pady=(0, 10))

    diag_btn = tk.Button(
        diag_row,
        text="🔄 Обновить статус доступности бэкендов",
        command=refresh_status_async,
        font=("Segoe UI", 9),
        fg="#cbd5e1",
        bg="#1e192f",
        activebackground="#2a223f",
        activeforeground="#ffffff",
        bd=1,
        relief="flat",
        cursor="hand2",
        padx=10,
        pady=3
    )
    diag_btn.pack(side="right")

    # 6. Кнопки действий
    actions_frame = tk.Frame(root, bg="#100c1b", padx=20, pady=10)
    actions_frame.pack(fill="x", side="bottom")

    msg_status_lbl = tk.Label(actions_frame, text="", font=("Segoe UI", 9, "bold"), fg="#10b981", bg="#100c1b")
    msg_status_lbl.pack(fill="x", pady=(0, 8))

    def on_apply(launch_after: bool = False):
        choice = selected_var.get()
        if switch_to(choice):
            active_name_lbl.config(
                text=f"● {PROFILE_SHORT_NAMES.get(choice, choice)}  ({PROFILES[choice].name})",
                fg="#10b981"
            )
            msg_status_lbl.config(
                text=f"✅ Конфигурация успешно переключена на {PROFILE_SHORT_NAMES.get(choice, choice)}!",
                fg="#10b981"
            )
            if launch_after:
                msg_status_lbl.config(text="🚀 Запуск EXSCIO...", fg="#fbbf24")
                root.update_idletasks()
                launch_app()
                root.after(600, root.destroy)
        else:
            msg_status_lbl.config(text="❌ Ошибка при копировании конфигурации!", fg="#f87171")

    btn_launch = tk.Button(
        actions_frame,
        text="🚀 Применить и запустить EXSCIO",
        command=lambda: on_apply(launch_after=True),
        font=("Segoe UI", 11, "bold"),
        fg="#ffffff",
        bg="#7c3aed",
        activebackground="#6d28d9",
        activeforeground="#ffffff",
        bd=0,
        cursor="hand2",
        pady=8
    )
    btn_launch.pack(fill="x", pady=(0, 6))

    btns_sub = tk.Frame(actions_frame, bg="#100c1b")
    btns_sub.pack(fill="x")

    btn_save_only = tk.Button(
        btns_sub,
        text="💾 Применить профиль",
        command=lambda: on_apply(launch_after=False),
        font=("Segoe UI", 9),
        fg="#f6effa",
        bg="#271f3a",
        activebackground="#342b4d",
        activeforeground="#ffffff",
        bd=1,
        relief="solid",
        cursor="hand2",
        pady=5
    )
    btn_save_only.pack(side="left", expand=True, fill="x", padx=(0, 4))

    btn_close = tk.Button(
        btns_sub,
        text="Закрыть",
        command=root.destroy,
        font=("Segoe UI", 9),
        fg="#94a3b8",
        bg="#181324",
        activebackground="#221b33",
        activeforeground="#ffffff",
        bd=1,
        relief="solid",
        cursor="hand2",
        pady=5
    )
    btn_close.pack(side="right", expand=True, fill="x", padx=(4, 0))

    root.bind("<Escape>", lambda e: root.destroy())
    root.bind("<Return>", lambda e: on_apply(launch_after=True))

    root.mainloop()


def interactive_menu():
    """Консольное текстовое меню для отладки и терминальных сред."""
    print("=" * 65)
    print("       МЕНЮ ПЕРЕКЛЮЧЕНИЯ БЭКЕНДА EXSCIO")
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
        print("\n[i] Запуск приложения EXSCIO...")
        launch_app()
    elif choice == "0":
        print("Отмена.")
    else:
        print("Неверный выбор.")


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    do_launch = ("--launch" in args or "-l" in args)
    args = [a for a in args if a not in ("--launch", "-l")]

    if not args:
        # Без аргументов — запускаем нативное графическое окно
        run_gui()
    elif "--cli" in args or "--console" in args:
        interactive_menu()
    else:
        target = args[0]
        if target in ("1", "lm", "lmstudio", "lm_studio"):
            switch_to("lmstudio")
        elif target in ("2", "ol", "ollama", "ollama_local"):
            switch_to("ollama")
        elif target in ("3", "dk", "docker"):
            switch_to("docker")
        else:
            switch_to(target)

        if do_launch:
            print("[i] Запуск комплекса EXSCIO...")
            launch_app()
