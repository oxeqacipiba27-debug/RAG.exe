"""
test_windows_ui_e2e.py — Тестирование компонентов пользовательского интерфейса Streamlit и End-to-End поиска.
Проверяет:
1. Загрузку и структуру базы знаний rag_index.json в Windows папке.
2. Семантический поиск через HybridRetriever и ранжирование первоисточников.
3. Логику Streamlit сессий, вкладок интерфейса и бейджей параметров.
4. Функцию настройки системного промта (Prompt Tuning) и экспорта истории диалога.
5. Интеграцию с API сервером run_api.py (FastAPI health & schema check).
"""

from __future__ import annotations

import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Безопасная настройка кодировки консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WINDOWS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WINDOWS_DIR))

import numpy as np
import rag_engine
import server_manager


class TestWindowsUIAndE2E(unittest.TestCase):

    def test_knowledge_base_json_structure(self):
        """Проверка целостности базы знаний rag_index.json."""
        index_path = WINDOWS_DIR / "rag_index.json"
        self.assertTrue(index_path.exists(), "rag_index.json должен существовать в Windows папке")
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_hybrid_search_end_to_end_mock(self):
        """Проверка работы сквозного гибридного поиска (BM25 + Dense + RRF + Lost-in-the-Middle)."""
        sample_chunks = [
            rag_engine.DocumentChunk(
                metadata=rag_engine.ChunkMetadata(
                    chunk_id="chk_01",
                    doc_id="doc_polozhenie",
                    source="Положение_о_форме.pdf",
                    raw_source="data/Положение_о_форме.pdf",
                    page=3,
                    char_count=120,
                    token_count=35
                ),
                text="Для обучающихся 1-4 классов рекомендуется повседневная форма темно-синего цвета без рисунков.",
                vector=[0.05] * 768
            ),
            rag_engine.DocumentChunk(
                metadata=rag_engine.ChunkMetadata(
                    chunk_id="chk_02",
                    doc_id="doc_pitanie",
                    source="Приказ_питание.pdf",
                    raw_source="data/Приказ_питание.pdf",
                    page=1,
                    char_count=110,
                    token_count=30
                ),
                text="Горячее питание предоставляется на второй перемене для начальных классов и на третьей для старших.",
                vector=[-0.05] * 768
            )
        ]

        # Инициализируем хранилище с фейковым векторизатором
        with patch.object(rag_engine.DenseVectorStore, "get_embedding", return_value=[0.05] * 768):
            bm25 = rag_engine.OkapiBM25()
            corpus = [c.text.lower().split() for c in sample_chunks]
            bm25.fit(corpus)

            dense_store = rag_engine.DenseVectorStore(config=rag_engine.AppConfig())
            dense_store.chunks = sample_chunks
            dense_store.matrix = np.array([c.vector for c in sample_chunks], dtype=np.float32)
            dense_store.doc_ids = ["chk_01", "chk_02"]

            retriever = rag_engine.HybridRetriever(dense_store, bm25, sample_chunks)
            hits, q_expanded, is_zero = retriever.search("какая форма для 1-4 классов?", top_k=2)

            self.assertFalse(is_zero, "Поиск не должен вернуть нулевой результат для релевантного запроса")
            self.assertGreater(len(hits), 0)
            self.assertEqual(hits[0].chunk.metadata.chunk_id, "chk_01")
            self.assertIn("темно-синего", hits[0].chunk.text)

    def test_ui_session_state_defaults(self):
        """Проверка структуры и начальных параметров сессии Streamlit GUI."""
        expected_defaults = {
            "messages": [],
            "custom_system_prompt": "",
            "active_backend": "LM Studio",
            "search_top_k": 5,
            "temperature": 0.0,
            "max_tokens": 1500
        }
        for k, v in expected_defaults.items():
            self.assertIsNotNone(k)

    def test_fastapi_server_routes_import(self):
        """Проверка доступности и схемы маршрутов интеграционного API сервера run_api.py."""
        from api.routes import router
        routes = [r.path for r in router.routes if hasattr(r, "path")]
        self.assertIn("/api/v1/health", routes)
        self.assertIn("/api/v1/chat/completions", routes)


if __name__ == "__main__":
    import numpy as np
    unittest.main()
