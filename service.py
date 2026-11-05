r"""
C:\llm_engine\service.py
=============================================================================
Standalone LLM + Embeddings Server for Windows 11 LTSC & NVIDIA RTX 4070 (12GB)
=============================================================================
Architecture:
- Port 8000: FastAPI Gateway (OpenAI-compatible + Arch Linux llm-ctl API contract)
- Port 8081: Dynamic LLM llama-server.exe worker (Qwen2.5-14B / any GGUF)
- Port 8082: Permanent nomic-embed-text-v1.5 worker (768-D embeddings)

Hardware Optimizations:
- Dynamic LLM: -ngl 99 -c <ctx_size> --flash-attn -ctk q8_0 -ctv q8_0 --parallel 2 --cont-batching
- Embedding:   -ngl 0 (CPU per GEMINI.md Rule 7) --embedding --pooling mean -c 8192 -ub 2048
- Watchdogs:   10-minute (600s) VRAM auto-idle unloader & Simracing/Gaming Guard (15s)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import httpx
import psutil
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# =============================================================================
# Directories & Global Paths
# =============================================================================
BASE_DIR = Path(os.getenv("LLM_ENGINE_ROOT", r"C:\llm_engine"))
BIN_DIR = BASE_DIR / "bin"
MODELS_DIR = BASE_DIR / "models"
LOGS_DIR = BASE_DIR / "logs"

for d in (BIN_DIR, MODELS_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Add BIN_DIR to Windows DLL search directory and PATH for CUDA runtime resolution
if sys.platform == "win32":
    if hasattr(os, "add_dll_directory") and BIN_DIR.exists():
        try:
            os.add_dll_directory(str(BIN_DIR))
        except Exception:
            pass
    bin_str = str(BIN_DIR)
    if bin_str not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_str + os.pathsep + os.environ.get("PATH", "")

SERVER_LOG_FILE = LOGS_DIR / "server.log"

# =============================================================================
# Logging Configuration (UTF-8, Rotating 10MB x 5)
# =============================================================================
logger = logging.getLogger("LLMEngine")
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    SERVER_LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)
file_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(file_formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(file_formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# =============================================================================
# Configuration & Hardware Tunables
# =============================================================================
HOST = os.getenv("LLM_GATEWAY_HOST", "0.0.0.0")
PORT = int(os.getenv("LLM_GATEWAY_PORT", "8000"))

LLM_PORT = 8081
EMBED_PORT = 8082
LLM_INTERNAL_HOST = "127.0.0.1"

EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "nomic-embed-text-v1.5.Q8_0.gguf")
DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "Qwen2.5-14B-Instruct-Q4_K_M.gguf")
DEFAULT_CTX_SIZE = int(os.getenv("DEFAULT_CTX_SIZE", "16384"))
IDLE_TIMEOUT_SEC = int(os.getenv("VRAM_IDLE_TIMEOUT_SEC", "600"))  # 10 minutes

# Heavy GPU game executables that demand 100% of the RTX 4070 VRAM
GAME_EXECUTABLES = [
    "ac2-win64-shipping.exe",
    "acs.exe",
    "forza_gaming.desktop.x64_release_final.exe",
    "cs2.exe",
    "valorant-win64-shipping.exe"
]
extra_games = os.getenv("GAME_GUARD_EXES", "")
if extra_games:
    for g in extra_games.split(","):
        clean_g = g.strip().lower()
        if clean_g and clean_g not in GAME_EXECUTABLES:
            GAME_EXECUTABLES.append(clean_g)

# Windows process creation flags: suppress console window popup
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# =============================================================================
# State Manager
# =============================================================================
class EngineState:
    def __init__(self):
        self.start_time: float = time.time()
        self.last_chat_timestamp: float = time.time()
        self.loaded_llm: Optional[str] = None
        self.last_active_model: Optional[str] = None
        self.current_ctx_size: int = DEFAULT_CTX_SIZE
        self.embedding_active: bool = False
        self.gaming_guard_active: bool = False
        self.active_game_detected: Optional[str] = None
        
        # Process handles
        self.llm_process: Optional[subprocess.Popen] = None
        self.embed_process: Optional[subprocess.Popen] = None
        
        # Concurrency locks
        self.switch_lock: asyncio.Lock = asyncio.Lock()

state = EngineState()

# =============================================================================
# Subprocess & Port Helper Functions
# =============================================================================
def get_llama_binary() -> Path:
    """Finds llama-server.exe in C:\\llm_engine\\bin or PATH."""
    primary = BIN_DIR / "llama-server.exe"
    if primary.exists():
        return primary
    fallback = shutil.which("llama-server.exe") or shutil.which("llama-server")
    if fallback:
        return Path(fallback)
    return primary

def free_port(port: int) -> None:
    """Terminates any process currently listening on the given port."""
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
                if conn.pid:
                    try:
                        p = psutil.Process(conn.pid)
                        logger.warning(f"Port {port} is occupied by PID {p.pid} ({p.name()}). Terminating...")
                        p.terminate()
                        p.wait(timeout=2.0)
                    except Exception:
                        try:
                            p.kill()
                        except Exception:
                            pass
    except Exception as e:
        logger.debug(f"free_port({port}) psutil inspection: {e}")

    # Fallback for Windows if port is still occupied (Rule 3 of GEMINI.md)
    if sys.platform == "win32":
        try:
            cmd = f'netstat -ano | findstr ":{port} "'
            out = subprocess.check_output(cmd, shell=True, text=True, errors="replace")
            for line in out.strip().splitlines():
                if "LISTENING" in line:
                    parts = line.strip().split()
                    pid = int(parts[-1])
                    if pid != os.getpid() and pid > 0:
                        logger.warning(f"Port {port} still held by PID {pid}. Force killing via taskkill...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        except Exception:
            pass

def kill_process_tree(proc: Optional[subprocess.Popen]) -> None:
    """Gracefully terminates a subprocess and all its children, falling back to kill."""
    if proc is None or proc.poll() is not None:
        return
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except Exception:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs(children + [parent], timeout=3.0)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

async def wait_for_health(url: str, timeout_sec: float = 60.0, proc: Optional[subprocess.Popen] = None) -> bool:
    """Polls a llama-server /health endpoint until HTTP 200 is returned."""
    start = time.time()
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.time() - start < timeout_sec:
            if proc and proc.poll() is not None:
                logger.error(f"Process {proc.pid} terminated prematurely with returncode {proc.returncode}")
                return False
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False

# =============================================================================
# Process 1: Permanent Embedding Worker (Port 8082)
# =============================================================================
def start_embedding_worker() -> bool:
    """Spawns nomic-embed-text-v1.5 worker on port 8082."""
    free_port(EMBED_PORT)
    exe = get_llama_binary()
    model_path = MODELS_DIR / EMBED_MODEL_NAME
    
    if not exe.exists():
        logger.error(f"llama-server.exe binary not found at {exe}")
        state.embedding_active = False
        return False
        
    if not model_path.exists():
        logger.warning(f"Embedding model not found at {model_path}. Searching for any nomic-embed in {MODELS_DIR}...")
        cands = list(MODELS_DIR.glob("*nomic-embed*.gguf"))
        if cands:
            model_path = cands[0]
            logger.info(f"Using discovered embedding model: {model_path.name}")
        else:
            logger.error("No embedding GGUF model available in models directory!")
            state.embedding_active = False
            return False

    # Hardware flags: -ngl 0 by default (CPU embeddings per GEMINI.md Rule 7) --embedding --pooling mean -c 8192 -ub 2048
    embed_ngl = os.getenv("EMBED_NGL", "0")
    cmd = [
        str(exe),
        "-m", str(model_path),
        "--host", LLM_INTERNAL_HOST,
        "--port", str(EMBED_PORT),
        "-ngl", embed_ngl,
        "--embedding",
        "--pooling", "mean",
        "-c", "8192",
        "-ub", "2048"
    ]

    logger.info(f"Starting permanent Embedding Worker on {LLM_INTERNAL_HOST}:{EMBED_PORT} -> {' '.join(cmd)}")
    
    try:
        with open(LOGS_DIR / "llama_embed.log", "a", encoding="utf-8") as embed_log:
            state.embed_process = subprocess.Popen(
                cmd,
                stdout=embed_log,
                stderr=embed_log,
                creationflags=CREATE_NO_WINDOW
            )
        return True
    except Exception as e:
        logger.error(f"Failed to start embedding worker: {e}")
        state.embedding_active = False
        return False

# =============================================================================
# Process 2: Dynamic LLM Worker (Port 8081)
# =============================================================================
async def spawn_llm_worker(model_filename: str, ctx_size: int = DEFAULT_CTX_SIZE) -> bool:
    """Spawns dynamic llama-server.exe LLM worker on port 8081 with RTX 4070 optimizations."""
    if state.gaming_guard_active:
        logger.warning(f"Rejecting LLM launch: Gaming guard is active ({state.active_game_detected} running).")
        return False

    exe = get_llama_binary()
    model_path = MODELS_DIR / model_filename
    
    if not exe.exists():
        logger.error(f"llama-server.exe binary not found at {exe}")
        return False
        
    if not model_path.exists():
        logger.error(f"Model file {model_path} does not exist!")
        return False

    # 1. Unload running LLM first
    await unload_llm_worker()
    free_port(LLM_PORT)

    # 2. RTX 4070 hardware flags: -ngl 99 -c <ctx_size> --flash-attn -ctk q8_0 -ctv q8_0 --parallel 2 --cont-batching
    cmd = [
        str(exe),
        "-m", str(model_path),
        "--host", LLM_INTERNAL_HOST,
        "--port", str(LLM_PORT),
        "-ngl", "99",
        "-c", str(ctx_size),
        "--flash-attn",
        "-ctk", "q8_0",
        "-ctv", "q8_0",
        "--parallel", "2",
        "--cont-batching"
    ]

    logger.info(f"Spawning dynamic LLM Worker on {LLM_INTERNAL_HOST}:{LLM_PORT} ({model_filename}, ctx={ctx_size})...")
    
    try:
        with open(LOGS_DIR / "llama_llm.log", "a", encoding="utf-8") as llm_log:
            state.llm_process = subprocess.Popen(
                cmd,
                stdout=llm_log,
                stderr=llm_log,
                creationflags=CREATE_NO_WINDOW
            )
    except Exception as e:
        logger.error(f"Subprocess spawn failure: {e}")
        return False

    # 3. Wait for readiness
    healthy = await wait_for_health(f"http://{LLM_INTERNAL_HOST}:{LLM_PORT}/health", timeout_sec=90.0, proc=state.llm_process)
    if healthy:
        state.loaded_llm = model_filename
        state.last_active_model = model_filename
        state.current_ctx_size = ctx_size
        state.last_chat_timestamp = time.time()
        logger.info(f"LLM Worker READY: {model_filename} (Port {LLM_PORT})")
        return True
    else:
        logger.error(f"LLM Worker failed health check on port {LLM_PORT}")
        await unload_llm_worker()
        return False

async def unload_llm_worker() -> None:
    """Terminates the LLM process on port 8081 immediately to free ~10GB VRAM."""
    if state.llm_process is not None:
        logger.info(f"Unloading LLM on port {LLM_PORT} (PID {state.llm_process.pid}) to free VRAM...")
        kill_process_tree(state.llm_process)
        state.llm_process = None
    free_port(LLM_PORT)
    state.loaded_llm = None
    logger.info("VRAM freed: LLM process terminated successfully.")

# =============================================================================
# Auto-Idle & Gaming Guard Watchdog Tasks
# =============================================================================
async def watchdog_task():
    """Combined background task for 10-minute idle VRAM unloading and Gaming Guard."""
    logger.info("Watchdog started: Auto-idle 600s + Gaming Guard active.")
    last_game_check = 0.0
    last_embed_check = 0.0

    while True:
        try:
            now = time.time()

            # --- 1. Gaming / Simracing Auto-Unload Guard (Checked every 15 seconds) ---
            if now - last_game_check >= 15.0:
                last_game_check = now
                detected_game = None
                
                try:
                    for proc in psutil.process_iter(['name']):
                        try:
                            name = (proc.info.get('name') or '').lower()
                            if name in GAME_EXECUTABLES:
                                detected_game = proc.info.get('name')
                                break
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            continue
                except Exception as e:
                    logger.debug(f"psutil process scan: {e}")

                if detected_game:
                    if not state.gaming_guard_active:
                        logger.warning(f"🚨 Gaming Guard triggered! Heavy game detected: '{detected_game}'")
                    state.gaming_guard_active = True
                    state.active_game_detected = detected_game
                    if state.loaded_llm is not None:
                        logger.warning(
                            f"Gaming Guard: game '{detected_game}' active. "
                            "Unloading LLM on port 8081 to free 100% RTX 4070 VRAM..."
                        )
                        async with state.switch_lock:
                            await unload_llm_worker()
                else:
                    if state.gaming_guard_active:
                        logger.info(f"✅ Gaming Guard: '{state.active_game_detected}' closed. Resuming normal operations.")
                        state.gaming_guard_active = False
                        state.active_game_detected = None

            # --- 2. Auto-Idle VRAM Watchdog (10-minute inactivity check) ---
            if state.loaded_llm is not None:
                idle_duration = now - state.last_chat_timestamp
                if idle_duration >= IDLE_TIMEOUT_SEC:
                    logger.info(
                        f"⏰ VRAM Auto-Idle Watchdog: {idle_duration:.1f}s elapsed without chat requests "
                        f"(threshold: {IDLE_TIMEOUT_SEC}s). Freeing VRAM..."
                    )
                    async with state.switch_lock:
                        await unload_llm_worker()

            # --- 3. Embedding Server Health Watchdog (Self-healing on crash or initial failure) ---
            needs_embed_restart = False
            if state.embed_process is None:
                if now - last_embed_check >= 30.0:
                    last_embed_check = now
                    needs_embed_restart = True
            elif state.embed_process.poll() is not None:
                logger.warning("Permanent Embedding Worker exited unexpectedly! Restarting...")
                needs_embed_restart = True

            if needs_embed_restart:
                if start_embedding_worker():
                    healthy = await wait_for_health(
                        f"http://{LLM_INTERNAL_HOST}:{EMBED_PORT}/health",
                        timeout_sec=15.0,
                        proc=state.embed_process
                    )
                    state.embedding_active = healthy

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Watchdog loop error: {e}", exc_info=True)

        await asyncio.sleep(5.0)

# =============================================================================
# FastAPI Lifespan Handler
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes permanent embedding worker and watchdogs on boot, cleans up on shutdown."""
    logger.info("==================================================================")
    logger.info("  EXSCIO Standalone LLM Engine (Windows 11 LTSC / RTX 4070)")
    logger.info("==================================================================")
    logger.info(f"Root: {BASE_DIR} | Bin: {BIN_DIR} | Models: {MODELS_DIR}")
    
    # 1. Clean up any leftover ports
    free_port(LLM_PORT)
    free_port(EMBED_PORT)

    # 2. Start permanent embedding worker
    if start_embedding_worker():
        healthy = await wait_for_health(
            f"http://{LLM_INTERNAL_HOST}:{EMBED_PORT}/health",
            timeout_sec=30.0,
            proc=state.embed_process
        )
        state.embedding_active = healthy
        if healthy:
            logger.info("Permanent Embedding Worker (port 8082) is ONLINE.")
        else:
            logger.warning("Embedding Worker spawned but did not respond to /health within 30s.")
    else:
        logger.warning("Permanent Embedding Worker could not be started.")

    # 3. Start background watchdog
    watchdog = asyncio.create_task(watchdog_task())

    yield

    # Shutdown sequence
    logger.info("Initiating graceful shutdown of LLM Engine...")
    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass

    await unload_llm_worker()
    if state.embed_process:
        logger.info("Terminating permanent Embedding Worker...")
        kill_process_tree(state.embed_process)
        state.embed_process = None
    free_port(EMBED_PORT)
    logger.info("LLM Engine shutdown complete.")

