"""
tests/test_integration_suite.py — Полный интеграционный сквозной тест RAG-системы,
API-сервера, Веб-виджета и Telegram-бота.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

# UTF-8 вывод для Windows консоли
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.app import create_app
from api.session_manager import SessionManager
from ingestion.parsers import (
    NOMIC_DOC_PREFIX,
    NOMIC_QUERY_PREFIX,
    format_nomic_document,
    format_nomic_query,
    load_and_chunk_document,
)
from rag_engine import Citation, PIISanitizer, RAGResponse, sanitize_llm_output
from telegram_bot import split_message_by_length, build_chat_keyboard


class TestFullRAGIntegrationSuite(unittest.TestCase):
    """Сквозной проверочный набор тестов всей системы."""

    @classmethod
    def setUpClass(cls):
        # Инициализация тестового mock-пайплайна
        cls.mock_pipeline = MagicMock()
        cls.mock_pipeline.is_ready = True
        cls.mock_pipeline.chunks = [MagicMock() for _ in range(120)]
        cls.mock_pipeline.llm_model = "qwen2.5-14b-instruct-1m"
        cls.mock_pipeline.SYSTEM_PROMPT = "Системный промпт Школа 1468"

        cls.mock_config = SimpleNamespace(
            llm_provider="LM_STUDIO",
            llm_model="qwen2.5-14b-instruct-1m",
            llm_temperature=0.0,
            llm_top_p=0.2,
            llm_max_tokens=1500,
            llm_presence_penalty=0.1,
            embedding_provider="CPU",
            embedding_model="text-embedding-nomic-embed-text-v1.5",
            retrieval_top_k=5,
            context_max_chunks=6,
        )
        cls.mock_pipeline.config = cls.mock_config
        cls.mock_pipeline.check_health = MagicMock(return_value=(True, "LM Studio OK, VRAM: 8.5 GB, 8192 ctx"))

        def mocked_query(user_query, chat_history=None):
            return RAGResponse(
                query=user_query,
                query_reformulated=user_query,
                answer=f"Для поступления в Школу № 1468 подайте заявление через mos.ru. (Вопрос: {user_query})",
                citations=[
                    Citation(source="Правила_приема_2026.docx", page=2, quote="Запись через mos.ru с 1 апреля."),
                    Citation(source="Устав_школы.pdf", page=5, quote="Прием ведется по территориальному признаку.")
                ],
                confidence=0.96,
                context_chunks_used=2,
                latency_ms=185.4,
                is_zero_retrieval=False
            )

        cls.mock_pipeline.query = MagicMock(side_effect=mocked_query)

        # Session Manager во временной базе
        cls.session_mgr = SessionManager(db_path=":memory:")

        # FastAPI app
        cls.app = create_app(pipeline=cls.mock_pipeline, session_manager=cls.session_mgr)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "session_mgr") and cls.session_mgr:
            cls.session_mgr.close()

    def test_01_api_health_check(self):
        """1. Проверка эндпоинта /health и /api/v1/health."""
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["llm_provider"], "LM_STUDIO")
        self.assertTrue(data["llm_healthy"])
        self.assertEqual(data["total_chunks"], 120)

    def test_02_web_chat_endpoint_lifecycle(self):
        """2. Проверка жизненного цикла диалога через веб-эндпоинт /api/v1/chat/message."""
        session_id = "test_web_session_999"
        
        # Первый вопрос
        resp1 = self.client.post("/api/v1/chat/message", json={
            "query": "Как записаться в школу?",
            "session_id": session_id
        })
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertIn("mos.ru", data1["answer"])
        self.assertEqual(len(data1["sources"]), 2)
        self.assertEqual(data1["sources"][0]["source"], "Правила_приема_2026.docx")
        self.assertEqual(data1["session_id"], session_id)

        # История в менеджере сессий
        hist = self.session_mgr.get_history(session_id)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["role"], "user")
        self.assertEqual(hist[1]["role"], "assistant")

        # Сброс диалога
        reset_resp = self.client.post("/api/v1/chat/reset", json={"session_id": session_id})
        self.assertEqual(reset_resp.status_code, 200)
        self.assertEqual(len(self.session_mgr.get_history(session_id)), 0)

    def test_03_telegram_message_endpoint(self):
        """3. Проверка эндпоинта /api/v1/telegram/message."""
        payload = {
            "chat_id": 445566,
            "user_id": 112233,
            "query": "Какие профильные классы есть?"
        }
        resp = self.client.post("/api/v1/telegram/message", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("mos.ru", data["answer"])
        self.assertGreater(data["confidence"], 0.8)
        self.assertEqual(data["session_id"], self.session_mgr.get_or_create_session_id("445566"))

    def test_04_widget_js_and_html_serving(self):
        """4. Проверка раздачи виджета widget.js и страницы /widget."""
        js_resp = self.client.get("/widget.js")
        self.assertEqual(js_resp.status_code, 200)
        self.assertIn("application/javascript", js_resp.headers.get("content-type", ""))
        self.assertIn("schoolx_rag_session_id", js_resp.text)
        self.assertIn("Школа № 1468", js_resp.text)

        html_resp = self.client.get("/widget")
        self.assertEqual(html_resp.status_code, 200)
        self.assertIn("text/html", html_resp.headers.get("content-type", ""))
        self.assertIn("ГБОУ Школа № 1468", html_resp.text)
        self.assertIn('<script src="/widget.js"', html_resp.text)

    def test_05_nomic_prefix_protocol(self):
        """5. Проверка Nomic v1.5 протокола префиксов эмбеддингов."""
        doc_raw = "Текст документа о правилах перевода."
        formatted_doc = format_nomic_document(doc_raw)
        self.assertTrue(formatted_doc.startswith(NOMIC_DOC_PREFIX))
        # Идемпотентность
        self.assertEqual(format_nomic_document(formatted_doc), formatted_doc)

        query_raw = "Правила перевода в 10 класс"
        formatted_q = format_nomic_query(query_raw)
        self.assertTrue(formatted_q.startswith(NOMIC_QUERY_PREFIX))
        self.assertEqual(format_nomic_query(formatted_q), formatted_q)

    def test_06_pii_sanitization_and_cjk_guard(self):
        """6. Проверка маскирования персональных данных (152-ФЗ) и фильтрации CJK."""
        raw_text_with_pii = (
            "Заявитель: Иванов Иван, тел: +7 (999) 123-45-67, email: test@school1468.ru, "
            "паспорт 4510 123456, СНИЛС 123-456-789 00."
        )
        clean = PIISanitizer.sanitize(raw_text_with_pii)
        self.assertNotIn("+7 (999) 123-45-67", clean)
        self.assertNotIn("test@school1468.ru", clean)
        self.assertNotIn("4510 123456", clean)
        self.assertIn("[PHONE_MASKED]", clean)
        self.assertIn("[EMAIL_MASKED]", clean)
        self.assertIn("[PASSPORT_MASKED]", clean)
        self.assertIn("[SNILS_MASKED]", clean)

        # CJK и галлюцинации
        cjk_text = "Нормативный ответ школы. \u4e2d\u6587\u6d4b\u8bd5 \u65e5\u672c\u8a9e"
        sanitized_cjk = sanitize_llm_output(cjk_text)
        self.assertNotIn("\u4e2d\u6587", sanitized_cjk)
        self.assertIn("Нормативный ответ школы.", sanitized_cjk)

    def test_07_telegram_message_split_safety(self):
        """7. Проверка безопасного разделения сообщений Telegram на чанки <= 4000 символов."""
        long_answer = "Пункт правил. " * 300  # ~4200 символов
        chunks = split_message_by_length(long_answer, max_length=4000)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4000)


if __name__ == "__main__":
    unittest.main()
