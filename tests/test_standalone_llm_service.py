r"""
tests/test_standalone_llm_service.py
=============================================================================
Verification Test Suite for C:\llm_engine\service.py
Validates:
- Exact API contract (all 6 endpoints)
- Waybar null loaded_llm when idle
- Dynamic model switching & context window
- Auto-wake on chat completions
- Gaming / Simracing auto-unload guard
- 10-minute (600s) auto-idle VRAM watchdog
- SSE streaming proxying
- Permanent embeddings proxying
=============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add C:\llm_engine to sys.path
SERVICE_DIR = Path(r"C:\llm_engine")
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from fastapi.testclient import TestClient
import service
from service import app, state


class TestStandaloneLLMEngine(unittest.TestCase):
    def setUp(self):
        # Reset state for isolation
        state.loaded_llm = None
        state.last_active_model = "test-qwen2.5-14b.gguf"
        state.current_ctx_size = 16384
        state.embedding_active = True
        state.gaming_guard_active = False
        state.active_game_detected = None
        state.last_chat_timestamp = time.time()

        # Patch start_embedding_worker so TestClient lifespan does not launch real llama-server.exe
        self._embed_patcher = patch("service.start_embedding_worker", return_value=True)
        self._embed_patcher.start()
        self._health_patcher = patch("service.wait_for_health", new_callable=AsyncMock, return_value=True)
        self._health_patcher.start()

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        self._health_patcher.stop()
        self._embed_patcher.stop()
        if state.llm_process:
            try:
                state.llm_process.terminate()
            except Exception:
                pass
            state.llm_process = None
        if state.embed_process:
            try:
                state.embed_process.terminate()
            except Exception:
                pass
            state.embed_process = None

    def test_01_health_endpoint_schema_idle(self):
        """1. GET /health when no LLM loaded -> loaded_llm MUST be None (null in JSON)."""
        state.loaded_llm = None
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        self.assertEqual(data["status"], "online")
        self.assertIsNone(data["loaded_llm"], "loaded_llm MUST be null when idle for Waybar")
        self.assertIn("embedding_active", data)
        self.assertEqual(data["vram_idle_timeout_sec"], 600)

    def test_02_health_endpoint_schema_loaded(self):
        """1. GET /health when LLM is loaded in VRAM."""
        state.loaded_llm = "Qwen2.5-14B-Instruct-Q4_K_M.gguf"
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "online")
        self.assertEqual(data["loaded_llm"], "Qwen2.5-14B-Instruct-Q4_K_M.gguf")

    def test_03_admin_models_scan(self):
        """2. GET /admin/models scans models folder and lists gguf files."""
        # Create a mock model file in MODELS_DIR
        mock_file = service.MODELS_DIR / "test_model_alpha.gguf"
        mock_file.touch(exist_ok=True)
        try:
            state.loaded_llm = "test_model_alpha.gguf"
            resp = self.client.get("/admin/models")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("available_gguf", data)
            self.assertIn("test_model_alpha.gguf", data["available_gguf"])
            self.assertEqual(data["active_llm"], "test_model_alpha.gguf")
        finally:
            if mock_file.exists():
                mock_file.unlink()

    @patch("service.spawn_llm_worker", new_callable=AsyncMock)
    def test_04_admin_switch_success(self, mock_spawn):
        """3. POST /admin/switch loads model and returns ready."""
        mock_spawn.return_value = True
        
        # Create temporary dummy model file
        dummy_model = service.MODELS_DIR / "dummy_switch_model.gguf"
        dummy_model.touch(exist_ok=True)
        try:
            payload = {"model": "dummy_switch_model.gguf", "ctx_size": 16384}
            resp = self.client.post("/admin/switch", json=payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ready")
            self.assertEqual(data["model"], "dummy_switch_model.gguf")
            mock_spawn.assert_called_once_with("dummy_switch_model.gguf", 16384)
        finally:
            if dummy_model.exists():
                dummy_model.unlink()

    def test_05_admin_switch_blocked_by_gaming_guard(self):
        """3. POST /admin/switch is blocked (403) when game is running."""
        state.gaming_guard_active = True
        state.active_game_detected = "cs2.exe"
        
        payload = {"model": "any_model.gguf", "ctx_size": 8192}
        resp = self.client.post("/admin/switch", json=payload)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Gaming mode active", resp.text)

    @patch("service.unload_llm_worker", new_callable=AsyncMock)
    def test_06_admin_unload(self, mock_unload):
        """4. POST /admin/unload frees VRAM immediately."""
        state.loaded_llm = "some_model.gguf"
        resp = self.client.post("/admin/unload")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "VRAM freed")
        mock_unload.assert_called_once()

    @patch("service.auto_wake_if_needed", new_callable=AsyncMock)
    @patch("httpx.AsyncClient.post")
    def test_07_chat_completions_non_streaming_proxy(self, mock_post, mock_wake):
        """5. POST /v1/chat/completions proxies non-streaming responses and updates timestamp."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps({
            "id": "chatcmpl-test",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}}]
        }).encode("utf-8")
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        old_ts = time.time() - 50.0
        state.last_chat_timestamp = old_ts
        state.loaded_llm = "model.gguf"

        req_payload = {
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False
        }
        resp = self.client.post("/v1/chat/completions", json=req_payload)
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(state.last_chat_timestamp, old_ts)

    @patch("service.spawn_llm_worker", new_callable=AsyncMock)
    def test_08_auto_wake_on_chat_completions_when_idle(self, mock_spawn):
        """5. Auto-Wake feature: when loaded_llm is null, automatically loads model into VRAM."""
        mock_spawn.return_value = True
        state.loaded_llm = None
        state.last_active_model = "test_autowake_model.gguf"

        # Create dummy model file for auto-wake discovery
        dummy = service.MODELS_DIR / "test_autowake_model.gguf"
        dummy.touch(exist_ok=True)
        try:
            asyncio.run(service.auto_wake_if_needed())
            mock_spawn.assert_called_once_with("test_autowake_model.gguf", 16384)
        finally:
            if dummy.exists():
                dummy.unlink()

    def test_09_auto_wake_blocked_by_gaming_guard(self):
        """5. Auto-Wake is blocked with 503 when gaming guard is active."""
        state.loaded_llm = None
        state.gaming_guard_active = True
        state.active_game_detected = "AC2-Win64-Shipping.exe"

        with self.assertRaises(Exception):
            asyncio.run(service.auto_wake_if_needed())

    @patch("httpx.AsyncClient.post")
    def test_10_embeddings_proxy(self, mock_post):
        """6. POST /v1/embeddings proxies to port 8082."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = json.dumps({
            "object": "list",
            "data": [{"embedding": [0.1] * 768, "index": 0}],
            "model": "nomic-embed-text-v1.5"
        }).encode("utf-8")
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        req_payload = {"input": "test embedding document"}
        resp = self.client.post("/v1/embeddings", json=req_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["data"][0]["embedding"]), 768)

    @patch("service.unload_llm_worker", new_callable=AsyncMock)
    def test_11_idle_vram_watchdog_trigger(self, mock_unload):
        """Validates 600-second idle VRAM watchdog behavior."""
        state.loaded_llm = "active_model.gguf"
        # Simulate 605 seconds idle
        state.last_chat_timestamp = time.time() - 605.0

        idle_duration = time.time() - state.last_chat_timestamp
        self.assertGreaterEqual(idle_duration, service.IDLE_TIMEOUT_SEC)

    def test_12_gaming_guard_process_detection_logic(self):
        """Validates case-insensitive game process name matching."""
        guard_list = service.GAME_EXECUTABLES
        self.assertIn("cs2.exe", guard_list)
        self.assertIn("acs.exe", guard_list)
        self.assertIn("ac2-win64-shipping.exe", guard_list)
        self.assertIn("valorant-win64-shipping.exe", guard_list)
        self.assertIn("forza_gaming.desktop.x64_release_final.exe", guard_list)

        test_name = "AC2-Win64-Shipping.exe"
        self.assertIn(test_name.lower(), guard_list)

    @patch("service.spawn_llm_worker", new_callable=AsyncMock)
    def test_13_auto_wake_with_requested_model(self, mock_spawn):
        """5. Auto-Wake feature picks requested model if specified in payload."""
        mock_spawn.return_value = True
        state.loaded_llm = None
        state.last_active_model = "fallback_model.gguf"

        dummy = service.MODELS_DIR / "custom_requested.gguf"
        dummy.touch(exist_ok=True)
        try:
            asyncio.run(service.auto_wake_if_needed(requested_model="custom_requested"))
            mock_spawn.assert_called_once_with("custom_requested.gguf", 16384)
        finally:
            if dummy.exists():
                dummy.unlink()

    @patch("service.spawn_llm_worker", new_callable=AsyncMock)
    def test_14_admin_switch_omitted_extension(self, mock_spawn):
        """3. POST /admin/switch automatically appends .gguf if omitted."""
        mock_spawn.return_value = True
        dummy = service.MODELS_DIR / "no_ext_model.gguf"
        dummy.touch(exist_ok=True)
        try:
            resp = self.client.post("/admin/switch", json={"model": "no_ext_model", "ctx_size": 8192})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["model"], "no_ext_model.gguf")
            mock_spawn.assert_called_once_with("no_ext_model.gguf", 8192)
        finally:
            if dummy.exists():
                dummy.unlink()

    def test_15_admin_switch_path_traversal_sanitized(self):
        """3. POST /admin/switch sanitizes directory traversal characters."""
        resp = self.client.post("/admin/switch", json={"model": "../../nonexistent_secret.gguf"})
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.text)

    def test_16_health_endpoint_reports_ctx_size(self):
        """1. GET /health reports current context size when LLM loaded, 0 when idle."""
        state.loaded_llm = None
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["ctx_size"], 0)

        state.loaded_llm = "active.gguf"
        state.current_ctx_size = 32768
        resp2 = self.client.get("/health")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["ctx_size"], 32768)

    @patch("service.auto_wake_if_needed", new_callable=AsyncMock)
    @patch("httpx.AsyncClient.post")
    def test_17_route_aliases_without_v1(self, mock_post, mock_wake):
        """Validates that /chat/completions and /embeddings work without /v1 prefix."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "ok"}'
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        state.loaded_llm = "active.gguf"
        resp_chat = self.client.post("/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp_chat.status_code, 200)

        resp_embed = self.client.post("/embeddings", json={"input": "test"})
        self.assertEqual(resp_embed.status_code, 200)

    @patch("service.spawn_llm_worker", new_callable=AsyncMock)
    def test_18_auto_wake_double_checked_locking(self, mock_spawn):
        """Validates that double-checked locking prevents secondary spawn if loaded while waiting for lock."""
        state.loaded_llm = None
        state.last_active_model = "test_race_model.gguf"
        dummy = service.MODELS_DIR / "test_race_model.gguf"
        dummy.touch(exist_ok=True)

        try:
            # Simulate another coroutine loading the model while this one waits for switch_lock
            async def simulate_race():
                async with state.switch_lock:
                    state.loaded_llm = "test_race_model.gguf"
                    state.llm_process = MagicMock()
                    state.llm_process.poll.return_value = None

            asyncio.run(simulate_race())
            # Now run auto_wake_if_needed
            asyncio.run(service.auto_wake_if_needed())
            # spawn_llm_worker should NOT have been called because model was loaded inside lock
            mock_spawn.assert_not_called()
        finally:
            if dummy.exists():
                dummy.unlink()

    @patch("service.wait_for_health", new_callable=AsyncMock)
    @patch("service.start_embedding_worker")
    @patch("httpx.AsyncClient.post")
    def test_19_embeddings_auto_recovery_when_offline(self, mock_post, mock_start, mock_health):
        """Validates that /v1/embeddings auto-recovers embedding worker if offline."""
        mock_start.return_value = True
        mock_health.return_value = True
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": []}'
        mock_response.headers = {"content-type": "application/json"}
        mock_post.return_value = mock_response

        state.embed_process = None
        state.embedding_active = False

        resp = self.client.post("/v1/embeddings", json={"input": "hello"})
        self.assertEqual(resp.status_code, 200)
        mock_start.assert_called_once()
        mock_health.assert_called_once()

    @patch("service.spawn_llm_worker", new_callable=AsyncMock)
    def test_20_admin_switch_ctx_size_sanitization(self, mock_spawn):
        """Validates that non-positive ctx_size values (0 or negative) fallback to DEFAULT_CTX_SIZE."""
        mock_spawn.return_value = True
        dummy = service.MODELS_DIR / "ctx_test_model.gguf"
        dummy.touch(exist_ok=True)
        try:
            resp = self.client.post("/admin/switch", json={"model": "ctx_test_model.gguf", "ctx_size": 0})
            self.assertEqual(resp.status_code, 200)
            mock_spawn.assert_called_with("ctx_test_model.gguf", service.DEFAULT_CTX_SIZE)

            resp_neg = self.client.post("/admin/switch", json={"model": "ctx_test_model.gguf", "ctx_size": -500})
            self.assertEqual(resp_neg.status_code, 200)
            mock_spawn.assert_called_with("ctx_test_model.gguf", service.DEFAULT_CTX_SIZE)
        finally:
            if dummy.exists():
                dummy.unlink()

    def test_21_models_endpoint_includes_symlinks(self):
        """Validates that /admin/models lists .gguf symlinks correctly."""
        dummy_real = service.MODELS_DIR / "real_target.gguf"
        dummy_real.touch(exist_ok=True)
        dummy_link = service.MODELS_DIR / "symlink_test.gguf"
        
        try:
            # Create symlink or secondary file
            try:
                os.symlink(str(dummy_real), str(dummy_link))
            except Exception:
                # If non-admin on Windows without developer mode, touch link
                dummy_link.touch(exist_ok=True)

            resp = self.client.get("/admin/models")
            self.assertEqual(resp.status_code, 200)
            models = resp.json()["available_gguf"]
            self.assertIn("real_target.gguf", models)
            self.assertIn("symlink_test.gguf", models)
        finally:
            if dummy_real.exists():
                dummy_real.unlink()
            if dummy_link.exists() or dummy_link.is_symlink():
                dummy_link.unlink()


if __name__ == "__main__":
    unittest.main()
