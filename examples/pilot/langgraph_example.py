"""Howdex pilot wiring for LangGraph-style state dictionaries.

This example imports no LangGraph package. The Howdex adapter works with plain
state dictionaries, so the module remains importable even when LangGraph is not
installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from howdex import Howdex
from howdex.adapters.langgraph import HowdexLangGraphAdapter


def build_adapter(db_path: str | Path = "howdex-pilot.db") -> HowdexLangGraphAdapter:
    memory = Howdex(path=db_path, embedder="hashing")
    return HowdexLangGraphAdapter(memory, include_source=False, max_chars=4000)


def prepare_state(
    objective: str,
    *,
    db_path: str | Path = "howdex-pilot.db",
) -> dict[str, Any]:
    adapter = build_adapter(db_path)
    state = {
        "objective": objective,
        "constraints": [
            "Do not paste source artifacts into guidance.",
            "Verify before claiming success.",
        ],
        "target_environment": "local pilot sandbox",
    }
    return adapter.before_node(state)


def record_tool_example(
    adapter: HowdexLangGraphAdapter,
    state: dict[str, Any],
) -> dict[str, Any]:
    started = adapter.start_task(state)
    after_tool = adapter.after_tool_call(
        started,
        "filesystem.read_file",
        {"path": "package.json"},
        "read package manifest",
    )
    return adapter.end_task(after_tool, outcome="success")


if __name__ == "__main__":
    print(prepare_state("Fix a failing local test command")["howdex_guidance"])
