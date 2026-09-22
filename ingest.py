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
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

DATA_DIR = Path("data")
CHROMA_DIR = "./chroma_db"
# Модель для эмбеддингов: для текстов на русском отлично подходит мультиязычная модель
# Она понимает и русский, и английский язык
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
# Запасной вариант (только английский, чуть быстрее): "all-MiniLM-L6-v2"

def load_documents(data_path: Path):
    """Загрузка документов (PDF и TXT) из папки data и её подпапок."""
    documents = []
    
    if not data_path.exists():
        print(f"Папка {data_path} не найдена!")
        return documents

    # Рекурсивный поиск всех PDF и TXT файлов
    files = list(data_path.rglob("*.pdf")) + list(data_path.rglob("*.txt"))
    print(f"Найдено файлов для индексации: {len(files)}")
    
    for file_path in files:
        try:
            print(f"  Чтение: {file_path.relative_to(data_path)}")
            if file_path.suffix.lower() == ".pdf":
                loader = PyPDFLoader(str(file_path))
            else:
                loader = TextLoader(str(file_path), encoding="utf-8")
            
            docs = loader.load()
            # Добавим относительный путь в метаданные для удобства ссылок на источники
            for d in docs:
                d.metadata["source"] = str(file_path.relative_to(data_path.parent))
            documents.extend(docs)
        except Exception as e:
            print(f"  Ошибка при чтении {file_path}: {e}")
            
    return documents

def main():
    print("=== [1/4] Загрузка документов ===")
    documents = load_documents(DATA_DIR)
    
    if not documents:
        print("Документы не найдены. Поместите PDF или TXT файлы в папку data/.")
        return

    print(f"Всего загружено страниц/документов: {len(documents)}")

    print("\n=== [2/4] Разделение на фрагменты (чанки) ===")
    # chunk_size: размер фрагмента в символах
    # chunk_overlap: перекрытие между соседними фрагментами для сохранения контекста
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""]
    )
    chunks = text_splitter.split_documents(documents)
    print(f"Создано фрагментов текста: {len(chunks)}")

    print(f"\n=== [3/4] Инициализация модели эмбеддингов ({EMBEDDING_MODEL}) ===")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"}  # или "cuda" при наличии видеокарты NVIDIA
    )

    print(f"\n=== [4/4] Сохранение векторов в базу ChromaDB ({CHROMA_DIR}) ===")
    # Создаем и сохраняем базу данных
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DIR
    )
    
    print("\n✅ Готово! Векторная база данных успешно сформирована.")
    print("Теперь можно запускать скрипт для общения с ИИ: python rag_chat.py")

if __name__ == "__main__":
    main()