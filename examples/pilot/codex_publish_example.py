"""Publish learned Howdex procedures to a local Codex folder."""

from __future__ import annotations

from pathlib import Path

from howdex import Howdex


def learn_example_procedure(memory: Howdex) -> list:
    memory.start_session("Fix a missing package before running tests")
    memory.log_step("inspect package.json", "missing dependency was visible")
    memory.log_step("npm install <PKG_1>", "dependency installed")
    memory.log_step("run pytest", "12 passed")
    memory.end_session("success")
    return memory.learn(min_samples=1)


def publish_candidate_codex(
    db_path: str | Path = "howdex-pilot.db",
    codex_path: str | Path = "./codex",
) -> dict:
    memory = Howdex(path=db_path, embedder="hashing")
    try:
        if not memory.list_procedures():
            learn_example_procedure(memory)
        return memory.publish_codex(codex_path)
    finally:
        memory.close()


if __name__ == "__main__":
    result = publish_candidate_codex()
    print(f"published={result['exported']} output={result['output']}")
