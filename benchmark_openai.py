"""Lazy OpenAI client helper for live benchmark scripts.

Benchmark modules are imported by unit tests, but OpenAI is an optional
dependency. Keep imports lazy so clean installs can collect tests without the
live benchmark dependency installed.
"""

from __future__ import annotations

from typing import Any


def get_openai_client() -> Any:
    """Return an OpenAI client, or raise a clear live-benchmark error."""
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The OpenAI optional dependency is required to run this live benchmark. "
            "Install with `pip install howdex-ai[openai]` or `pip install openai`."
        ) from exc
    return OpenAI()
