"""Deterministic working-memory context selection."""

from __future__ import annotations

import json
import time

from howdex.core.types import Memory, MemoryLayer

DEFAULT_WORKING_MAX_ITEMS = 20
DEFAULT_WORKING_MAX_CHARS = 4_000
CHARS_PER_TOKEN_APPROXIMATION = 4


def select_working_context(
    memories: list[Memory],
    *,
    max_items: int | None = DEFAULT_WORKING_MAX_ITEMS,
    max_chars: int | None = DEFAULT_WORKING_MAX_CHARS,
    token_budget: int | None = None,
    include_provenance: bool = True,
    now: float | None = None,
) -> tuple[list[Memory], str]:
    """Return the highest-value active items and their prompt-ready text."""
    effective_now = time.time() if now is None else now
    active = [
        memory
        for memory in memories
        if memory.layer == MemoryLayer.WORKING
        and not memory.is_expired(effective_now)
    ]
    ranked = rank_working_memories(active)
    item_limit = (
        len(ranked)
        if max_items is None
        else max(0, int(max_items))
    )
    char_limit = _effective_char_budget(max_chars, token_budget)
    if item_limit == 0 or char_limit == 0:
        return [], ""

    selected: list[Memory] = []
    lines: list[str] = []
    used_chars = 0
    for memory in ranked:
        if len(selected) >= item_limit:
            break
        line = render_working_memory(
            memory,
            include_provenance=include_provenance,
        )
        separator_cost = 1 if lines else 0
        if char_limit is None:
            selected.append(memory)
            lines.append(line)
            continue
        remaining = char_limit - used_chars - separator_cost
        if remaining <= 0:
            break
        if len(line) <= remaining:
            selected.append(memory)
            lines.append(line)
            used_chars += separator_cost + len(line)
            continue
        if not selected:
            selected.append(memory)
            lines.append(_truncate(line, remaining))
        break

    return selected, "\n".join(lines)


def rank_working_memories(memories: list[Memory]) -> list[Memory]:
    """Rank by deterministic importance plus relative recency."""
    recency_order = sorted(
        memories,
        key=lambda memory: (-memory.created_at, memory.id),
    )
    count = len(recency_order)
    recency_score = {
        memory.id: (
            1.0
            if count <= 1
            else 1.0 - (index / (count - 1))
        )
        for index, memory in enumerate(recency_order)
    }

    def score(memory: Memory) -> tuple[float, float, str]:
        importance = min(1.0, max(0.0, float(memory.importance)))
        combined = (0.65 * importance) + (0.35 * recency_score[memory.id])
        return (-round(combined, 12), -memory.created_at, memory.id)

    return sorted(memories, key=score)


def render_working_memory(
    memory: Memory,
    *,
    include_provenance: bool = True,
) -> str:
    """Render one working-memory item without model-dependent summarisation."""
    content = " ".join(str(memory.content or "").split())
    if not include_provenance:
        return content

    attributes = [
        f"source={memory.source}",
        f"importance={memory.importance:.2f}",
    ]
    provenance = (memory.metadata or {}).get("provenance")
    if provenance is not None:
        attributes.append(
            "provenance="
            + json.dumps(
                provenance,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                default=str,
            )
        )
    return f"- [{'; '.join(attributes)}] {content}"


def _effective_char_budget(
    max_chars: int | None,
    token_budget: int | None,
) -> int | None:
    char_limit = None if max_chars is None else max(0, int(max_chars))
    if token_budget is None:
        return char_limit
    token_chars = max(0, int(token_budget)) * CHARS_PER_TOKEN_APPROXIMATION
    return token_chars if char_limit is None else min(char_limit, token_chars)


def _truncate(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    return value[: limit - 1].rstrip() + "…"
