"""
Автономный RAG-скрипт прямого взаимодействия с LM Studio.
Работает на базе установленного httpx и pypdf (без тяжелых библиотек torch/chromadb).
"""
import os
import sys
import json
import math
import re
from pathlib import Path
from collections import Counter

# Настройка кодировки для Windows консоли
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Исключаем локальный адрес из системных прокси
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("pypdf").setLevel(logging.ERROR)

import httpx
import pypdf

LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
INDEX_FILE = "rag_index.json"
DATA_DIR = Path("data")

# Создаем httpx клиент с прямым подключением без прокси
http_client = httpx.Client(base_url=LM_STUDIO_URL, timeout=60.0, trust_env=False)

def extract_documents(target_path: Path = None):
    """Чтение PDF и TXT файлов из папки data/ или указанного файла/папки."""
    search_dir = target_path if target_path else DATA_DIR
    if search_dir.is_file():
        files = [search_dir]
    else:
        files = list(search_dir.rglob("*.pdf")) + list(search_dir.rglob("*.txt"))

    print(f"Найдено файлов для обработки: {len(files)}", flush=True)
    docs = []

    for idx, file_path in enumerate(files, 1):
        rel_path = str(file_path.relative_to(DATA_DIR.parent)) if DATA_DIR.parent in file_path.parents else str(file_path)
        print(f"[{idx}/{len(files)}] Чтение: {rel_path}...", flush=True)
        if file_path.suffix.lower() == ".pdf":
            try:
                reader = pypdf.PdfReader(str(file_path))
                num_pages = len(reader.pages)
                print(f"    Страниц в PDF: {num_pages}", flush=True)
                for page_num, page in enumerate(reader.pages):
                    try:
                        text = page.extract_text() or ""
                        text = text.strip()
                        if text:
                            docs.append({
                                "source": rel_path,
                                "page": page_num + 1,
                                "text": text
                            })
                    except Exception:
                        pass
            except Exception as e:
                print(f"    Ошибка чтения PDF {rel_path}: {e}", flush=True)
        elif file_path.suffix.lower() == ".txt":
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                    if content:
                        docs.append({
                            "source": rel_path,
                            "page": 1,
                            "text": content
                        })
            except Exception as e:
                print(f"    Ошибка чтения TXT {rel_path}: {e}", flush=True)
    return docs

def split_text_into_chunks(text: str, chunk_size: int = 800, overlap: int = 150):
    """Разбивка текста на смысловые фрагменты."""
    words = text.split()
    chunks = []
    start = 0
    words_per_chunk = chunk_size // 5  # примерно 150-160 слов
    step = words_per_chunk - (overlap // 5)
    
    while start < len(words):
        chunk_words = words[start : start + words_per_chunk]
        chunk = " ".join(chunk_words)
        if len(chunk) > 50:
            chunks.append(chunk)
        start += max(1, step)
    return chunks

def tokenize(text: str):
    """Простая токенизация для поиска по ключевым словам."""
    return [w.lower() for w in re.findall(r"\b\w{3,}\b", text)]

def check_embedding_support():
    """Проверяет, умеет ли текущий сервер LM Studio генерировать эмбеддинги."""
    try:
        resp = http_client.post("/embeddings", json={"input": "тест", "model": "local-model"}, timeout=1.5)
        if resp.status_code == 200:
            return True
    except Exception:
        pass
    return False

def get_embedding(text: str):
    """Получить вектор от LM Studio."""
    resp = http_client.post("/embeddings", json={"input": text, "model": "local-model"})
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]

def cosine_similarity(v1, v2):
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def build_index(target_path: Path = None):
    """Индексация документов."""
    print("=" * 60, flush=True)
    print(" 🛠 Создание индекса базы знаний", flush=True)
    print("=" * 60, flush=True)

    docs = extract_documents(target_path)
    if not docs:
        print("Документы не найдены!", flush=True)
        return

    use_embeddings = check_embedding_support()
    if use_embeddings:
        print("\n[✓] LM Studio поддерживает режим эмбеддингов. Используем векторный поиск.", flush=True)
    else:
        print("\n[i] В LM Studio загружена модель генерации текста (без /embeddings).", flush=True)
        print("    Используем интеллектуальный полнотекстовый поиск (BM25/TF-IDF).", flush=True)

    all_chunks = []
    print("\nНарезка документов на фрагменты...", flush=True)
    for doc in docs:
        chunks = split_text_into_chunks(doc["text"])
        for ch in chunks:
            chunk_obj = {
                "source": doc["source"],
                "page": doc["page"],
                "text": ch,
                "tokens": tokenize(ch)
            }
            if use_embeddings:
                try:
                    chunk_obj["vector"] = get_embedding(ch)
                except Exception:
                    pass
            all_chunks.append(chunk_obj)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False)

    print(f"\n✅ Индексация завершена! Всего сохранено фрагментов: {len(all_chunks)}", flush=True)
    print(f"Файл индекса: {INDEX_FILE}", flush=True)
    print("Теперь запустите чат: python rag_direct.py", flush=True)

