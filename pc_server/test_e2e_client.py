#!/usr/bin/env python3
"""
End-to-End Client Integration Test for RTX 4070 PC Server.
Spins up pc_server on port 8009, invokes Remote4070Client from rag_remote_client.py,
and verifies:
1. Health check & status parsing
2. Listing models
3. Switching model in VRAM
4. Generating 768-dim embeddings via client.embed()
5. Real-time token streaming via client.stream_chat() with RAG context chunks
6. VRAM unload via client.unload_model()
"""

import os
import subprocess
import sys
import time
from pathlib import Path

# Paths
PC_SERVER_DIR = Path(__file__).resolve().parent
REPO_ROOT = PC_SERVER_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from rag_remote_client import Remote4070Client, ServerOfflineError, NoModelLoadedError


def run_e2e_test():
    print("=================================================================")
    print("    Starting End-to-End Integration Test with Remote4070Client   ")
    print("=================================================================")

    test_port = 8009
    env = os.environ.copy()
    env["PC_SERVER_PORT"] = str(test_port)
    env["PC_SERVER_HOST"] = "127.0.0.1"
    env["PC_SERVER_DEFAULT_MODEL"] = "Qwen2.5-14B-Instruct-Q4_K_M.gguf"

    # Start server in background
    print(f"\n[1/6] Launching PC Server on 127.0.0.1:{test_port}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(test_port)],
        cwd=str(PC_SERVER_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for server to listen
        time.sleep(1.5)
        client = Remote4070Client(host="127.0.0.1", port=test_port)

        # 1. Health Check
        print("\n[2/6] Verifying client.check_health()...")
        health = client.check_health()
        print(f"  ✔ Status: {health.get('status')}")
        print(f"  ✔ Loaded LLM: {health.get('loaded_llm')}")
        assert health.get("status") == "online", "Server status must be online"
        assert health.get("embedding_active") is True, "Embedding service must be active"

        # 2. List Models
        print("\n[3/6] Verifying client.list_models()...")
        models = client.list_models()
        print(f"  ✔ Available GGUF: {models.get('available_gguf')}")
        print(f"  ✔ Active LLM: {models.get('active_llm')}")
        assert len(models.get("available_gguf", [])) > 0

        # 3. Embedding Generation (768-dim)
        print("\n[4/6] Verifying client.embed() 768-dim vectors...")
        texts = [
            "Arch Linux client communicates with Windows 11 RTX 4070 inference host.",
            "Tailscale WireGuard mesh encrypts cross-network inference traffic.",
        ]
        vectors = client.embed(texts)
        print(f"  ✔ Generated {len(vectors)} embeddings.")
        print(f"  ✔ Vector dimension: {len(vectors[0])} floats.")
        assert len(vectors) == 2
        assert len(vectors[0]) == 768, f"Expected 768 dimensions, got {len(vectors[0])}"

        # 4. Stream Chat with RAG Context
        print("\n[5/6] Verifying client.stream_chat() with RAG context chunks...")
        context = [
            "The RTX 4070 features 5888 CUDA cores and 12GB of GDDR6X VRAM.",
            "Tailscale uses WireGuard to establish direct point-to-point connections through NATs.",
        ]
        query = "How much VRAM does the RTX 4070 have?"
        print(f"  User Query: '{query}'")
        print("  Streamed Tokens: ", end="", flush=True)

        token_count = 0
        collected_tokens = []
        for token in client.stream_chat(user_prompt=query, context_chunks=context):
            print(token, end="", flush=True)
            collected_tokens.append(token)
            token_count += 1
        print(f"\n  ✔ Successfully streamed {token_count} chunks!")
        assert token_count > 0

        # 5. Model Switch & Unload
        print("\n[6/6] Verifying model switch and VRAM unload...")
        client.switch_model("Llama-3.1-8B-Instruct-Q8_0.gguf", ctx_size=8192)
        h_switched = client.check_health()
        assert h_switched.get("loaded_llm") == "Llama-3.1-8B-Instruct-Q8_0.gguf"
        assert h_switched.get("ctx_size") == 8192
        print(f"  ✔ Model switched to: {h_switched.get('loaded_llm')} (ctx: {h_switched.get('ctx_size')})")

        client.unload_model()
        h_unloaded = client.check_health()
        assert h_unloaded.get("loaded_llm") is None
        print("  ✔ Model unloaded, VRAM freed!")

        # Verify stream_chat raises NoModelLoadedError when unloaded
        try:
            for _ in client.stream_chat("Should fail"):
                pass
            assert False, "stream_chat should have raised NoModelLoadedError"
        except NoModelLoadedError:
            print("  ✔ Verified NoModelLoadedError correctly raised when VRAM is unloaded.")

        print("\n=================================================================")
        print("    ALL E2E CLIENT INTEGRATION CHECKS PASSED PERFECTLY!          ")
        print("=================================================================")

    finally:
        # Terminate test server
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    run_e2e_test()
