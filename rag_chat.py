import os
import sys
from pathlib import Path

# Настройка кодировки для корректного вывода в терминале Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Исключаем локальный адрес из системных прокси (SOCKS/HTTP)
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import httpx
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

CHROMA_DIR = "./chroma_db"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Адрес локального сервера LM Studio (по умолчанию порт 1234)
LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
API_KEY = "lm-studio"  # Для локального сервера ключ может быть любым

SYSTEM_PROMPT_TEMPLATE = """Ты — интеллектуальный ассистент, помогающий работать с базой документов.
Твоя задача — точно и понятно отвечать на вопросы пользователя, опираясь ИСКЛЮЧИТЕЛЬНО на предоставленный ниже контекст.

Правила:
1. Отвечай подробно и структурированно, основываясь только на фактах из контекста.
2. Если в контексте нет информации для ответа, прямо напиши: "В загруженных документах нет информации по этому вопросу."
3. Не придумывай и не домысливай факты, которых нет в тексте.

---
КОНТЕКСТ ИЗ ДОКУМЕНТОВ:
{context}
---"""

def format_context(docs_with_scores):
    """Форматирует найденные фрагменты с указанием источника."""
    context_parts = []
    for i, (doc, score) in enumerate(docs_with_scores, 1):
        source = doc.metadata.get("source", "Неизвестный файл")
        page = doc.metadata.get("page", None)
        page_info = f", стр. {page + 1}" if page is not None else ""
        context_parts.append(
            f"[Фрагмент {i} | Источник: {source}{page_info}]\n{doc.page_content.strip()}"
        )
    return "\n\n".join(context_parts)

def main():
    print("=" * 60)
    print(" 🚀 Локальный RAG-ассистент (LM Studio + ChromaDB)")
    print("=" * 60)

    # 1. Проверяем наличие векторной базы
    if not Path(CHROMA_DIR).exists():
        print(f"❌ Ошибка: папка базы данных '{CHROMA_DIR}' не найдена.")
        print("Сначала запустите индексацию документов: python ingest.py")
        sys.exit(1)

    # 2. Загружаем модель эмбеддингов
    print(f"Подключение эмбеддингов ({EMBEDDING_MODEL})...")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"}
    )

    # 3. Подключаемся к базе ChromaDB
    print(f"Подключение к базе ChromaDB ({CHROMA_DIR})...")
    vectorstore = Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=embeddings
    )

    # 4. Инициализируем клиент LM Studio
    print(f"Подключение к серверу LM Studio по адресу {LM_STUDIO_URL}...")
    llm = ChatOpenAI(
        base_url=LM_STUDIO_URL,
        api_key=API_KEY,
        model="local-model",  # LM Studio автоматически использует текущую загруженную модель
        temperature=0.2,       # Небольшая температура для более точных ответов по фактам
        streaming=True,        # Потоковый вывод ответа (печатается по словам)
        http_client=httpx.Client(trust_env=False)
    )

    print("\n✅ Система готова к работе!")
    print("Введите ваш вопрос (или 'exit' / 'выход' для завершения):\n")

    while True:
        try:
            query = input("\n💬 Вопрос: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nВыход из программы.")
            break

        if not query:
            continue

        if query.lower() in ("exit", "quit", "выход", "q"):
            print("До свидания!")
            break

        print("\n🔍 Поиск релевантной информации в документах...")
        # Ищем 4 наиболее релевантных фрагмента
        results = vectorstore.similarity_search_with_score(query, k=4)

        if not results:
            print("❌ В базе не найдено подходящей информации.")
            continue

        # Выводим найденные источники
        print("\n📄 Найденные источники:")
        for doc, score in results:
            src = doc.metadata.get("source", "документ")
            page = doc.metadata.get("page", None)
            page_str = f" (стр. {page + 1})" if page is not None else ""
            print(f"  • {src}{page_str}")

        # Собираем контекст для промпта
        context_text = format_context(results)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context_text)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=query)
        ]

        print("\n🤖 Ответ LM Studio:\n" + "-" * 40)
        try:
            # Стримим ответ в реальном времени
            for chunk in llm.stream(messages):
                print(chunk.content, end="", flush=True)
            print("\n" + "-" * 40)
        except Exception as e:
            print(f"\n❌ Ошибка обращения к LM Studio: {e}")
            print("Убедитесь, что в LM Studio запущен локальный сервер (порт 1234) и загружена модель!")

if __name__ == "__main__":
    main()
