"""
Unit & Integration tests for SchoolX RAG FastAPI Server.
Tests endpoints: /api/v1/health, /api/v1/telegram/message,
/api/v1/telegram/message/stream, /api/v1/chat/sessions/{chat_id}/reset,
and authentication middleware using Python's standard unittest.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from starlette.testclient import TestClient

from api.app import create_app
from api.session_manager import SessionManager
from rag_engine import Citation, RAGResponse


class TestRAGApiServer(unittest.TestCase):
    """Test suite for FastAPI RAG endpoints."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_sessions.db")
        self.session_mgr = SessionManager(db_path=self.db_path)

        # Mock RAG pipeline with concrete configuration attributes
        self.mock_pipeline = MagicMock()
        self.mock_pipeline.is_ready = True
        self.mock_pipeline.chunks = [MagicMock(), MagicMock()]
        self.mock_pipeline.llm_model = "test-local-model"
        self.mock_pipeline.SYSTEM_PROMPT = "Test system prompt"

        self.mock_config = SimpleNamespace(
            llm_provider="LM_STUDIO",
            llm_model="test-local-model",
            llm_temperature=0.2,
            llm_top_p=0.9,
            llm_max_tokens=1500,
            llm_presence_penalty=0.0,
            embedding_provider="CPU",
            embedding_model="test-embed-model",
            retrieval_top_k=4,
            context_max_chunks=4,
        )
        self.mock_pipeline.config = self.mock_config
        self.mock_pipeline.check_health = MagicMock(return_value=(True, "All systems operational"))

        def fake_query(user_query, chat_history=None):
            return RAGResponse(
                query=user_query,
                query_reformulated=user_query,
                answer=f"Echo: {user_query}",
                citations=[
                    Citation(
                        source="manual.pdf",
                        page=1,
                        quote="Relevant information snippet",
                    )
                ],
                confidence=0.92,
                context_chunks_used=1,
                latency_ms=45.0,
                is_zero_retrieval=False,
            )

        self.mock_pipeline.query = MagicMock(side_effect=fake_query)

        # Retriever mock for streaming
        mock_hit = MagicMock()
        mock_hit.chunk.metadata.source = "manual.pdf"
        mock_hit.chunk.metadata.page = 1
        mock_hit.chunk.text = "Relevant information snippet"
        mock_hit.rerank_score = 0.95

        self.mock_pipeline.retriever = MagicMock()
        self.mock_pipeline.retriever.search = MagicMock(return_value=([mock_hit], "reformulated", False))
        self.mock_pipeline.retriever.reorder_lost_in_the_middle = MagicMock(return_value=[mock_hit])

        self.mock_pipeline.context_assembler = MagicMock()
        self.mock_pipeline.context_assembler.assemble = MagicMock(return_value=("<context>doc</context>", [mock_hit]))

        # Stream chunk mock
        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock(delta=MagicMock(content="Echo: "))]
        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock(delta=MagicMock(content="Answer chunk"))]

        self.mock_pipeline.openai_client = MagicMock()
        self.mock_pipeline.openai_client.chat.completions.create = MagicMock(
            return_value=iter([mock_chunk1, mock_chunk2])
        )

        # Create FastAPI app with no auth by default
        self.env_patcher = patch.dict(os.environ, {"RAG_API_KEY": ""})
        self.env_patcher.start()

        self.app = create_app(pipeline=self.mock_pipeline, session_manager=self.session_mgr)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.env_patcher.stop()
        if hasattr(self, "session_mgr") and self.session_mgr:
            self.session_mgr.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_health_check(self):
        """Test GET /api/v1/health returns 200 and healthy status."""
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["llm_provider"], "LM_STUDIO")
        self.assertTrue(data["llm_healthy"])
        self.assertTrue(data["index_loaded"])
        self.assertEqual(data["total_chunks"], 2)

    def test_telegram_message(self):
        """Test POST /api/v1/telegram/message returns structured answer and citations."""
        payload = {
            "chat_id": 123456,
            "user_id": 987654,
            "message_id": 1,
            "query": "Как подать документы?",
        }
        response = self.client.post("/api/v1/telegram/message", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("answer", data)
        self.assertIn("Echo: Как подать документы?", data["answer"])
        self.assertIsInstance(data["session_id"], str)
        self.assertTrue(len(data["session_id"]) > 0)
        self.assertIsInstance(data["sources"], list)
        self.assertEqual(len(data["sources"]), 1)
        self.assertEqual(data["sources"][0]["source"], "manual.pdf")
        self.assertGreaterEqual(data["latency_ms"], 0)

    def test_chat_completions_alias(self):
        """Test alias endpoint POST /api/v1/chat/completions."""
        payload = {
            "chat_id": 555,
            "user_id": 555,
            "query": "Тестовый вопрос",
        }
        response = self.client.post("/api/v1/chat/completions", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Echo: Тестовый вопрос", data["answer"])

    def test_session_history_and_reset(self):
        """Test session history retention and reset via /api/v1/chat/sessions/{chat_id}/reset."""
        chat_id = "999"
        # First message
        resp1 = self.client.post(
            "/api/v1/telegram/message",
            json={"chat_id": chat_id, "user_id": 999, "query": "Первый вопрос"},
        )
        self.assertEqual(resp1.status_code, 200)

        # Check history has 2 turns (user + assistant)
        history = self.session_mgr.get_history(chat_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Первый вопрос")
        self.assertEqual(history[1]["role"], "assistant")

        # Reset session
        resp_reset = self.client.post(f"/api/v1/chat/sessions/{chat_id}/reset")
        self.assertEqual(resp_reset.status_code, 200)
        data = resp_reset.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(str(data["chat_id"]), chat_id)

        # History should now be empty
        self.assertEqual(len(self.session_mgr.get_history(chat_id)), 0)

    def test_streaming_endpoint(self):
        """Test POST /api/v1/telegram/message/stream returns SSE events."""
        payload = {
            "chat_id": 777,
            "user_id": 777,
            "query": "Стриминговый запрос",
        }
        response = self.client.post("/api/v1/telegram/message/stream", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        content = response.text
        self.assertIn("data:", content)

    def test_authentication_enforcement(self):
        """Test authentication middleware with RAG_API_KEY set."""
        with patch.dict(os.environ, {"RAG_API_KEY": "secure-key-456"}):
            auth_app = create_app(pipeline=self.mock_pipeline, session_manager=self.session_mgr)
            client = TestClient(auth_app)

            # Health is public
            self.assertEqual(client.get("/api/v1/health").status_code, 200)

            # Request without key -> 401
            resp_no_key = client.post(
                "/api/v1/telegram/message",
                json={"chat_id": 1, "user_id": 1, "query": "hello"},
            )
            self.assertEqual(resp_no_key.status_code, 401)

            # Request with invalid key -> 401
            resp_bad_key = client.post(
                "/api/v1/telegram/message",
                json={"chat_id": 1, "user_id": 1, "query": "hello"},
                headers={"X-API-Key": "wrong-key"},
            )
            self.assertEqual(resp_bad_key.status_code, 401)

            # Request with valid X-API-Key -> 200
            resp_ok_header = client.post(
                "/api/v1/telegram/message",
                json={"chat_id": 1, "user_id": 1, "query": "hello"},
                headers={"X-API-Key": "secure-key-456"},
            )
            self.assertEqual(resp_ok_header.status_code, 200)

            # Request with valid Bearer token -> 200
            resp_ok_bearer = client.post(
                "/api/v1/telegram/message",
                json={"chat_id": 1, "user_id": 1, "query": "hello"},
                headers={"Authorization": "Bearer secure-key-456"},
            )
            self.assertEqual(resp_ok_bearer.status_code, 200)

    def test_web_chat_message(self):
        """Test POST /api/v1/chat/message with WebChatMessageRequest (decoupled from Telegram)."""
        payload = {
            "query": "Как работает библиотека?",
            "session_id": "web_test_12345"
        }
        response = self.client.post("/api/v1/chat/message", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("answer", data)
        self.assertIn("Echo: Как работает библиотека?", data["answer"])
        self.assertEqual(data["session_id"], "web_test_12345")
        self.assertIsInstance(data["sources"], list)

    def test_web_chat_stream(self):
        """Test POST /api/v1/chat/stream with WebChatMessageRequest."""
        payload = {
            "query": "Вопрос для веб-стриминга",
            "session_id": "web_stream_test"
        }
        response = self.client.post("/api/v1/chat/stream", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        self.assertIn("data:", response.text)

    def test_web_chat_reset(self):
        """Test POST /api/v1/chat/reset for web sessions."""
        sess_id = "web_to_reset"
        self.client.post("/api/v1/chat/message", json={"query": "Тест", "session_id": sess_id})
        self.assertGreater(len(self.session_mgr.get_history(sess_id)), 0)

        resp = self.client.post("/api/v1/chat/reset", json={"session_id": sess_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertEqual(len(self.session_mgr.get_history(sess_id)), 0)

    def test_widget_assets(self):
        """Test GET /widget.js and GET /widget endpoints."""
        js_resp = self.client.get("/widget.js")
        self.assertEqual(js_resp.status_code, 200)
        self.assertIn("application/javascript", js_resp.headers.get("content-type", ""))
        self.assertIn("rag-widget-container", js_resp.text)

        html_resp = self.client.get("/widget")
        self.assertEqual(html_resp.status_code, 200)
        self.assertIn("text/html", html_resp.headers.get("content-type", ""))
        self.assertIn("Школа № 1468", html_resp.text)


if __name__ == "__main__":
    unittest.main()

