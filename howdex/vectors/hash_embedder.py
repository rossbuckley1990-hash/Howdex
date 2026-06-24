from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


@dataclass
class HashEmbedder:
    """Small deterministic embedder for tests/CI.

    This is not intended to beat semantic embedding models. It provides stable,
    dependency-free vectors so Howdex can run in CI without downloading models.
    """

    dim: int = 384

    def encode(self, texts):
        single = isinstance(texts, str)

        if single:
            texts = [texts]

        vectors = [self._embed(text) for text in texts]

        return vectors[0] if single else vectors

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim

        tokens = TOKEN_RE.findall((text or "").lower())

        if not tokens:
            return vec

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