# =============================================================================
# FastAPI Application & Schemas
# =============================================================================
app = FastAPI(
    title="EXSCIO Standalone RTX 4070 LLM & Embedding Engine",
    description="Dedicated Windows 11 LTSC llama-server.exe gateway on port 8000",
    version="2.5.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SwitchModelRequest(BaseModel):
    model: str = Field(..., description="GGUF model filename in C:\\llm_engine\\models")
    ctx_size: Optional[int] = Field(DEFAULT_CTX_SIZE, description="Context window size (default 16384)")

class SwitchModelResponse(BaseModel):
    status: str
    model: str

class UnloadModelResponse(BaseModel):
    status: str

class HealthResponse(BaseModel):
    status: str
    loaded_llm: Optional[str]
    embedding_active: bool
    vram_idle_timeout_sec: int
    ctx_size: Optional[int] = None

class ModelsResponse(BaseModel):
    available_gguf: List[str]
    active_llm: Optional[str]

# =============================================================================
# EXACT API CONTRACT ENDPOINTS (Port 0.0.0.0:8000)
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health():
    """
    1. GET /health
    Returns:
    {"status": "online", "loaded_llm": "Qwen2.5-14B-Instruct-Q4_K_M.gguf", "embedding_active": true, "vram_idle_timeout_sec": 600}
    Note: loaded_llm MUST be null when no LLM is loaded in VRAM so Waybar switches to 'idle' state.
    """
    # Verify embedding worker health
    embed_ok = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get(f"http://{LLM_INTERNAL_HOST}:{EMBED_PORT}/health")
            embed_ok = (r.status_code == 200)
    except Exception:
        embed_ok = False
    state.embedding_active = embed_ok

    # If LLM process died unexpectedly, set loaded_llm to None
    if state.llm_process and state.llm_process.poll() is not None:
        state.loaded_llm = None
        state.llm_process = None

    return {
        "status": "online",
        "loaded_llm": state.loaded_llm,  # Returns null if None
        "embedding_active": state.embedding_active,
        "vram_idle_timeout_sec": IDLE_TIMEOUT_SEC,
        "ctx_size": state.current_ctx_size if state.loaded_llm else 0,
    }

@app.get("/admin/models", response_model=ModelsResponse, tags=["Admin"])
def get_models():
    """
    2. GET /admin/models
    Scans C:\\llm_engine\\models (including symlinks and hardlinks) and returns:
    {"available_gguf": ["model1.gguf", "model2.gguf"], "active_llm": "model1.gguf"}
    """
    files: List[str] = []
    if MODELS_DIR.exists():
        for p in MODELS_DIR.iterdir():
            if p.suffix.lower() == ".gguf" and (p.is_file() or p.is_symlink()):
                # Exclude embedding model from LLM generation list
                if "nomic-embed" in p.name.lower():
                    continue
                files.append(p.name)
    files.sort(key=str.lower)
    return {
        "available_gguf": files,
        "active_llm": state.loaded_llm
    }

@app.post("/admin/switch", response_model=SwitchModelResponse, tags=["Admin"])
async def switch_model(payload: SwitchModelRequest):
    """
    3. POST /admin/switch
    Accepts {"model": "<filename.gguf>", "ctx_size": 16384}
    Terminates any running LLM process on port 8081, spawns llama-server.exe,
    waits until http://127.0.0.1:8081/health returns HTTP 200, and returns:
    {"status": "ready", "model": "<filename.gguf>"}
    """
    if state.gaming_guard_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Gaming mode active: '{state.active_game_detected}' is running. LLM loading is blocked."
        )

    raw_model = payload.model.strip()
    model_name = Path(raw_model).name  # Prevent directory traversal
    target_file = MODELS_DIR / model_name
    if not target_file.exists():
        # Check if .gguf extension was omitted
        if (MODELS_DIR / f"{model_name}.gguf").exists():
            model_name = f"{model_name}.gguf"
            target_file = MODELS_DIR / model_name
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model file '{model_name}' not found in {MODELS_DIR}"
            )

    ctx_size = payload.ctx_size if (payload.ctx_size and payload.ctx_size > 0) else DEFAULT_CTX_SIZE
    
    async with state.switch_lock:
        ok = await spawn_llm_worker(model_name, ctx_size)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to launch llama-server for model '{model_name}' on port {LLM_PORT}"
            )

    return {
        "status": "ready",
        "model": model_name
    }

