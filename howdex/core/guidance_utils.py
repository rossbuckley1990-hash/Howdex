"""Shared deterministic helpers for Howdex guidance rendering."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def get_value(item: Any, name: str, default: Any = None) -> Any:
    """Read one field from either a mapping or an object."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def as_list(value: Any) -> list[Any]:
    """Normalize optional scalar/iterable values without splitting strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, Iterable):
        return [item for item in value if item is not None]
    return [value]


def unique_strings(values: Any) -> list[str]:
    """Return non-empty strings once, preserving deterministic input order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in as_list(values):
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def truncate_with_marker(
    text: str,
    max_chars: int | None,
    *,
    marker: str,
) -> str:
    """Bound text deterministically and retain an explicit truncation marker."""
    if max_chars is None:
        return text
    limit = int(max_chars)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(marker):
        return marker[:limit]
    return text[: limit - len(marker)].rstrip() + marker