def search_index(query: str, index_data, top_k: int = 4):
    """Поиск наиболее релевантных фрагментов по запросу."""
    q_tokens = tokenize(query)
    has_vectors = "vector" in index_data[0] if index_data else False

    if has_vectors and check_embedding_support():
        try:
            q_vec = get_embedding(query)
            scored = []
            for item in index_data:
                if "vector" in item:
                    score = cosine_similarity(q_vec, item["vector"])
                    scored.append((score, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in scored[:top_k]]
        except Exception:
            pass

    # Полнотекстовый поиск с учетом корней русских слов (стемминг по префиксу)
    scored = []
    for item in index_data:
        doc_tokens = item.get("tokens", [])
        if not doc_tokens:
            continue
        
        overlap_score = 0.0
        for qw in q_tokens:
            qw_stem = qw[:4] if len(qw) >= 4 else qw
            for dw in doc_tokens:
                if dw == qw:
                    overlap_score += 2.0  # точное совпадение
                elif len(dw) >= 4 and dw[:4] == qw_stem:
                    overlap_score += 1.2  # совпадение по корню слова (падежи/окончания)

        if overlap_score > 0:
            score = overlap_score / (math.log(len(doc_tokens) + 2))
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        # Если точных совпадений нет, берем первые фрагменты
        return index_data[:top_k]
    return [item for _, item in scored[:top_k]]

def chat_loop():
    """Интерактивный диалог с локальной нейросетью."""
    if not Path(INDEX_FILE).exists():
        print(f"❌ Файл индекса '{INDEX_FILE}' не найден.")
        print("Сначала проиндексируйте файлы командой: python rag_direct.py --index")
        return

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    print("=" * 60)
    print(" 🚀 Локальный RAG-чат (LM Studio + Direct API)")
    print("=" * 60)
    print("База знаний загружена. Фрагментов:", len(index_data))
    print("Введите вопрос (или 'exit' для выхода):\n")

    while True:
        try:
            query = input("\n💬 Вопрос: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nВыход.")
            break

        if not query or query.lower() in ("exit", "quit", "выход", "q"):
            print("До свидания!")
            break

        results = search_index(query, index_data, top_k=4)

        print("\n📄 Найденные источники:")
        for r in results:
            print(f"  • {r['source']} (стр. {r['page']})")

        # Формируем контекст
        context = "\n\n".join([
            f"[Источник: {r['source']}, стр. {r['page']}]:\n{r['text']}"
            for r in results
        ])

        system_prompt = (
            "Ты — интеллектуальный ассистент по базе документов. "
            "Отвечай на вопрос строго на основе приведенного контекста. "
            "Если в контексте нет информации, прямо напиши: 'В документах нет информации по этому вопросу.'\n\n"
            f"КОНТЕКСТ:\n{context}"
        )

        print("\n🤖 Ответ LM Studio:\n" + "-" * 40)
        try:
            payload = {
                "model": "local-model",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "temperature": 0.2,
                "stream": True
            }

            # Стриминг ответа в реальном времени через Server-Sent Events (SSE)
            with http_client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    print(f"Ошибка сервера LM Studio: {response.status_code}")
                    continue

                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0]["delta"]
                            if "content" in delta:
                                print(delta["content"], end="", flush=True)
                        except Exception:
                            pass
            print("\n" + "-" * 40)
        except Exception as e:
            print(f"\n❌ Ошибка связи с LM Studio: {e}")
            print("Убедитесь, что в LM Studio нажат 'Start Server' во вкладке Local Server!")

if __name__ == "__main__":
    if "--index" in sys.argv or "-i" in sys.argv:
        # Можно передать конкретную папку или файл: python rag_direct.py --index data/sample.pdf
        target = None
        args = [a for a in sys.argv[1:] if a not in ("--index", "-i")]
        if args:
            target = Path(args[0])
        build_index(target)
    else:
        chat_loop()
