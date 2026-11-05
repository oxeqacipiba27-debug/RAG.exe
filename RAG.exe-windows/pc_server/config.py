"""
Configuration management for Windows 11 RTX 4070 Server.
Loads environment variables from .env or system environment with safe fallbacks.
"""

import os
from pathlib import Path
from typing import List, Optional

SERVER_DIR = Path(__file__).resolve().parent
MODELS_DIR = SERVER_DIR / "models"
LOGS_DIR = SERVER_DIR / "logs"

# Ensure essential directories exist
MODELS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def load_env_file(env_path: Path) -> None:
    """Simple parser to load key=value pairs into os.environ if not already set."""
    if not env_path.is_file():
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass


# Attempt to load .env from server dir
load_env_file(SERVER_DIR / ".env")


class ServerConfig:
    """RTX 4070 inference and remote connectivity configuration."""

    # Network binding
    # 0.0.0.0 binds to all local interfaces, LAN, and Tailscale VPN interfaces
    HOST: str = os.getenv("PC_SERVER_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PC_SERVER_PORT", "8000"))

    # Security / API Token
    # If API_KEY is set, requests must provide Authorization: Bearer <API_KEY>
    # When empty/None, open access (safe within private Tailscale mesh or trusted LAN)
    API_KEY: Optional[str] = os.getenv("PC_SERVER_API_KEY", "").strip() or None

    # Storage paths
    MODELS_PATH: Path = Path(os.getenv("PC_SERVER_MODELS_DIR", str(MODELS_DIR))).resolve()
    LOGS_PATH: Path = Path(os.getenv("PC_SERVER_LOGS_DIR", str(LOGS_DIR))).resolve()

    # Default LLM Settings for RTX 4070 (12GB VRAM)
    DEFAULT_MODEL: Optional[str] = os.getenv("PC_SERVER_DEFAULT_MODEL", "").strip() or None
    DEFAULT_CTX_SIZE: int = int(os.getenv("PC_SERVER_DEFAULT_CTX", "16384"))
    # -1 offloads all layers to GPU in llama-cpp-python
    N_GPU_LAYERS: int = int(os.getenv("PC_SERVER_GPU_LAYERS", "-1"))
    # Thread count for CPU parts of compute (default to half logical cores)
    N_THREADS: int = int(os.getenv("PC_SERVER_THREADS", str(max(1, (os.cpu_count() or 4) // 2))))

    # Embedding engine
    EMBEDDING_MODEL_PATH: Optional[str] = os.getenv("PC_SERVER_EMBEDDING_MODEL", "").strip() or None
    EMBEDDING_DIM: int = int(os.getenv("PC_SERVER_EMBEDDING_DIM", "768"))

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    # Emulation / Testing flag
    # If set to true, forces simulated GPU inference even if llama_cpp is installed
    SIMULATE_GPU: bool = os.getenv("PC_SERVER_SIMULATE_GPU", "false").lower() in ("true", "1", "yes")


config = ServerConfig()
