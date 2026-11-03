#!/usr/bin/env python3
"""
Explicit Edge Cases & Client Integration Test for RTX 4070 Server.
Tests boundary values, empty inputs, rapid concurrent switching,
and end-to-end compatibility with rag_remote_client.py.
"""

import asyncio
import os
import sys
from pathlib import Path
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from fastapi.testclient import TestClient
from server import app, model_manager


class TestEdgeCasesAndClientIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Ensure model is loaded for test cases requiring active inference
        if model_manager.active_model_name is None:
            self.client.post("/admin/switch", json={"model": "Qwen2.5-14B-Instruct-Q4_K_M.gguf"})

    def test_empty_and_whitespace_embeddings(self):
        """Test embedding generation with empty lists, empty strings, and whitespace."""
        # Empty list
        r1 = self.client.post("/v1/embeddings", json={"input": []})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["data"], [])

        # Empty string
        r2 = self.client.post("/v1/embeddings", json={"input": ""})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(r2.json()["data"]), 1)
        self.assertEqual(len(r2.json()["data"][0]["embedding"]), 768)

        # Whitespace-only string
        r3 = self.client.post("/v1/embeddings", json={"input": "   \n\t  "})
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(len(r3.json()["data"][0]["embedding"]), 768)

    def test_extreme_context_sizes(self):
        """Test switching with minimum and extreme context window sizes."""
        # Minimum context
        r_min = self.client.post("/admin/switch", json={"model": "test_model.gguf", "ctx_size": 512})
        self.assertEqual(r_min.status_code, 200)
        self.assertEqual(r_min.json()["ctx_size"], 512)

        # Large 64k context
        r_large = self.client.post("/admin/switch", json={"model": "test_model.gguf", "ctx_size": 65536})
        self.assertEqual(r_large.status_code, 200)
        self.assertEqual(r_large.json()["ctx_size"], 65536)

    def test_empty_messages_chat(self):
        """Test chat completion with empty messages list."""
        r = self.client.post("/v1/chat/completions", json={"messages": [], "stream": False})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("choices", data)

    def test_rapid_switch_and_unload_cycle(self):
        """Test rapid back-to-back switch and unload operations to ensure state consistency."""
        for i in range(5):
            s = self.client.post("/admin/switch", json={"model": f"model_{i}.gguf", "ctx_size": 8192})
            self.assertEqual(s.status_code, 200)
            self.assertEqual(s.json()["model"], f"model_{i}.gguf")

            u = self.client.post("/admin/unload")
            self.assertEqual(u.status_code, 200)
            self.assertEqual(u.json()["status"], "VRAM freed")

        # Health should show unloaded
        h = self.client.get("/health").json()
        self.assertIsNone(h.get("loaded_llm"))

    def test_long_prompt_and_max_tokens_boundary(self):
        """Test very large prompt and token boundaries."""
        self.client.post("/admin/switch", json={"model": "Qwen2.5-14B-Instruct-Q4_K_M.gguf"})
        huge_text = "Tensor core optimization " * 2000
        req = {
            "messages": [
                {"role": "system", "content": "You are a concise AI."},
                {"role": "user", "content": huge_text},
            ],
            "max_tokens": 1,
            "temperature": 0.0,
            "stream": False,
        }
        resp = self.client.post("/v1/chat/completions", json=req)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("choices", resp.json())

    def test_structured_and_null_messages(self):
        """Test OpenAI multimodal structured content and null assistant content."""
        self.client.post("/admin/switch", json={"model": "Qwen2.5-14B-Instruct-Q4_K_M.gguf"})

        # Multimodal structured content list
        req_multimodal = {
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Analyze this architecture"}]}
            ],
            "stream": False,
        }
        r1 = self.client.post("/v1/chat/completions", json=req_multimodal)
        self.assertEqual(r1.status_code, 200)

        # Null content message (e.g. tool call message in history)
        req_null = {
            "messages": [
                {"role": "assistant", "content": None},
                {"role": "user", "content": "Continue answer"}
            ],
            "stream": False,
        }
        r2 = self.client.post("/v1/chat/completions", json=req_null)
        self.assertEqual(r2.status_code, 200)

    def test_stop_tokens_support(self):
        """Test chat completions with custom stop sequences."""
        self.client.post("/admin/switch", json={"model": "Qwen2.5-14B-Instruct-Q4_K_M.gguf"})
        req = {
            "messages": [{"role": "user", "content": "Hello"}],
            "stop": ["\n", "User:"],
            "stream": False,
        }
        resp = self.client.post("/v1/chat/completions", json=req)
        self.assertEqual(resp.status_code, 200)

    def test_remote_client_url_and_auth_parsing(self):
        """Test rag_remote_client.py handling of https URLs, custom ports, and API key."""
        from rag_remote_client import Remote4070Client

        # HTTPS Cloudflare domain
        c_https = Remote4070Client(host="https://my-rag.trycloudflare.com")
        self.assertEqual(c_https.base_url, "https://my-rag.trycloudflare.com")
        self.assertEqual(c_https.port, 443)

        # Direct IP with custom port
        c_ip = Remote4070Client(host="100.84.12.34", port=9000)
        self.assertEqual(c_ip.base_url, "http://100.84.12.34:9000")

        # API Key authorization header
        os.environ["LLM_API_KEY"] = "sk-test-auth-key-123"
        try:
            c_auth = Remote4070Client(host="127.0.0.1", port=8000)
            self.assertEqual(c_auth.api_key, "sk-test-auth-key-123")
            self.assertIn("Authorization", c_auth.http_client.headers)
            self.assertEqual(c_auth.http_client.headers["Authorization"], "Bearer sk-test-auth-key-123")
        finally:
            os.environ.pop("LLM_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