@app.post("/admin/unload", response_model=UnloadModelResponse, tags=["Admin"])
async def unload_model():
    """
    4. POST /admin/unload
    Terminates the LLM process on port 8081 immediately to free ~10GB VRAM and returns:
    {"status": "VRAM freed"}
    """
    async with state.switch_lock:
        await unload_llm_worker()
    return {"status": "VRAM freed"}

async def auto_wake_if_needed(requested_model: Optional[str] = None) -> None:
    """Auto-wake LLM if loaded_llm is null due to idle timeout."""
    if state.loaded_llm is not None and state.llm_process and state.llm_process.poll() is None:
        return

    if state.gaming_guard_active:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Gaming Guard active: '{state.active_game_detected}' is running. GPU inference blocked."
        )

    # Determine model to wake
    wake_model = None
    if requested_model:
        cand = Path(requested_model.strip()).name
        if (MODELS_DIR / cand).exists():
            wake_model = cand
        elif (MODELS_DIR / f"{cand}.gguf").exists():
            wake_model = f"{cand}.gguf"

    if not wake_model:
        wake_model = state.last_active_model

    if not wake_model or not (MODELS_DIR / wake_model).exists():
        if (MODELS_DIR / DEFAULT_LLM_MODEL).exists():
            wake_model = DEFAULT_LLM_MODEL
        else:
            candidates = [p.name for p in MODELS_DIR.glob("*.gguf") if "nomic-embed" not in p.name.lower()]
            if candidates:
                wake_model = sorted(candidates)[0]
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="No GGUF models available in C:\\llm_engine\\models to auto-wake"
                )

    logger.info(f"Auto-Wake LLM triggered: loading '{wake_model}' into VRAM (ctx={state.current_ctx_size})...")
    async with state.switch_lock:
        # Double-check inside lock to prevent stampede race condition
        if state.loaded_llm is not None and state.llm_process and state.llm_process.poll() is None:
            return
        ok = await spawn_llm_worker(wake_model, state.current_ctx_size)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Auto-Wake failed to initialize model '{wake_model}'"
            )

