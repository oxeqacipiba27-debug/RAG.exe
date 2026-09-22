"""
ingest.py — Промышленный CLI-скрипт индексации базы документов для Enterprise RAG 2.0.
Использует единый с ядром пайплайн DocumentIngestionPipeline и модель nomic-embed-text-v1.5 (768-D).
"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path

# Настройка UTF-8 для консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("IngestCLI")

from rag_engine import (
    DocumentIngestionPipeline,
    AppConfig,
    EmbeddingDimensionMismatchError,
    CONFIG
)


def run_ingestion(data_dir: str = "data", output_file: str = "rag_index.json"):
    """
    Запуск индексации директории документов с гарантией размерности 768-D.
    """
    print("=" * 70)
    print(" 🚀 Enterprise RAG 2.0 — Индексация документов (Nomic v1.5 strictly 768-D)")
    print("=" * 70)

    config = AppConfig.from_env()
    config.data_dir = data_dir
    config.index_file = output_file

    print(f"[*] Режим окружения: {config.environment}")
    print(f"[*] Модель эмбеддингов: {config.embedding_model} (768-D)")
    print(f"[*] Провайдер эмбеддингов: {config.embedding_provider} (Устройство: {config.embedding_device})")
    print(f"[*] Каталог исходных данных: {Path(config.data_dir).resolve()}")
    print(f"[*] Целевой файл индекса: {Path(config.index_file).resolve()}")
    print("-" * 70)

    pipeline = DocumentIngestionPipeline(config=config)
    try:
        count = pipeline.index_directory(config.data_dir, output_file=config.index_file)
        print("-" * 70)
        print(f"✅ [SUCCESS] Индексация завершена успешно! Всего чанков в индексе: {count}")
        print(f"[*] Файл индекса сохранен: {config.index_file}")
        return count
    except EmbeddingDimensionMismatchError as dim_err:
        logger.critical(f"❌ [CRITICAL DIMENSION ERROR] {dim_err}")
        sys.exit(1)
    except Exception as exc:
        logger.exception(f"❌ [ERROR] Ошибка в процессе индексации: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    target_data = sys.argv[1] if len(sys.argv) > 1 else "data"
    target_index = sys.argv[2] if len(sys.argv) > 2 else "rag_index.json"
    run_ingestion(target_data, target_index)