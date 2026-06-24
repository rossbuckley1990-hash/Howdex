"""Framework-neutral Howdex pilot loop.

Use this when your agent is just Python functions and tool calls.
"""

from __future__ import annotations

from pathlib import Path

from howdex import Howdex
from howdex.adapters.generic import HowdexMiddleware, howdex_task, howdex_tool


def create_memory(db_path: str | Path = "howdex-pilot.db") -> Howdex:
    return Howdex(path=db_path, embedder="hashing")


def middleware_guidance(
    objective: str,
    *,
    db_path: str | Path = "howdex-pilot.db",
) -> str:
    memory = create_memory(db_path)
    middleware = HowdexMiddleware(memory, include_source=False, max_chars=4000)
    return middleware.before_task(
        objective,
        constraints=["Do not include source artifacts by default."],
        environment="local pilot sandbox",
    )


def build_decorated_tools(memory: Howdex):
    @howdex_tool(memory, name="filesystem.read_file")
    def read_file(path: str) -> str:
        return f"read {path}"

    @howdex_task(memory, objective="Inspect package manifest", learn=True)
    def inspect_manifest() -> str:
        return read_file("package.json")

    return inspect_manifest


if __name__ == "__main__":
    pilot_memory = create_memory()
    task = build_decorated_tools(pilot_memory)
    print(task())
