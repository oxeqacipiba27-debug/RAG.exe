import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

"""
rag_chat.py — Консольный интерактивный чат с базой знаний на базе EXSCIO 2.0.
Использует RAGPipeline (гибридный поиск BM25 + Nomic 768-D + LLM Qwen2.5-14B).
"""
import os
from pathlib import Path

# Исключаем локальный адрес из системных прокси
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from rag_engine import RAGPipeline, AppConfig


def main():
    print("=" * 65)
    print(" [i] EXSCIO 2.0 — Интерактивный терминальный консультант")
    print("=" * 65)

    config = AppConfig.from_env()
    index_path = Path(config.index_file)
    if not index_path.exists():
        print(f"[!] Файл индекса '{config.index_file}' не найден!")
        print("    Запустите индексацию: python ingest.py")
        sys.exit(1)

    print(f"[*] Загрузка RAG-пайплайна (индекс: {config.index_file})...")
    pipeline = RAGPipeline(config=config)
    healthy, msg = pipeline.check_health()
    if not healthy:
        print(f"[!] Предупреждение о здоровье сервисов: {msg}")
    else:
        print(f"[OK] {msg}")

    print("\n[?] Введите ваш вопрос (или 'exit' / 'quit' для выхода):")
    print("-" * 65)

    chat_history = []
    while True:
        try:
            query = input("\n[>] Вы: ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q", "выход"):
                print("Завершение сеанса. До свидания!")
                break

            response = pipeline.query(query, chat_history=chat_history)
            print(f"\n[*] Ответ ({response.latency_ms:.0f} мс | уверенность {response.confidence:.2f}):")
            print(response.answer)

            if response.citations:
                print("\n[i] Источники:")
                for cit in response.citations:
                    print(f"  * {cit.source} (стр. {cit.page})")

            chat_history.append({"role": "user", "content": query})
            chat_history.append({"role": "assistant", "content": response.answer})

        except KeyboardInterrupt:
            print("\nСеанс прерван пользователем.")
            break
        except Exception as e:
            print(f"\n[X] Ошибка: {e}")


if __name__ == "__main__":
    main()
