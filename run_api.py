"""
schoolX/run_api.py — Точка входа для запуска REST & SSE API сервера RAG.
"""

import argparse
import os
import sys

# Настройка UTF-8 для консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Исключаем localhost из прокси
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import uvicorn
import dotenv

dotenv.load_dotenv(override=True)


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

    args = parser.parse_args()

    print("=" * 65)
    print(" 🚀 Запуск Enterprise RAG 2.0 API Server")
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
