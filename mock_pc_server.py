#!/usr/bin/env python3
"""
Local Mock Server simulating Windows 11 RTX 4070 Server (Port 8000)
Provides complete API parity with the remote inference host:
- GET  /health
- GET  /admin/models
- POST /admin/switch
- POST /admin/unload
- POST /v1/chat/completions (OpenAI-compatible, SSE streaming + non-streaming)
- POST /v1/embeddings (OpenAI-compatible 768-dim nomic-embed-text-v1.5)
"""

import asyncio
import hashlib
import json
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="RTX 4070 Mock Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MockServerState:
    def __init__(self):
        self.available_gguf: List[str] = [
            "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
            "Llama-3.1-8B-Instruct-Q8_0.gguf",
            "DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
            "Mistral-Nemo-Instruct-2407-Q5_K_M.gguf",
        ]
        self.active_llm: Optional[str] = "Qwen2.5-14B-Instruct-Q4_K_M.gguf"
        self.ctx_size: int = 16384
        self.embedding_active: bool = True
        self.start_time: float = time.time()


state = MockServerState()


# --- Request & Response Models ---

class SwitchModelRequest(BaseModel):
    model: str
    ctx_size: Optional[int] = 16384


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1024


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: Optional[str] = "nomic-embed-text-v1.5"


# --- Helper Functions ---

def generate_pseudo_embedding(text: str, dim: int = 768) -> List[float]:
    """Generates a deterministic, normalized 768-dimensional float vector for input text."""
    seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
    seed_int = int.from_bytes(seed_bytes[:8], byteorder="big")

    raw_vals: List[float] = []
    current = seed_int
    for _ in range(dim):
        current = (current * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        val = ((current % 200000) / 100000.0) - 1.0
        raw_vals.append(val)

    norm = math.sqrt(sum(x * x for x in raw_vals)) or 1.0
    return [round(x / norm, 6) for x in raw_vals]


# --- API Endpoints ---

@app.get("/health")
@app.get("/v1/health")
def get_health() -> Dict[str, Any]:
    """Health check endpoint used by Waybar and RAG client."""
    return {
        "status": "online",
        "loaded_llm": state.active_llm,
        "embedding_active": state.embedding_active,
        "ctx_size": state.ctx_size,
        "uptime_sec": int(time.time() - state.start_time),
    }


@app.get("/admin/models")
@app.get("/v1/admin/models")
def get_models() -> Dict[str, Any]:
    """List available GGUF models on disk and currently active model."""
    return {
        "available_gguf": state.available_gguf,
        "active_llm": state.active_llm,
    }


@app.get("/v1/models")
def get_v1_models() -> Dict[str, Any]:
    """OpenAI-compatible models list endpoint."""
    return {
        "object": "list",
        "data": [
            {
                "id": m,
                "object": "model",
                "created": int(state.start_time),
                "owned_by": "exscio-rtx4070",
            }
            for m in state.available_gguf
        ],
    }


@app.post("/admin/switch")
@app.post("/v1/admin/switch")
def switch_model(payload: SwitchModelRequest) -> Dict[str, Any]:
    """Switch active LLM loaded in VRAM."""
    model_name = payload.model
    if model_name not in state.available_gguf:
        state.available_gguf.append(model_name)
    state.active_llm = model_name
    state.ctx_size = payload.ctx_size or 16384
    return {
        "status": "ready",
        "model": state.active_llm,
        "ctx_size": state.ctx_size,
    }


@app.post("/admin/unload")
@app.post("/v1/admin/unload")
def unload_model() -> Dict[str, Any]:
    """Free VRAM by unloading active LLM."""
    state.active_llm = None
    return {"status": "VRAM freed"}


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    """OpenAI-compatible chat completion endpoint supporting SSE streaming."""
    if state.active_llm is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "message": "No LLM loaded in RTX 4070 VRAM. Call /admin/switch to load a model.",
                    "type": "model_not_loaded",
                    "code": 503,
                }
            },
        )

    # Extract user message content
    user_query = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            user_query = msg.content
            break
    if not user_query:
        user_query = req.messages[-1].content if req.messages else "test query"

    model_name = req.model or state.active_llm
    completion_id = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"
    created_ts = int(time.time())

    # Realistic simulated assistant response
    sample_response_text = (
        f"[Mock RTX 4070 ({model_name})]: "
        f"Inference request processed successfully with context window {state.ctx_size}. "
        f"Query acknowledged: '{user_query[:50]}...'. "
        f"Local RAG vector search and GPU tensor pipeline are fully operational."
    )

    if req.stream:
        async def event_generator():
            words = sample_response_text.split(" ")
            # First chunk: role
            first_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(first_chunk)}\n\n"
            await asyncio.sleep(0.04)

            # Subsequent chunks: tokens
            for i, word in enumerate(words):
                prefix = "" if i == 0 else " "
                token = prefix + word
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": token},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0.03)

            # Stop chunk
            finish_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(finish_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    else:
        # Non-streaming response
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": sample_response_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": max(len(user_query.split()), 1),
                "completion_tokens": len(sample_response_text.split()),
                "total_tokens": max(len(user_query.split()), 1) + len(sample_response_text.split()),
            },
        }


@app.post("/v1/embeddings")
@app.post("/embeddings")
def embeddings(req: EmbeddingRequest) -> Dict[str, Any]:
    """OpenAI-compatible embeddings endpoint returning 768-dim float vectors."""
    if not state.embedding_active:
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Embedding service inactive", "type": "server_error"}},
        )

    inputs = [req.input] if isinstance(req.input, str) else req.input
    data_items = []
    total_tokens = 0

    for idx, text in enumerate(inputs):
        vec = generate_pseudo_embedding(text, dim=768)
        data_items.append({
            "object": "embedding",
            "index": idx,
            "embedding": vec,
        })
        total_tokens += max(len(text.split()), 1)

    return {
        "object": "list",
        "data": data_items,
        "model": req.model or "nomic-embed-text-v1.5",
        "usage": {
            "prompt_tokens": total_tokens,
            "total_tokens": total_tokens,
        },
    }


if __name__ == "__main__":
    print("Starting RTX 4070 Mock Server on http://127.0.0.1:8000 ...")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
