"""
Production-grade Windows 11 RTX 4070 LLM & Embedding Server.
Implements the exact API contract required by Arch Linux client (SwayFX / Waybar)
and OpenAI SDK:
- GET  /health
- GET  /admin/models
- POST /admin/switch
- POST /admin/unload
- POST /v1/chat/completions (OpenAI SSE streaming + JSON response)
- POST /v1/embeddings (OpenAI 768-dim nomic-embed-text-v1.5)
- GET  /admin/gpu (telemetry)
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from auth import verify_api_key
from config import config
from embedding_engine import EmbeddingEngine
from model_manager import ModelManager
from schemas import (
    ChatCompletionRequest,
    EmbeddingItem,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
    HealthResponse,
    ModelsResponse,
    SwitchModelRequest,
    SwitchModelResponse,
    UnloadModelResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pc_server")

start_time = time.time()

# Core service instances
model_manager = ModelManager(
    models_dir=config.MODELS_PATH,
    default_ctx=config.DEFAULT_CTX_SIZE,
    n_gpu_layers=config.N_GPU_LAYERS,
    n_threads=config.N_THREADS,
    simulate_gpu=config.SIMULATE_GPU,
)

embedding_engine = EmbeddingEngine(
    models_dir=config.MODELS_PATH,
    target_dim=config.EMBEDDING_DIM,
    custom_model_path=config.EMBEDDING_MODEL_PATH,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle startup and teardown management."""
    logger.info("=================================================================")
    logger.info("    RTX 4070 Inference & Remote Server Starting Up              ")
    logger.info(f"    Host: {config.HOST}:{config.PORT} | Models: {config.MODELS_PATH}")
    logger.info(f"    Auth Enabled: {bool(config.API_KEY)} | GPU Offload: {config.N_GPU_LAYERS} layers")
    logger.info("=================================================================")

    # Auto-load default model only if configured and available
    if config.DEFAULT_MODEL:
        available = model_manager.list_available_models()
        if (
            config.DEFAULT_MODEL in available
            or (model_manager.models_dir / config.DEFAULT_MODEL).is_file()
            or model_manager.simulate_gpu
            or not model_manager._llama_available
        ):
            logger.info(f"Auto-loading default model: {config.DEFAULT_MODEL}")
            try:
                await model_manager.switch_model(config.DEFAULT_MODEL, config.DEFAULT_CTX_SIZE)
            except Exception as e:
                logger.warning(f"Failed to auto-load default model: {e}. GPU is in IDLE state.")
        else:
            logger.info(f"Default model '{config.DEFAULT_MODEL}' not found on disk. Server started in IDLE state (VRAM unloaded).")
    else:
        logger.info("No default model specified. Server started in IDLE state (VRAM unloaded, ready for /admin/switch).")

    yield

    # Teardown: unload VRAM
    logger.info("Server shutting down, releasing GPU VRAM...")
    await model_manager.unload_model()
    logger.info("Server stopped.")


