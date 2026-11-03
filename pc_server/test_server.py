#!/usr/bin/env python3
"""
Comprehensive automated test suite for RTX 4070 PC Server.
Verifies all 6 required endpoints, OpenAI API contracts, SSE streaming,
768-dim embeddings, VRAM state transitions, and optional API key security.
"""

import json
import os
import sys
from pathlib import Path
import unittest

# Add current directory to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from fastapi.testclient import TestClient
from server import app, model_manager, embedding_engine
import auth


class TestPCServerAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Reset auth to none by default for tests
        os.environ.pop("PC_SERVER_API_KEY", None)

    def test_01_root_and_health(self):
        """Test root info and initial /health response."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("service"), "RTX 4070 Remote Inference Server")

        # Health endpoint
        health_resp = self.client.get("/health")
        self.assertEqual(health_resp.status_code, 200)
        h = health_resp.json()
        self.assertEqual(h.get("status"), "online")
        self.assertTrue(h.get("embedding_active"))
        self.assertIn("loaded_llm", h)
        self.assertIn("ctx_size", h)
        self.assertIn("uptime_sec", h)

    def test_02_admin_models_and_switch(self):
        """Test listing models and hot-swapping model with context size."""
        # 1. List models
        resp = self.client.get("/admin/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("available_gguf", data)
        self.assertIsInstance(data["available_gguf"], list)
        self.assertTrue(len(data["available_gguf"]) > 0)

        target_model = data["available_gguf"][0]

        # 2. Switch model
        switch_payload = {"model": target_model, "ctx_size": 32768}
        switch_resp = self.client.post("/admin/switch", json=switch_payload)
        self.assertEqual(switch_resp.status_code, 200)
        switch_data = switch_resp.json()
        self.assertEqual(switch_data.get("status"), "ready")
        self.assertEqual(switch_data.get("model"), target_model)
        self.assertEqual(switch_data.get("ctx_size"), 32768)

        # 3. Verify health reflected the switch
        h = self.client.get("/health").json()
        self.assertEqual(h.get("loaded_llm"), target_model)
        self.assertEqual(h.get("ctx_size"), 32768)

    def test_03_chat_completions_non_streaming(self):
        """Test OpenAI-compatible non-streaming chat completions."""
        payload = {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Explain GPU offloading."},
            ],
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 256,
        }
        resp = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("id", data)
        self.assertEqual(data.get("object"), "chat.completion")
        self.assertIn("choices", data)
        self.assertEqual(len(data["choices"]), 1)
        choice = data["choices"][0]
        self.assertEqual(choice["message"]["role"], "assistant")
        self.assertTrue(len(choice["message"]["content"]) > 0)
        self.assertEqual(choice.get("finish_reason"), "stop")
        self.assertIn("usage", data)

    def test_04_chat_completions_streaming_sse(self):
        """Test OpenAI-compatible SSE streaming chat completions."""
        payload = {
            "messages": [
                {"role": "user", "content": "Hello RTX 4070!"},
            ],
            "stream": True,
        }
        resp = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers["content-type"])

        raw_lines = resp.text.split("\n\n")
        data_chunks = [line.strip() for line in raw_lines if line.strip().startswith("data:")]
        self.assertTrue(len(data_chunks) >= 3, "Expected at least role, content, and [DONE] chunks")

        # First chunk should set assistant role
        first_payload = json.loads(data_chunks[0].replace("data: ", ""))
        self.assertEqual(first_payload["choices"][0]["delta"].get("role"), "assistant")

        # Final chunk should be [DONE]
        self.assertEqual(data_chunks[-1], "data: [DONE]")

    def test_05_embeddings_768_dimensions(self):
        """Test 768-dimensional float embedding generation (nomic-embed-text-v1.5)."""
        # 1. Single string input
        req_single = {"input": "Deep learning on RTX 4070 GPU", "model": "nomic-embed-text-v1.5"}
        resp = self.client.post("/v1/embeddings", json=req_single)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("object"), "list")
        self.assertEqual(len(data["data"]), 1)
        item0 = data["data"][0]
        self.assertEqual(item0["object"], "embedding")
        self.assertEqual(item0["index"], 0)
        vector0 = item0["embedding"]
        self.assertEqual(len(vector0), 768, f"Expected 768 dimensions, got {len(vector0)}")

        # 2. Batch input
        req_batch = {"input": ["Text chunk A", "Text chunk B"]}
        resp_b = self.client.post("/v1/embeddings", json=req_batch)
        self.assertEqual(resp_b.status_code, 200)
        data_b = resp_b.json()
        self.assertEqual(len(data_b["data"]), 2)
        self.assertEqual(len(data_b["data"][0]["embedding"]), 768)
        self.assertEqual(len(data_b["data"][1]["embedding"]), 768)

    def test_06_unload_and_503_behavior(self):
        """Test VRAM unloading to 0MB and proper 503 response on chat."""
        # Unload
        unload_resp = self.client.post("/admin/unload")
        self.assertEqual(unload_resp.status_code, 200)
        self.assertEqual(unload_resp.json().get("status"), "VRAM freed")

        # Verify /health shows loaded_llm as null / None
        health = self.client.get("/health").json()
        self.assertIsNone(health.get("loaded_llm"))

        # Verify chat completion returns 503 when VRAM is unloaded
        chat_req = {
            "messages": [{"role": "user", "content": "Should fail because VRAM unloaded"}],
            "stream": False,
        }
        chat_resp = self.client.post("/v1/chat/completions", json=chat_req)
        self.assertEqual(chat_resp.status_code, 503)
        err_data = chat_resp.json()
        self.assertIn("error", err_data)

    def test_07_api_key_authentication(self):
        """Test Bearer token security middleware when configured."""
        try:
            # Set secret key
            os.environ["PC_SERVER_API_KEY"] = "sk-test-secret-4070"
            os.environ["PC_SERVER_ALLOW_UNAUTH_HEALTH"] = "true"

            # 1. Health should still succeed if allow_unauth_health is true (for Waybar)
            health_resp = self.client.get("/health")
            self.assertEqual(health_resp.status_code, 200)

            # 2. Admin endpoint without token should fail with 401
            unauth_resp = self.client.get("/admin/models")
            self.assertEqual(unauth_resp.status_code, 401)

            # 3. Admin endpoint with invalid token should fail with 401
            bad_token_resp = self.client.get(
                "/admin/models",
                headers={"Authorization": "Bearer wrong-token"},
            )
            self.assertEqual(bad_token_resp.status_code, 401)

            # 4. Admin endpoint with valid Bearer token should succeed with 200
            good_token_resp = self.client.get(
                "/admin/models",
                headers={"Authorization": "Bearer sk-test-secret-4070"},
            )
            self.assertEqual(good_token_resp.status_code, 200)

            # 5. X-API-Key header fallback should also succeed
            x_api_resp = self.client.get(
                "/admin/models",
                headers={"X-API-Key": "sk-test-secret-4070"},
            )
            self.assertEqual(x_api_resp.status_code, 200)

        finally:
            os.environ.pop("PC_SERVER_API_KEY", None)

    def test_08_gpu_telemetry_endpoint(self):
        """Test /admin/gpu diagnostic endpoint."""
        resp = self.client.get("/admin/gpu")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("gpu_name", data)
        self.assertIn("vram_total_mb", data)


if __name__ == "__main__":
    unittest.main()
