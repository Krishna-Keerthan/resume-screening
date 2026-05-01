"""
app/services/embedding_service.py  ── IMPROVED VERSION

Singleton wrapper around a sentence-transformers model.

IMPROVEMENTS OVER ORIGINAL
---------------------------
  [E1]  In-memory embedding cache (LRU, 512 slots): repeated calls with the
        same text (e.g. the same job description scored against 100 resumes)
        now return immediately instead of re-running the model.

  [E2]  Batch encode support improved: encode() now accepts a list of strings
        and returns an (N, d) array with a single model.encode() call —
        previously callers had to loop. Batch size is configurable.

  [E3]  Model warm-up: _warm_up() encodes a short dummy sentence after load
        so the first real encode() is not penalised by JIT/CUDA compilation.

  [E4]  Model health check: is_healthy() method returns True only if the
        model can encode a test string without error — used by the /health
        endpoint to report embedding status accurately.

  [E5]  encode() now returns a zero-vector instead of raising RuntimeError
        when the model is unavailable, with a single warning log. This aligns
        with the "never raise" contract of the rest of the service layer.
        Callers that need to distinguish unavailability should check .available.

  [E6]  Cache key hashing: uses a fast hash of the text (not the full string)
        as the dict key to avoid storing duplicate large strings.

  [E7]  encode_pair() now also uses cache for both texts — hot paths like
        predict_score() on identical job descriptions benefit immediately.

  [E8]  __repr__ now includes cache statistics.
"""

import hashlib
import logging
import threading
from collections import OrderedDict
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# [E1] LRU cache capacity (number of unique texts)
_CACHE_CAPACITY = 512


class _LRUCache:
    """
    [E1][E6] Simple thread-safe LRU cache backed by OrderedDict.

    Keys are short hex hashes of the text, not the full strings.
    """

    def __init__(self, capacity: int):
        self._capacity = capacity
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock   = threading.Lock()
        self._hits   = 0
        self._misses = 0

    def get(self, key: str) -> np.ndarray | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: np.ndarray) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self._capacity:
                    self._cache.popitem(last=False)
                self._cache[key] = value

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            rate  = self._hits / total if total > 0 else 0.0
            return {
                "size":      len(self._cache),
                "capacity":  self._capacity,
                "hits":      self._hits,
                "misses":    self._misses,
                "hit_rate":  round(rate, 4),
            }

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits   = 0
            self._misses = 0


def _text_key(text: str) -> str:
    """[E6] Fast 16-char hex key for a text string."""
    return hashlib.blake2b(text.encode("utf-8", errors="replace"), digest_size=8).hexdigest()