app = FastAPI(
    title="RTX 4070 LLM & Embedding Server",
    description="High-performance inference engine for Windows 11 PC + RTX 4070",
    version="1.0.0",
    lifespan=lifespan,
)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Ensure all HTTP error responses match OpenAI API error schema {"error": {...}}."""
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        content = exc.detail
    elif isinstance(exc.detail, dict):
        content = {"error": exc.detail}
    else:
        content = {
            "error": {
                "message": str(exc.detail),
                "type": "api_error",
                "code": exc.status_code,
            }
        }
    return JSONResponse(status_code=exc.status_code, content=content)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Root & Health Endpoints ---

@app.get("/", tags=["Info"])
def root_info() -> Dict[str, Any]:
    return {
        "service": "RTX 4070 Remote Inference Server",
        "status": "online",
        "docs_url": "/docs",
        "active_model": model_manager.active_model_name,
        "embedding_active": embedding_engine.is_active(),
    }


@app.get(
    "/health",
    response_model=HealthResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Monitoring"],
)
def get_health() -> HealthResponse:
    """
    Sub-second health check consumed by Waybar pill and client status probes.
    Returns status: online, loaded_llm: filename (or null if VRAM unloaded).
    """
    gpu_info = model_manager.get_gpu_info()
    return HealthResponse(
        status="online",
        loaded_llm=model_manager.active_model_name,
        embedding_active=embedding_engine.is_active(),
        ctx_size=model_manager.active_ctx_size,
        uptime_sec=int(time.time() - start_time),
        gpu_name=gpu_info.get("gpu_name"),
        vram_used_mb=gpu_info.get("vram_used_mb"),
        vram_total_mb=gpu_info.get("vram_total_mb"),
    )


# --- Admin Control Endpoints ---

@app.get(
    "/admin/models",
    response_model=ModelsResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Admin"],
)
def get_models() -> ModelsResponse:
    """List all available GGUF models on disk and currently active model in VRAM."""
    return ModelsResponse(
        available_gguf=model_manager.list_available_models(),
        active_llm=model_manager.active_model_name,
    )


@app.post(
    "/admin/switch",
    response_model=SwitchModelResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Admin"],
)
async def switch_model(payload: SwitchModelRequest) -> SwitchModelResponse:
    """Hot-swap active GGUF model in GPU VRAM and configure context window."""
    try:
        res = await model_manager.switch_model(
            model_filename=payload.model,
            ctx_size=payload.ctx_size,
        )
        return SwitchModelResponse(
            status="ready",
            model=res["model"],
            ctx_size=res["ctx_size"],
        )
    except FileNotFoundError as fnf:
        raise HTTPException(
            status_code=404,
            detail={"error": {"message": str(fnf), "type": "model_not_found", "code": 404}},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": str(exc), "type": "model_switch_error", "code": 500}},
        )


@app.post(
    "/admin/unload",
    response_model=UnloadModelResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Admin"],
)
async def unload_model() -> UnloadModelResponse:
    """Immediately free all GPU VRAM to 0MB."""
    await model_manager.unload_model()
    return UnloadModelResponse(status="VRAM freed")


@app.get(
    "/admin/gpu",
    dependencies=[Depends(verify_api_key)],
    tags=["Admin"],
)
def get_gpu_telemetry() -> Dict[str, Any]:
    """Retrieve detailed GPU telemetry (RTX 4070 VRAM and utilization)."""
    return model_manager.get_gpu_info()


# --- OpenAI Compatible Endpoints ---

@app.post(
    "/v1/chat/completions",
    dependencies=[Depends(verify_api_key)],
    tags=["OpenAI API"],
)
async def chat_completions(req: ChatCompletionRequest):
    """
    OpenAI-compatible chat completion endpoint.
    Supports real-time SSE streaming (stream=True) and standard JSON responses.
    """
    if model_manager.active_model_name is None:
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

    # Convert Pydantic ChatMessages to dict list
    messages_payload = [{"role": m.role, "content": m.content} for m in req.messages]

    try:
        completion_result = await model_manager.generate_chat_completion(
            messages=messages_payload,
            stream=bool(req.stream),
            temperature=req.temperature if req.temperature is not None else 0.7,
            max_tokens=req.max_tokens or 1024,
            model_name=req.model,
            stop=req.stop,
        )

        if req.stream:
            return StreamingResponse(
                completion_result,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            return JSONResponse(content=completion_result)

    except RuntimeError as re:
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": str(re), "type": "model_not_loaded", "code": 503}},
        )
    except Exception as exc:
        logger.error(f"Chat completion failure: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": str(exc), "type": "internal_error", "code": 500}},
        )


@app.post(
    "/v1/embeddings",
    response_model=EmbeddingResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["OpenAI API"],
)
def generate_embeddings(req: EmbeddingRequest) -> EmbeddingResponse:
    """
    OpenAI-compatible embeddings endpoint.
    Generates 768-dimensional normalized float vectors for nomic-embed-text-v1.5.
    """
    if not embedding_engine.is_active():
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Embedding service inactive", "type": "server_error", "code": 503}},
        )

    inputs = [req.input] if isinstance(req.input, str) else req.input
    if not inputs:
        return EmbeddingResponse(
            object="list",
            data=[],
            model=req.model or "nomic-embed-text-v1.5",
            usage=EmbeddingUsage(prompt_tokens=0, total_tokens=0),
        )

    vectors, total_tokens = embedding_engine.embed(inputs)

    items = [
        EmbeddingItem(
            object="embedding",
            index=i,
            embedding=vec,
        )
        for i, vec in enumerate(vectors)
    ]

    return EmbeddingResponse(
        object="list",
        data=items,
        model=req.model or "nomic-embed-text-v1.5",
        usage=EmbeddingUsage(
            prompt_tokens=total_tokens,
            total_tokens=total_tokens,
        ),
    )


# --- Standalone Entry Point ---

def run():
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level="info",
    )


if __name__ == "__main__":
    run()