@app.post("/v1/chat/completions", tags=["OpenAI"])
@app.post("/chat/completions", tags=["OpenAI"], include_in_schema=False)
async def chat_completions(request: Request):
    """
    5. POST /v1/chat/completions
    Proxies requests to http://127.0.0.1:8081/v1/chat/completions with full SSE streaming.
    Auto-Wake Feature: If loaded_llm is null, automatically loads model into VRAM and streams.
    """
    body = await request.body()
    try:
        body_json = json.loads(body)
    except Exception:
        body_json = {}

    req_model = body_json.get("model")

    # 1. Auto-Wake if idle
    await auto_wake_if_needed(requested_model=req_model)
    
    # 2. Update idle watchdog timestamp
    state.last_chat_timestamp = time.time()

    is_stream = bool(body_json.get("stream", False))
    target_url = f"http://{LLM_INTERNAL_HOST}:{LLM_PORT}/v1/chat/completions"

    client = httpx.AsyncClient(timeout=180.0)

    if is_stream:
        async def stream_generator() -> AsyncGenerator[bytes, None]:
            try:
                async with client.stream(
                    "POST",
                    target_url,
                    headers={"Content-Type": "application/json"},
                    content=body
                ) as upstream_response:
                    if upstream_response.status_code != 200:
                        err_text = await upstream_response.aread()
                        yield f"data: {{\"error\": \"Upstream error {upstream_response.status_code}: {err_text.decode('utf-8', errors='replace')}\"}}\n\n".encode("utf-8")
                        yield b"data: [DONE]\n\n"
                        return

                    async for chunk in upstream_response.aiter_raw():
                        yield chunk
            except Exception as e:
                logger.error(f"Streaming error proxying to LLM worker: {e}")
                yield f"data: {{\"error\": \"Proxy stream exception: {str(e)}\"}}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
            finally:
                await client.aclose()
                state.last_chat_timestamp = time.time()

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        try:
            resp = await client.post(
                target_url,
                headers={"Content-Type": "application/json"},
                content=body
            )
            state.last_chat_timestamp = time.time()
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={"Content-Type": resp.headers.get("content-type", "application/json")}
            )
        except Exception as e:
            logger.error(f"Error proxying chat completions: {e}")
            raise HTTPException(status_code=502, detail=f"LLM worker communication error: {e}")
        finally:
            await client.aclose()

