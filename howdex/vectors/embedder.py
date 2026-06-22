"""Pluggable embedding backends.

Howdex prefers the optional local sentence-transformers backend when available.
The hashing backend is deterministic, dependency-free, and retained as the
CI/offline fallback. OpenAI embeddings remain an explicit opt-in adapter.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

import numpy as np

from howdex.core.errors import EmbeddingError


from howdex.vectors.hash_embedder import HashEmbedder
class Embedder:
    """Base interface. Subclasses implement ``embed(text) -> list[float]``."""

    name = "base"
    dim = 0

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class HashingEmbedder(Embedder):
    """Deterministic, dependency-free embedder.

    Uses character n-gram hashing into a fixed-dimensional space. Quality
    is below neural embedders but it always works offline and is great for
    tests. For production, swap in :class:`SentenceTransformerEmbedder`.
    """

    name = "hashing"
    dim = 384

    def __init__(self, dim: int = 384, ngram: int = 3):
        self.dim = dim
        self.ngram = ngram

    def embed(self, text: str) -> list[float]:
        text = (text or "").lower()
        vec = np.zeros(self.dim, dtype=np.float32)

        if not text:
            return vec.tolist()

        # word-level features
        for word in text.split():
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0

        # char n-grams
        for i in range(len(text) - self.ngram + 1):
            gram = text[i : i + self.ngram]
            h = int(hashlib.sha1(gram.encode()).hexdigest(), 16)
            vec[h % self.dim] += 0.5

        # L2 normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm

        return vec.tolist()


class SentenceTransformerEmbedder(Embedder):
    """Local neural embedder via ``sentence-transformers``.

    Install: ``pip install sentence-transformers``.
    Default model: ``all-MiniLM-L6-v2`` (384 dim, ~80MB).
    """

    name = "sentence-transformer"
    dim = 384

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:
            raise EmbeddingError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            ) from e
        self._model = SentenceTransformer(model_name)
        if hasattr(self._model, "get_embedding_dimension"):
            self.dim = self._model.get_embedding_dimension() or 384
        else:
            self.dim = self._model.get_sentence_embedding_dimension() or 384
        self.name = f"sentence-transformer:{model_name}"

    def embed(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


class OpenAIEmbedder(Embedder):
    """OpenAI ``text-embedding-3-small`` (1536 dim).

    Requires ``OPENAI_API_KEY`` and ``openai`` package.
    """

    name = "openai"
    dim = 1536

    def __init__(self, model: str = "text-embedding-3-small"):
        try:
            import openai  # type: ignore
        except ImportError as e:
            raise EmbeddingError("openai not installed. Run: pip install openai") from e
        if not os.getenv("OPENAI_API_KEY"):
            raise EmbeddingError("OPENAI_API_KEY not set")
        self._client = openai.OpenAI()
        self._model = model
        self.name = f"openai:{model}"

    def embed(self, text: str) -> list[float]:
        return self._client.embeddings.create(input=text, model=self._model).data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(input=texts, model=self._model)
        return [d.embedding for d in resp.data]


def auto_embedder(preferred: Optional[str] = None, dim: int = 384) -> Embedder:
    """Pick the configured embedder.

    Priority:
      1. explicit ``preferred``
      2. ``HOWDEX_EMBEDDER`` environment variable
      3. neural sentence-transformer default

    Set ``HOWDEX_EMBEDDER=hash`` for CI/offline runs. In hash mode this
    function must not initialise sentence-transformers or contact Hugging Face.
    """
    mode = (preferred or os.getenv("HOWDEX_EMBEDDER", "")).strip().lower()

    if mode in {"openai"}:
        return OpenAIEmbedder()

    if mode in {"st", "sbert", "sentence-transformers", "sentence_transformers", "neural"}:
        return SentenceTransformerEmbedder()

    if mode in {"hash", "hashing", "local", "offline", "ci"}:
        return HashingEmbedder(dim=dim)

    if mode:
        raise ValueError(
            f"Unknown embedder mode: {mode!r}. "
            "Use one of: openai, st, sentence-transformers, hash."
        )

    # Product-quality default. CI/offline runs should set HOWDEX_EMBEDDER=hash.
    try:
        return SentenceTransformerEmbedder()
    except EmbeddingError:
        return HashingEmbedder(dim=dim)
