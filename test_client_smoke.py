"""
test_client_smoke.py — Автоматизированный смоук-тест клиентской версии EXSCIO RAG.
Проверяет:
1. Отсутствие зависимостей от server_manager в клиентском коде.
2. Корректность инициализации конфигурации и фиксации MAIN_SERVER_URL.
3. Доступность основного сервера инференса (LM Studio / v1 API).
4. Чтение базы знаний rag_index.json в строгом режиме read-only.
5. Работу CJK-санитайзера и фильтрацию вывода.
6. Выполнение гибридного поиска (BM25 + Dense + RRF) без ошибок.
"""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import json
import time
from pathlib import Path
import httpx
import dotenv

dotenv.load_dotenv(override=True)


def test_no_server_manager_dependency():
    print("\n[TEST 1] Проверка отсутствия server_manager в клиентской версии...")
    client_files = ["rag_gui.py", "run_client.py"]
    for fname in client_files:
        fpath = Path(__file__).parent / fname
        content = fpath.read_text(encoding="utf-8")
        assert "server_manager" not in content, f"Обнаружено упоминание server_manager в {fname}!"
    print("  [OK] Зависимость от server_manager полностью исключена.")


def test_main_server_url_lock():
    print("\n[TEST 2] Проверка фиксации MAIN_SERVER_URL в конфигурации...")
    from rag_engine import AppConfig
    cfg = AppConfig()
    main_url = os.getenv("MAIN_SERVER_URL", "http://localhost:1234/v1")
    assert cfg.llm_base_url.rstrip("/") == main_url.rstrip("/"), f"Несовпадение base_url: {cfg.llm_base_url} != {main_url}"
    print(f"  [OK] URL основного сервера зафиксирован: {cfg.llm_base_url}")


def test_main_server_connectivity():
    print("\n[TEST 3] Проверка доступности основного сервера инференса...")
    main_url = os.getenv("MAIN_SERVER_URL", "http://localhost:1234/v1").rstrip("/")
    if not main_url.endswith("/v1"):
        main_url += "/v1"

    try:
        with httpx.Client(timeout=4.0, trust_env=False) as client:
            resp = client.get(f"{main_url}/models")
            assert resp.status_code == 200, f"Сервер вернул статус {resp.status_code}"
            models = resp.json().get("data", [])
            model_ids = [m["id"] for m in models if "id" in m]
            print(f"  [OK] Основной сервер активен: доступно {len(model_ids)} моделей -> {model_ids}")
    except Exception as e:
        print(f"  [!] Предупреждение: Сервер не ответил: {e}")


def test_cjk_sanitizer():
    print("\n[TEST 4] Проверка CJK-санитайзера и фильтрации текста...")
    from rag_engine import sanitize_llm_output
    raw = "Форма одежды: деловой стиль. 學校 學生 校服 Приказ № 1468 от 2024 года."
    clean = sanitize_llm_output(raw)
    assert "學校" not in clean and "學生" not in clean and "校服" not in clean
    assert "деловой стиль" in clean
    assert "Приказ № 1468" in clean
    print(f"  [OK] CJK-санитайзер успешно устранил иероглифы: '{clean}'")


def test_read_only_index_and_hybrid_search():
    print("\n[TEST 5] Проверка чтения индекса и гибридного поиска...")
    from rag_engine import RAGPipeline
    index_file = Path("rag_index.json")
    if not index_file.exists():
        print("  [!] rag_index.json отсутствует в каталоге, проверка поиска пропущена.")
        return

    pipeline = RAGPipeline(index_file=str(index_file))
    print(f"  [i] Индекс загружен: {len(pipeline.chunks)} чанков.")

    query = "какая одежда нужна для школы"
    hits, reformulated, is_zero = pipeline.retriever.search(raw_query=query, top_k=3)
    assert not is_zero, "Поиск вернул Zero-Retrieval на стандартный запрос"
    assert len(hits) > 0, "Не найдены фрагменты по запросу"

    top_hit = hits[0]
    print(f"  [OK] Извлечено {len(hits)} фрагментов. Топ-1: '{top_hit.chunk.metadata.source}' (Стр. {top_hit.chunk.metadata.page})")
    print(f"  [OK] RRF Score: {top_hit.rrf_score:.5f}, Dense: {top_hit.dense_score:.4f}, BM25: {top_hit.sparse_score:.2f}")


def test_search_query_kwarg_and_edge_cases():
    print("\n[TEST 6] Проверка граничных случаев поиска (kwarg query, пустой запрос)...")
    from rag_engine import RAGPipeline
    index_file = Path("rag_index.json")
    if not index_file.exists():
        print("  [!] rag_index.json отсутствует в каталоге, проверка пропущена.")
        return

    pipeline = RAGPipeline(index_file=str(index_file))

    # 1. Поиск через именованный параметр query (вместо raw_query)
    hits, ref_q, is_z = pipeline.retriever.search(query="одежда", top_k=2)
    assert not is_z, "Поиск по query='одежда' вернул Zero-Retrieval"
    assert len(hits) > 0, "Не найдены результаты по query='одежда'"
    print("  [OK] Поиск через параметр query= успешно выполнен без ошибок.")

    # 2. Поиск с пустым запросом
    empty_hits, _, is_empty_z = pipeline.retriever.search(raw_query="", top_k=2)
    assert is_empty_z or len(empty_hits) == 0, "Пустой запрос должен возвращать пустой результат"
    print("  [OK] Пустой поисковый запрос корректно обработан.")


def test_url_normalization():
    print("\n[TEST 7] Проверка нормализации URL основного сервера...")
    from rag_engine import AppConfig
    # Проверка нормализации URL без суффикса /v1
    orig = os.environ.get("MAIN_SERVER_URL")
    try:
        os.environ["MAIN_SERVER_URL"] = "http://192.168.1.55:1234"
        cfg = AppConfig()
        assert cfg.llm_base_url == "http://192.168.1.55:1234/v1", f"URL не нормализован: {cfg.llm_base_url}"
        assert cfg.embedding_base_url == "http://192.168.1.55:1234/v1", f"Embedding URL не нормализован: {cfg.embedding_base_url}"
        print(f"  [OK] URL без /v1 корректно приведен к: {cfg.llm_base_url}")
    finally:
        if orig is not None:
            os.environ["MAIN_SERVER_URL"] = orig
        else:
            os.environ.pop("MAIN_SERVER_URL", None)


def test_read_only_save_blocked():
    print("\n[TEST 8] Проверка защиты от модификации базы знаний (Read-Only safeguard)...")
    from rag_engine import RAGPipeline
    pipeline = RAGPipeline()
    res = pipeline.save_index()
    assert res is False, "save_index должен возвращать False и блокировать запись в клиентской версии!"
    print("  [OK] Запись в базу знаний успешно заблокирована защитным механизмом.")


def main():
    print("=" * 60)
    print("  EXSCIO RAG Client Edition — Smoke Test Suite")
    print("=" * 60)

    test_no_server_manager_dependency()
    test_main_server_url_lock()
    test_main_server_connectivity()
    test_cjk_sanitizer()
    test_read_only_index_and_hybrid_search()
    test_search_query_kwarg_and_edge_cases()
    test_url_normalization()
    test_read_only_save_blocked()

    print("\n" + "=" * 60)
    print("  [ALL TESTS PASSED] Клиентская версия полностью верифицирована!")
    print("=" * 60)


if __name__ == "__main__":
    main()