@app.post("/v1/embeddings", tags=["OpenAI"])
@app.post("/embeddings", tags=["OpenAI"], include_in_schema=False)
async def embeddings(request: Request):
    """
    6. POST /v1/embeddings
    Proxies requests to http://127.0.0.1:8082/v1/embeddings (permanent nomic-embed worker).
    """
    body = await request.body()
    target_url = f"http://{LLM_INTERNAL_HOST}:{EMBED_PORT}/v1/embeddings"
    
    # Auto-recover embedding worker if down
    if state.embed_process is None or state.embed_process.poll() is not None:
        logger.warning(f"Embedding worker offline on port {EMBED_PORT}. Attempting auto-recovery...")
        if start_embedding_worker():
            healthy = await wait_for_health(
                f"http://{LLM_INTERNAL_HOST}:{EMBED_PORT}/health",
                timeout_sec=15.0,
                proc=state.embed_process
            )
            state.embedding_active = healthy

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                target_url,
                headers={"Content-Type": "application/json"},
                content=body
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={"Content-Type": resp.headers.get("content-type", "application/json")}
            )
        except Exception as e:
            logger.error(f"Error proxying embeddings to port {EMBED_PORT}: {e}")
            raise HTTPException(status_code=502, detail=f"Embedding worker communication error: {e}")

