"""
Embedding Engine for RTX 4070 PC Server.
Generates 768-dimensional normalized float vectors (nomic-embed-text-v1.5 standard).
Supports:
1. llama-cpp-python embedding model (GGUF nomic-embed-text)
2. sentence-transformers / HuggingFace model if installed
3. Deterministic high-entropy 768-dim vector generator fallback for instant startup / testing
"""

import hashlib
import logging
import math
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("pc_server.embedding")


class EmbeddingEngine:
    def __init__(self, models_dir: Path, target_dim: int = 768, custom_model_path: Optional[str] = None):
        self.models_dir = models_dir
        self.target_dim = target_dim
        self.custom_model_path = custom_model_path
        self._llama_embedder = None
        self._st_model = None
        self._engine_type = "fallback"
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        """Attempt to load real embedding model if available, else use fallback."""
        # Check custom path or search for nomic-embed GGUF in models_dir
        embed_gguf: Optional[Path] = None
        if self.custom_model_path:
            p = Path(self.custom_model_path)
            if p.is_file():
                embed_gguf = p
        else:
            for candidate in self.models_dir.glob("*.gguf"):
                cand_lower = candidate.name.lower()
                if "embed" in cand_lower or "nomic" in cand_lower or "bge" in cand_lower:
                    embed_gguf = candidate
                    break

        if embed_gguf and embed_gguf.is_file():
            try:
                import llama_cpp
                logger.info(f"Loading GGUF embedding model from {embed_gguf.name}...")
                self._llama_embedder = llama_cpp.Llama(
                    model_path=str(embed_gguf),
                    embedding=True,
                    n_gpu_layers=-1,
                    verbose=False,
                )
                self._engine_type = f"llama_cpp ({embed_gguf.name})"
                logger.info("GGUF embedding model successfully loaded.")
                return
            except Exception as e:
                logger.warning(f"Could not load GGUF embedding model via llama_cpp: {e}")

        # Try sentence_transformers if available
        try:
            from sentence_transformers import SentenceTransformer
            model_name = "nomic-ai/nomic-embed-text-v1.5"
            logger.info(f"Trying sentence-transformers ({model_name})...")
            self._st_model = SentenceTransformer(model_name, trust_remote_code=True)
            self._engine_type = "sentence_transformers"
            logger.info("SentenceTransformer model loaded.")
            return
        except Exception:
            pass

        # Fallback to high-entropy deterministic embedding engine
        self._engine_type = "deterministic_768d_fallback"
        logger.info("Using built-in deterministic 768-dim normalized embedding engine.")

    @property
    def engine_type(self) -> str:
        return self._engine_type

    def is_active(self) -> bool:
        return True

    def _generate_deterministic_vector(self, text: str) -> List[float]:
        """Generates a deterministic, L2-normalized 768-dimensional float vector for input text."""
        seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_bytes[:8], byteorder="big")

        raw_vals: List[float] = []
        current = seed_int
        # Linear congruential generator with 64-bit parameters
        for _ in range(self.target_dim):
            current = (current * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            val = ((current % 200000) / 100000.0) - 1.0
            raw_vals.append(val)

        norm = math.sqrt(sum(x * x for x in raw_vals)) or 1.0
        return [round(x / norm, 6) for x in raw_vals]

    def embed(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        """
        Embed a list of text strings.
        Returns:
            (list of 768-dim float vectors, total token count estimate)
        """
        if not texts:
            return [], 0

        total_tokens = sum(max(1, len(t.split())) for t in texts)

        # 1. llama-cpp embedder
        if self._llama_embedder is not None:
            try:
                embeddings = []
                for t in texts:
                    res = self._llama_embedder.create_embedding(t)
                    # Output shape from llama_cpp: {"data": [{"embedding": [...]}]}
                    vec = res["data"][0]["embedding"]
                    # Normalize if not normalized
                    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
                    embeddings.append([x / norm for x in vec])
                return embeddings, total_tokens
            except Exception as e:
                logger.error(f"llama-cpp embedding error: {e}. Falling back to deterministic.")

        # 2. sentence-transformers
        if self._st_model is not None:
            try:
                vectors = self._st_model.encode(texts, normalize_embeddings=True)
                return [v.tolist() for v in vectors], total_tokens
            except Exception as e:
                logger.error(f"sentence-transformers embedding error: {e}. Falling back.")

        # 3. Deterministic normalized generator
        embeddings = [self._generate_deterministic_vector(t) for t in texts]
        return embeddings, total_tokens
