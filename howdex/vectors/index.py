"""Vector indexing for Howdex.

Two backends, auto-selected at runtime:

* **hnswlib** — production-grade HNSW. Used if installed (``pip install hnswlib``).
* **NumPy brute-force** — pure-python fallback. Slower but always works.

Both expose the same :class:`VectorIndex` interface.
"""

from __future__ import annotations

import threading

import numpy as np

from howdex.core.errors import HowdexError


class VectorIndex:
    """ANN index over memory embeddings.

    The index is *ephemeral* — it lives in process memory and is rebuilt
    from SQLite on engine startup. Writes are mirrored into the index
    immediately.
    """

    def __init__(self, dim: int, metric: str = "cosine", max_elements: int = 1_000_000):
        self.dim = dim
        self.metric = metric
        self.max_elements = max_elements
        self._ids: list[str] = []
        self._id_to_pos: dict[str, int] = {}
        self._lock = threading.RLock()
        self._backend = "numpy"
        self._np: np.ndarray | None = None  # (N, dim) float32
        try:
            import hnswlib  # type: ignore
            self._hnsw = hnswlib.Index(space=metric, dim=dim)
            self._hnsw.init_index(max_elements=max_elements, ef_construction=200, M=16)
            self._hnsw.set_ef(64)
            self._backend = "hnswlib"
        except ImportError:
            self._hnsw = None

    @property
    def backend(self) -> str:
        return self._backend

    def add(self, mem_id: str, vec: list[float] | np.ndarray) -> None:
        vec = np.asarray(vec, dtype=np.float32)
        if vec.shape != (self.dim,):
            raise HowdexError(f"embedding dim mismatch: expected {self.dim}, got {vec.shape}")
        with self._lock:
            if self._backend == "hnswlib":
                if len(self._ids) >= self.max_elements:
                    self._hnsw.resize_index(self.max_elements * 2)
                    self.max_elements *= 2
                self._hnsw.add_items(vec[None, :], [len(self._ids)])
            else:
                if self._np is None:
                    self._np = np.empty((self.max_elements, self.dim), dtype=np.float32)
                if len(self._ids) >= self.max_elements:
                    new = np.empty((self.max_elements * 2, self.dim), dtype=np.float32)
                    new[: len(self._ids)] = self._np[: len(self._ids)]
                    self._np = new
                    self.max_elements *= 2
                self._np[len(self._ids)] = vec
            self._id_to_pos[mem_id] = len(self._ids)
            self._ids.append(mem_id)

    def remove(self, mem_id: str) -> None:
        """Soft removal — mark ID as None. Compaction happens on rebuild."""
        with self._lock:
            if mem_id not in self._id_to_pos:
                return
            # we don't physically remove from hnswlib/numpy; we just stop
            # returning it. The position is left empty.
            pos = self._id_to_pos.pop(mem_id)
            self._ids[pos] = ""

    def search(
        self, query: list[float] | np.ndarray, k: int = 5, min_score: float = 0.0
    ) -> list[tuple[str, float]]:
        """Return ``[(mem_id, score), ...]`` sorted by descending score.

        ``score`` is similarity in [0, 1] for cosine, [0, ∞) for L2.
        """
        if not self._ids:
            return []
        query = np.asarray(query, dtype=np.float32)
        with self._lock:
            if self._backend == "hnswlib":
                labels, distances = self._hnsw.knn_query(query[None, :], k=min(k * 2, len(self._ids)))
                out: list[tuple[str, float]] = []
                for lbl, dist in zip(labels[0], distances[0], strict=False):
                    mem_id = self._ids[lbl] if lbl < len(self._ids) else ""
                    if not mem_id:
                        continue
                    score = 1.0 - float(dist) if self.metric == "cosine" else -float(dist)
                    if score >= min_score:
                        out.append((mem_id, score))
                    if len(out) >= k:
                        break
                return out
            # numpy brute-force cosine
            n = len(self._ids)
            mat = self._np[:n]
            qn = query / (np.linalg.norm(query) + 1e-9)
            mn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
            sims = mn @ qn
            order = np.argsort(-sims)[: k * 2]
            out = []
            for i in order:
                mem_id = self._ids[i]
                if not mem_id:
                    continue
                score = float(sims[i])
                if score >= min_score:
                    out.append((mem_id, score))
                if len(out) >= k:
                    break
            return out

    def __len__(self) -> int:
        return len(self._id_to_pos)