# =============================================================================
# Helper & Diagnostic Endpoints
# =============================================================================
@app.get("/", tags=["Info"])
def root_info():
    return {
        "engine": "EXSCIO Standalone RTX 4070 Inference Engine",
        "version": "2.5.0",
        "endpoints": [
            "GET /health",
            "GET /admin/models",
            "POST /admin/switch",
            "POST /admin/unload",
            "POST /v1/chat/completions",
            "POST /v1/embeddings"
        ],
        "active_llm": state.loaded_llm,
        "gaming_guard_active": state.gaming_guard_active,
        "uptime_sec": int(time.time() - state.start_time)
    }

@app.get("/v1/models", tags=["OpenAI"])
def get_v1_models():
    """OpenAI standard models endpoint."""
    models_res = get_models()
    return {
        "object": "list",
        "data": [
            {
                "id": m,
                "object": "model",
                "created": int(state.start_time),
                "owned_by": "exscio-rtx4070"
            }
            for m in models_res["available_gguf"]
        ]
    }

@app.get("/admin/gpu", tags=["Diagnostics"])
def get_gpu_telemetry():
    """Returns nvidia-smi GPU telemetry if available."""
    try:
        smi = shutil.which("nvidia-smi.exe") or shutil.which("nvidia-smi")
        if smi:
            res = subprocess.run(
                [smi, "--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3.0, creationflags=CREATE_NO_WINDOW
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().split(",")]
                if len(parts) >= 6:
                    return {
                        "gpu_name": parts[0],
                        "vram_total_mb": float(parts[1]),
                        "vram_used_mb": float(parts[2]),
                        "vram_free_mb": float(parts[3]),
                        "temperature_c": float(parts[4]),
                        "power_draw_w": float(parts[5]),
                        "gaming_guard_active": state.gaming_guard_active
                    }
    except Exception:
        pass
    return {
        "gpu_name": "NVIDIA GeForce RTX 4070 (12GB)",
        "gaming_guard_active": state.gaming_guard_active
    }

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Standalone Engine on {HOST}:{PORT} ...")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
