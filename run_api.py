"""
schoolX/run_api.py — Точка входа для запуска REST & SSE API сервера RAG.
"""

import argparse
import os
import sys

# Настройка UTF-8 для консоли Windows и безопасный вывод для pythonw
if sys.platform == "win32":
    if sys.stdout is None:
        try:
            log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")
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

# Исключаем localhost из прокси
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import uvicorn
import dotenv

dotenv.load_dotenv(override=True)


def run_gui(host: str, port: int, reload: bool):
    """Графическое окно управления API сервером EXSCIO."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("[!] Tkinter не установлен, запуск в консольном режиме...")
        uvicorn.run("api.app:app", host=host, port=port, reload=reload, log_level="info")
        return

    import threading
    import webbrowser

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
    root.title("EXSCIO 2.0 — REST & SSE API Сервер")
    root.geometry("490x300")
    root.resizable(False, False)
    root.configure(bg="#100c1b")

    ico_path = os.path.join(os.path.dirname(__file__), "rag_icon.ico")
    if os.path.exists(ico_path):
        try:
            root.iconbitmap(ico_path)
        except Exception:
            pass

    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - 490) // 2)
    y = max(0, (sh - 300) // 2)
    root.geometry(f"490x300+{x}+{y}")

    # Заголовок
    header = tk.Frame(root, bg="#100c1b", padx=20, pady=16)
    header.pack(fill="x")

    top_row = tk.Frame(header, bg="#100c1b")
    top_row.pack(fill="x")

    t_lbl = tk.Label(top_row, text="EXSCIO 2.0 API Server", font=("Segoe UI", 16, "bold"), fg="#f6effa", bg="#100c1b")
    t_lbl.pack(side="left")

    badge = tk.Label(top_row, text="  FastAPI & SSE  ", font=("Segoe UI", 9, "bold"), fg="#a855f7", bg="#231938")
    badge.pack(side="right")

    sub_lbl = tk.Label(header, text="Шлюз интеграции корпоративного RAG для ботов и веб-виджетов", font=("Segoe UI", 9), fg="#94a3b8", bg="#100c1b")
    sub_lbl.pack(anchor="w", pady=(2, 0))

    # Статус-карточка
    card = tk.Frame(root, bg="#1b1428", bd=1, relief="solid", highlightthickness=1, highlightbackground="#382e54", padx=16, pady=12)
    card.pack(fill="x", padx=20, pady=(0, 14))

    st_lbl = tk.Label(card, text="● Сервер активен и готов к приему запросов", font=("Segoe UI", 10, "bold"), fg="#10b981", bg="#1b1428")
    st_lbl.pack(anchor="w")

    doc_url = f"http://localhost:{port}/docs" if host in ("0.0.0.0", "127.0.0.1") else f"http://{host}:{port}/docs"
    api_url = f"http://localhost:{port}" if host in ("0.0.0.0", "127.0.0.1") else f"http://{host}:{port}"

    info_lbl = tk.Label(card, text=f"Эндпоинт: {api_url}  |  Порт: {port}", font=("Segoe UI", 9), fg="#cbd5e1", bg="#1b1428")
    info_lbl.pack(anchor="w", pady=(4, 0))

    # Кнопки
    btn_frame = tk.Frame(root, bg="#100c1b", padx=20)
    btn_frame.pack(fill="x")

    btn_swagger = tk.Button(
        btn_frame,
        text="📖 Открыть Swagger документацию в браузере",
        command=lambda: webbrowser.open(doc_url),
        font=("Segoe UI", 10, "bold"),
        fg="#ffffff",
        bg="#7c3aed",
        activebackground="#6d28d9",
        activeforeground="#ffffff",
        bd=0,
        cursor="hand2",
        pady=8
    )
    btn_swagger.pack(fill="x", pady=(0, 8))

    config = uvicorn.Config("api.app:app", host=host, port=port, reload=reload, log_level="info")
    server = uvicorn.Server(config)

    def on_stop():
        server.should_exit = True
        try:
            root.destroy()
        except Exception:
            pass

    btn_stop = tk.Button(
        btn_frame,
        text="⏹️ Остановить сервер",
        command=on_stop,
        font=("Segoe UI", 9),
        fg="#fca5a5",
        bg="#271a2a",
        activebackground="#3b1d28",
        activeforeground="#ffffff",
        bd=1,
        relief="solid",
        cursor="hand2",
        pady=5
    )
    btn_stop.pack(fill="x")

    root.protocol("WM_DELETE_WINDOW", on_stop)

    # Запуск сервера uvicorn в daemon-потоке
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Запуск RAG API сервера")
    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("RAG_API_HOST", "0.0.0.0"),
        help="Хост для привязки сервера (по умолчанию: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("RAG_API_PORT", "8000")),
        help="Порт сервера (по умолчанию: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("RAG_API_RELOAD", "false").lower() == "true",
        help="Автоматический перезапуск при изменении кода"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Запустить графическое окно управления сервером"
    )

    args = parser.parse_args()

    if args.gui:
        run_gui(host=args.host, port=args.port, reload=args.reload)
        return

    print("=" * 65)
    print(" 🚀 Запуск EXSCIO 2.0 API Server")
    print(f" 📡 Адрес: http://{args.host}:{args.port}")
    print(f" 📖 Документация Swagger: http://localhost:{args.port}/docs")
    print("=" * 65)

    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
