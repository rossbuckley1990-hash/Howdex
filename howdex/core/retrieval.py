"""Keyword + graph search helpers (the non-vector half of hybrid retrieval)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from howdex.core.types import Memory

_TOKEN_RE = re.compile(r"\b\w+\b", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def keyword_score(query_tokens: list[str], memory: Memory) -> float:
    """Simple TF overlap score in [0, 1]."""
    if not query_tokens:
        return 0.0
    mem_tokens = tokenize(memory.content)
    # also tokenize metadata values
    for v in memory.metadata.values():
        if isinstance(v, str):
            mem_tokens.extend(tokenize(v))
    if not mem_tokens:
        return 0.0
    counter = Counter(mem_tokens)
    qcounter = Counter(query_tokens)
    overlap = sum((counter & qcounter).values())
    return overlap / (len(query_tokens) + 1e-9)


def graph_neighbors(memories: Iterable[Memory], seed_ids: set[str], hops: int = 1) -> set[str]:
    """BFS over memory.relations up to ``hops``. Returns neighbor IDs."""
    if not seed_ids:
        return set()
    by_id = {m.id: m for m in memories}
    visited = set(seed_ids)
    frontier = set(seed_ids)
    for _ in range(hops):
        nxt: set[str] = set()
        for sid in frontier:
            mem = by_id.get(sid)
            if not mem:
                continue
            for rel in mem.relations:
                target = rel.get("target") or rel.get("to") or rel.get("id")
                if target and target in by_id and target not in visited:
                    nxt.add(target)
        if not nxt:
            break
        visited |= nxt
        frontier = nxt
    return visited - set(seed_ids)
