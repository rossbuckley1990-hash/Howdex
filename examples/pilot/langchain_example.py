"""Howdex pilot wiring for LangChain-style memory.

This example does not require LangChain at import time. ``HowdexMemory``
implements the conventional ``load_memory_variables`` and ``save_context``
methods without subclassing LangChain base classes.
"""

from __future__ import annotations

from pathlib import Path

from howdex import Howdex
from howdex.adapters.langchain import HowdexMemory


def build_memory(db_path: str | Path = "howdex-pilot.db") -> HowdexMemory:
    memory = Howdex(path=db_path, embedder="hashing")
    return HowdexMemory(memory, include_source=False, max_chars=4000)


def load_guidance(objective: str, *, db_path: str | Path = "howdex-pilot.db") -> str:
    howdex_memory = build_memory(db_path)
    variables = howdex_memory.load_memory_variables(
        {
            "input": objective,
            "constraints": ["Verify before treating the procedure as successful."],
            "target_environment": "local pilot sandbox",
        }
    )
    return variables["howdex_guidance"]


def save_context_example(
    howdex_memory: HowdexMemory,
    objective: str,
    output: str,
) -> None:
    howdex_memory.save_context(
        {"input": objective},
        {"output": output, "status": "success"},
    )


if __name__ == "__main__":
    print(load_guidance("Recover a local service health check"))
