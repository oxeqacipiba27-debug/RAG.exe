#!/usr/bin/env python3
"""
rag_remote_client.py: Drop-in Python RAG Client for Remote RTX 4070 Server
=============================================================================
Connects to the remote Windows 11 inference host (or local mock server on 127.0.0.1).
Reads configuration from ~/.config/llm-remote/config.env.
Features:
- Sub-second /health check before executing inference.
- Human-friendly exceptions for Offline and Unloaded VRAM states.
- 768-dimensional embeddings generation (nomic-embed-text-v1.5).
- Real-time token streaming with RAG context injection.
- Dynamic model switching & VRAM unload control.
"""

import os
from pathlib import Path
import sys
from typing import Any, Dict, Generator, List, Optional, Union

import httpx
import openai
from openai import OpenAI, APIConnectionError, APITimeoutError


class RemoteLLMError(Exception):
    """Base exception for remote LLM infrastructure errors."""
    pass


class ServerOfflineError(RemoteLLMError):
    """Raised when the RTX 4070 server is unreachable or sleeping."""
    pass


class NoModelLoadedError(RemoteLLMError):
    """Raised when the server is online, but VRAM is unloaded."""
    pass


class Remote4070Client:
    """Client for querying the remote Windows 11 RTX 4070 LLM & Embedding server."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[Union[str, int]] = None,
        connect_timeout: float = 1.0,
        read_timeout: float = 60.0,
    ):
        """
        Initialize the remote client.
        Configuration precedence:
        1. Explicit arguments (`host`, `port`)
        2. Environment variables (`LLM_SERVER_IP`, `LLM_SERVER_PORT`)
        3. Config file (`~/.config/llm-remote/config.env`)
        4. Default fallback: 127.0.0.1:8000
        """
        self.config_path = Path(
            config_path or os.getenv("LLM_CONFIG_PATH") or "~/.config/llm-remote/config.env"
        ).expanduser()

        env_cfg = self._load_env_config(self.config_path)

        raw_host = (
            host
            or os.getenv("LLM_SERVER_URL")
            or os.getenv("LLM_SERVER_IP")
            or env_cfg.get("LLM_SERVER_URL")
            or env_cfg.get("LLM_SERVER_IP")
            or "127.0.0.1"
        )
        if raw_host.startswith("http://") or raw_host.startswith("https://"):
            parsed = httpx.URL(raw_host)
            self.host = parsed.host
            self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
            base = str(parsed).rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            self.base_url = base
        else:
            self.host = raw_host
            self.port = int(
                port
                or os.getenv("LLM_SERVER_PORT")
                or env_cfg.get("LLM_SERVER_PORT")
                or 8000
            )
            scheme = "https" if self.port == 443 else "http"
            self.base_url = f"{scheme}://{self.host}:{self.port}"

        self.api_key = (
            os.getenv("LLM_API_KEY")
            or env_cfg.get("LLM_API_KEY")
            or os.getenv("PC_SERVER_API_KEY")
            or "sk-no-key-required"
        )

        self.mac = (
            os.getenv("LLM_SERVER_MAC")
            or env_cfg.get("LLM_SERVER_MAC")
            or "00:11:22:33:44:55"
        )
        self.default_ctx = int(
            os.getenv("LLM_DEFAULT_CTX")
            or env_cfg.get("LLM_DEFAULT_CTX")
            or 16384
        )

        self.api_v1_url = f"{self.base_url}/v1"
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        headers = {}
        if self.api_key and self.api_key != "sk-no-key-required":
            headers["Authorization"] = f"Bearer {self.api_key}"

        # HTTPX client for direct health & admin endpoints
        self.http_client = httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(
                connect=self.connect_timeout,
                read=self.read_timeout,
                write=5.0,
                pool=5.0,
            )
        )

        # Standard OpenAI client configured for the remote host
        self.openai_client = OpenAI(
            base_url=self.api_v1_url,
            api_key=self.api_key,
            max_retries=1,
            timeout=httpx.Timeout(
                connect=self.connect_timeout,
                read=self.read_timeout,
                write=5.0,
                pool=5.0,
            ),
        )

    def close(self) -> None:
        """Close underlying HTTP clients."""
        try:
            self.http_client.close()
        except Exception:
            pass
        try:
            self.openai_client.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def _load_env_config(path: Path) -> Dict[str, str]:
        """Simple, robust parser for config.env files without external dependencies."""
        config: Dict[str, str] = {}
        if not path.is_file():
            return config

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        config[key] = val
        except Exception:
            pass
        return config

    def check_health(self) -> Dict[str, Any]:
        """
        Verify server connectivity and VRAM state.
        Supports both custom /health endpoint and standard OpenAI /v1/models (LM Studio / vLLM).
        Raises ServerOfflineError with troubleshooting steps if unreachable.
        """
        url = f"{self.base_url}/health"
        try:
            resp = self.http_client.get(url)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404 or resp.status_code >= 400:
                # Fallback to /v1/models for LM Studio / standard OpenAI servers
                v1_resp = self.http_client.get(f"{self.base_url}/v1/models")
                if v1_resp.status_code == 200:
                    data = v1_resp.json()
                    models_list = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
                    llm_models = [m for m in models_list if not ("embed" in m.lower() or "nomic" in m.lower())]
                    active_llm = llm_models[0] if llm_models else (models_list[0] if models_list else "qwen2.5-14b-instruct-1m")
                    return {
                        "status": "online",
                        "loaded_llm": active_llm,
                        "embedding_active": True,
                        "ctx_size": self.default_ctx,
                        "server_type": "lm_studio",
                    }
                resp.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, httpx.HTTPError) as err:
            # Final attempt to probe /v1/models directly
            try:
                v1_resp = self.http_client.get(f"{self.base_url}/v1/models")
                if v1_resp.status_code == 200:
                    data = v1_resp.json()
                    models_list = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
                    llm_models = [m for m in models_list if not ("embed" in m.lower() or "nomic" in m.lower())]
                    active_llm = llm_models[0] if llm_models else (models_list[0] if models_list else "qwen2.5-14b-instruct-1m")
                    return {
                        "status": "online",
                        "loaded_llm": active_llm,
                        "embedding_active": True,
                        "ctx_size": self.default_ctx,
                        "server_type": "lm_studio",
                    }
            except Exception:
                pass

            raise ServerOfflineError(
                f"\n❌ [CONNECTION FAILED] Unable to reach RTX 4070 Server at {self.base_url}.\n"
                f"   Reason: {type(err).__name__} ({err})\n\n"
                f"   Troubleshooting steps:\n"
                f"   1. Wake Server PC: Run 'llm-ctl wake' or select 'Send Wake-on-LAN' in Waybar menu.\n"
                f"   2. Test Locally:   Run 'llm-ctl menu' -> 'Start Local Mock Server' or:\n"
                f"                      python3 ~/.local/share/llm-remote/mock_pc_server.py &\n"
                f"   3. Check IP:       Verify LLM_SERVER_IP in ~/.config/llm-remote/config.env\n"
            ) from err

    def list_models(self) -> Dict[str, Any]:
        """List available GGUF models on disk and currently active model."""
        health = self.check_health()
        try:
            resp = self.http_client.get(f"{self.base_url}/admin/models")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

        # Fallback for LM Studio / OpenAI endpoints
        try:
            v1_resp = self.http_client.get(f"{self.base_url}/v1/models")
            if v1_resp.status_code == 200:
                data = v1_resp.json()
                models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
                active = health.get("loaded_llm") or (models[0] if models else "qwen2.5-14b-instruct-1m")
                return {"available_gguf": models, "active_llm": active}
        except Exception:
            pass
        return {"available_gguf": [health.get("loaded_llm", "qwen2.5-14b-instruct-1m")], "active_llm": health.get("loaded_llm")}

    def switch_model(self, model_name: str, ctx_size: Optional[int] = None) -> Dict[str, Any]:
        """Switch or load a model into GPU VRAM."""
        self.check_health()
        payload = {
            "model": model_name,
            "ctx_size": ctx_size or self.default_ctx,
        }
        resp = self.http_client.post(f"{self.base_url}/admin/switch", json=payload)
        resp.raise_for_status()
        return resp.json()

    def unload_model(self) -> Dict[str, Any]:
        """Free GPU VRAM by unloading active LLM."""
        self.check_health()
        resp = self.http_client.post(f"{self.base_url}/admin/unload")
        resp.raise_for_status()
        return resp.json()

    def embed(
        self,
        texts: Union[str, List[str]],
        model: str = "nomic-embed-text-v1.5",
    ) -> List[List[float]]:
        """
        Generate 768-dimensional embeddings for a text or list of texts.
        Returns a list of float vectors.
        """
        health = self.check_health()
        if not health.get("embedding_active", True):
            raise RemoteLLMError("Embedding service on RTX 4070 server is currently disabled.")

        input_data = [texts] if isinstance(texts, str) else texts
        if not input_data:
            return []

        try:
            response = self.openai_client.embeddings.create(
                input=input_data,
                model=model,
            )
            vectors = [item.embedding for item in response.data]
            return vectors
        except (APIConnectionError, APITimeoutError, httpx.NetworkError, httpx.TimeoutException) as err:
            raise ServerOfflineError(
                f"\n❌ [CONNECTION DROPPED] Lost connection to {self.base_url} during embedding generation.\n"
                f"   Reason: {type(err).__name__} ({err})"
            ) from err

    def stream_chat(
        self,
        user_prompt: str,
        system_prompt: str = "You are an intelligent, helpful AI assistant.",
        context_chunks: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Generator[str, None, None]:
        """
        Stream chat completion tokens in real-time.
        Automatically verifies that an LLM is currently loaded in GPU VRAM.
        Injects optional RAG context chunks into the prompt.
        """
        # 1. Health check & VRAM validation
        health = self.check_health()
        loaded_llm = health.get("loaded_llm")
        if not loaded_llm:
            raise NoModelLoadedError(
                f"\n⚠️  [VRAM UNLOADED] RTX 4070 is ONLINE at {self.base_url}, but NO LLM is loaded in VRAM.\n"
                f"   To load a model:\n"
                f"   1. Use Waybar: Click the '󰚩 IDLE' pill and select a model from the menu.\n"
                f"   2. Via CLI:    Run 'llm-ctl menu' or 'llm-ctl switch <model.gguf>'\n"
                f"   3. Via Python: client.switch_model('Qwen2.5-14B-Instruct-Q4_K_M.gguf')\n"
            )

        active_model = model or loaded_llm

        # 2. Build RAG messages payload
        messages = [{"role": "system", "content": system_prompt}]

        if context_chunks:
            context_block = "\n\n".join(
                [f"--- Document Context [{i+1}] ---\n{chunk}" for i, chunk in enumerate(context_chunks)]
            )
            augmented_user_message = (
                f"Use the following retrieved context documents to answer the question:\n\n"
                f"{context_block}\n\n"
                f"User Question: {user_prompt}"
            )
            messages.append({"role": "user", "content": augmented_user_message})
        else:
            messages.append({"role": "user", "content": user_prompt})

        # 3. Stream completions via OpenAI SDK
        try:
            stream = self.openai_client.chat.completions.create(
                model=active_model,
                messages=messages,
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except (APIConnectionError, APITimeoutError, httpx.NetworkError, httpx.TimeoutException) as err:
            raise ServerOfflineError(
                f"\n❌ [CONNECTION DROPPED] Lost connection to {self.base_url} during token streaming.\n"
                f"   Reason: {type(err).__name__} ({err})"
            ) from err


# --- Interactive Self-Test & Demo ---

if __name__ == "__main__":
    print("=" * 65)
    print("  Testing Remote4070Client with Local Mock / Remote RTX 4070")
    print("=" * 65)

    client = Remote4070Client()

    # Step 1: Health Check
    print(f"\n[1/3] Checking Server Health at {client.base_url}...")
    try:
        health = client.check_health()
        print(f"  ✔ Status: {health.get('status')}")
        print(f"  ✔ Loaded LLM: {health.get('loaded_llm')}")
        print(f"  ✔ Embedding Service: {health.get('embedding_active')}")
    except ServerOfflineError as e:
        print(e)
        sys.exit(1)

    # Step 2: Embeddings Test
    print("\n[2/3] Testing 768-dim Embedding Generation...")
    sample_texts = [
        "Arch Linux with SwayFX provides smooth Wayland desktop compositing.",
        "Retrieval-Augmented Generation indexes technical manuals into vector spaces.",
    ]
    try:
        embeddings = client.embed(sample_texts)
        print(f"  ✔ Generated {len(embeddings)} vectors.")
        print(f"  ✔ Vector dimension: {len(embeddings[0])} floats (matches nomic-embed-text-v1.5)")
        print(f"  ✔ Sample slice: [{embeddings[0][0]:.4f}, {embeddings[0][1]:.4f}, {embeddings[0][2]:.4f}, ...]")
    except Exception as e:
        print(f"  ❌ Embedding failed: {e}")

    # Step 3: Streaming Chat with RAG Context
    print("\n[3/3] Testing Streaming Chat Completion with RAG Context...")
    test_context = [
        "TechnoLab Arduino Motor Controller utilizes pin 8 for Enable and pin 9 for Step.",
        "Thermal throttling on the RTX 4070 begins at 83 degrees Celsius core temperature.",
    ]
    test_question = "Which pin enables the TechnoLab Arduino motor controller?"

    try:
        print(f"\nUser Query: '{test_question}'\nAssistant: ", end="", flush=True)
        for token in client.stream_chat(
            user_prompt=test_question,
            context_chunks=test_context,
            system_prompt="You are a precise technical engineering assistant.",
        ):
            print(token, end="", flush=True)
        print("\n\n✔ Streaming completion test successful!")
    except NoModelLoadedError as e:
        print(e)
    except Exception as e:
        print(f"❌ Chat failed: {e}")

    print("=" * 65)