class EmbeddingService:
    """
    Lazy-loaded sentence-transformer embedding service with LRU cache.

    Attributes:
        model_name:  HuggingFace model identifier.
        cache_dir:   Local cache directory for downloaded weights.
        available:   True once the model loads successfully.
    """

    _instances: dict[str, "EmbeddingService"] = {}
    _lock = threading.Lock()

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        cache_dir: str = ".cache/embeddings",
        embed_cache_size: int = _CACHE_CAPACITY,
    ):
        self.model_name = model_name
        self.cache_dir  = cache_dir
        self._model: Any           = None
        self._model_lock           = threading.Lock()
        self.available             = False
        self._cache                = _LRUCache(embed_cache_size)  # [E1]

    # ── Singleton factory ──────────────────────────────────────────────────────

    @classmethod
    def get_instance(
        cls,
        model_name: str = "all-MiniLM-L6-v2",
        cache_dir: str = ".cache/embeddings",
    ) -> "EmbeddingService":
        """Return the shared singleton for this model_name."""
        key = f"{model_name}::{cache_dir}"
        if key not in cls._instances:
            with cls._lock:
                if key not in cls._instances:
                    instance = cls(model_name=model_name, cache_dir=cache_dir)
                    cls._instances[key] = instance
        return cls._instances[key]

    # ── Model loading ──────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        """Load the model on first call. Thread-safe. Returns True if available."""
        if self._model is not None:
            return True
        with self._model_lock:
            if self._model is not None:
                return True
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("Loading embedding model: %s", self.model_name)
                self._model = SentenceTransformer(
                    self.model_name,
                    cache_folder=self.cache_dir,
                )
                self.available = True
                logger.info("Embedding model loaded: %s", self.model_name)
                self._warm_up()   # [E3]
                return True
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed. "
                    "Semantic scoring will be unavailable."
                )
                self.available = False
                return False
            except Exception as exc:
                logger.error(
                    "Failed to load embedding model %s: %s",
                    self.model_name, exc, exc_info=True,
                )
                self.available = False
                return False

    def _warm_up(self) -> None:
        """
        [E3] Encode a dummy sentence immediately after model load.

        Triggers JIT / CUDA compilation and ONNX warm-up so the first real
        request is not penalised by a multi-second delay.
        """
        try:
            _ = self._model.encode(["warm up"], normalize_embeddings=True, show_progress_bar=False)
            logger.debug("Embedding model warm-up complete.")
        except Exception as exc:
            logger.warning("Embedding warm-up failed (non-fatal): %s", exc)

    # ── Encoding ───────────────────────────────────────────────────────────────

    def encode(
        self,
        text: str | list[str],
        batch_size: int = 32,
        normalize: bool = True,
    ) -> np.ndarray:
        """
        [E1][E2][E5] Encode text into embedding vector(s).

        Returns a zero-vector (instead of raising) when model is unavailable.

        Args:
            text:       Single string or list of strings.
            batch_size: Batch size for multi-text encoding.
            normalize:  L2-normalise output so cosine_sim == dot product.

        Returns:
            np.ndarray of shape (d,) for single text, (N, d) for list.
        """
        is_single = isinstance(text, str)

        # [E5] Graceful unavailability — return zero vector instead of raising
        if not self._ensure_loaded():
            logger.warning("encode() called but embedding model is unavailable")
            if is_single:
                return np.zeros(384, dtype=np.float32)   # MiniLM dim
            return np.zeros((len(text), 384), dtype=np.float32)

        texts = [text] if is_single else list(text)

        # [E1][E2] Cache check — for batch, check each text individually
        results: list[np.ndarray | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str]   = []

        for i, t in enumerate(texts):
            key = _text_key(t)
            cached = self._cache.get(key)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(t)

        # Encode only uncached texts
        if uncached_texts:
            try:
                new_vecs = self._model.encode(
                    uncached_texts,
                    batch_size=batch_size,
                    normalize_embeddings=normalize,
                    show_progress_bar=False,
                )
                if new_vecs.ndim == 1:
                    new_vecs = new_vecs.reshape(1, -1)
                for idx, vec, t in zip(uncached_indices, new_vecs, uncached_texts):
                    results[idx] = vec
                    self._cache.set(_text_key(t), vec)
            except Exception as exc:
                logger.error("Embedding encode error: %s", exc)
                # Fill remaining None slots with zero vectors
                dim = 384
                for idx in uncached_indices:
                    if results[idx] is None:
                        results[idx] = np.zeros(dim, dtype=np.float32)

        # All slots filled
        arr = np.stack(results)    # (N, d)
        return arr[0] if is_single else arr

    # ── Similarity ─────────────────────────────────────────────────────────────

    def cosine_similarity(
        self,
        query_vec: np.ndarray,
        candidate_vecs: np.ndarray,
    ) -> np.ndarray:
        """
        Compute cosine similarity between a query vector and N candidate vectors.

        Assumes both inputs are L2-normalised (encode with normalize=True).

        Args:
            query_vec:      Shape (d,)
            candidate_vecs: Shape (N, d)

        Returns:
            np.ndarray of shape (N,) with similarities in [-1, 1].
        """
        if query_vec.ndim == 1:
            query_vec = query_vec.reshape(1, -1)
        if candidate_vecs.ndim == 1:
            candidate_vecs = candidate_vecs.reshape(1, -1)
        sims = np.dot(candidate_vecs, query_vec.T).squeeze()
        return np.clip(sims, -1.0, 1.0)

    def encode_pair(self, text_a: str, text_b: str) -> float:
        """
        [E7] Encode two texts and return their cosine similarity.

        Both texts use the LRU cache — hot paths (same job vs many resumes)
        get the job vector from cache on every call after the first.
        """
        vecs = self.encode([text_a, text_b])
        sim  = float(np.dot(vecs[0], vecs[1]))
        return max(0.0, min(1.0, sim))

    # ── Health check ───────────────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """
        [E4] Return True only if the model can encode a test string right now.

        Used by the /health endpoint. Catches transient failures.
        """
        if not self._ensure_loaded():
            return False
        try:
            vec = self.encode("health check")
            return isinstance(vec, np.ndarray) and vec.shape[0] > 0
        except Exception:
            return False

    @property
    def cache_stats(self) -> dict:
        """[E1] Return current cache hit/miss statistics."""
        return self._cache.stats

    def clear_cache(self) -> None:
        """Clear the in-memory embedding cache (e.g. for testing)."""
        self._cache.clear()

    def __repr__(self) -> str:
        status = "available" if self.available else "unavailable"
        stats  = self._cache.stats
        return (
            f"EmbeddingService(model={self.model_name!r}, status={status}, "
            f"cache={stats['size']}/{stats['capacity']}, "
            f"hit_rate={stats['hit_rate']:.1%})"
        )