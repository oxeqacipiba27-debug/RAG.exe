"""
Pydantic schemas for the RTX 4070 PC Server REST API.
Maintains exact parity with OpenAI SDK and the Arch Linux client contract.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


# --- Health & Admin Schemas ---

class HealthResponse(BaseModel):
    status: str = "online"
    loaded_llm: Optional[str] = None
    embedding_active: bool = True
    ctx_size: int = 16384
    uptime_sec: int = 0
    gpu_name: Optional[str] = None
    vram_used_mb: Optional[int] = None
    vram_total_mb: Optional[int] = None


class ModelsResponse(BaseModel):
    available_gguf: List[str]
    active_llm: Optional[str] = None


class SwitchModelRequest(BaseModel):
    model: str = Field(..., description="Filename of GGUF model located in models/ directory")
    ctx_size: Optional[int] = Field(16384, description="Context window size (e.g. 8192, 16384, 32768)")


class SwitchModelResponse(BaseModel):
    status: str = "ready"
    model: str
    ctx_size: int


class UnloadModelResponse(BaseModel):
    status: str = "VRAM freed"


# --- OpenAI Chat Completion Schemas ---

class ChatMessage(BaseModel):
    role: str
    content: Optional[Union[str, List[Any]]] = ""


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1024
    top_p: Optional[float] = 0.95
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    stop: Optional[Union[str, List[str]]] = None


# --- OpenAI Embedding Schemas ---

class EmbeddingRequest(BaseModel):
    input: Union[str, List[Any]]
    model: Optional[str] = "nomic-embed-text-v1.5"


class EmbeddingItem(BaseModel):
    object: str = "embedding"
    index: int
    embedding: List[float]


class EmbeddingUsage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingItem]
    model: str
    usage: EmbeddingUsage
