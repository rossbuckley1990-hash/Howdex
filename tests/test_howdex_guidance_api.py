"""First-class Howdex.guidance() API tests."""

from __future__ import annotations

from typing import Any

from howdex import Howdex
from howdex.core.types import Procedure


def _store_procedure(memory: Howdex) -> Procedure:
    procedure = Procedure(
        id="guidance-procedure",
        task_signature="repair package dependency",
        steps=[
            {
                "canonical_name": "install_dependencies",
                "parameterized_args": {
                    "cmd": "npm install <PKG_1>",
                },
            },
            {
                "canonical_name": "run_test_suite",
                "parameterized_args": {"cmd": "npm test"},
            },
        ],
        expected_outcome="success",
        success_rate=1.0,
        sample_count=3,
        support_count=3,
        success_count=3,
        confidence=0.9,
        source_episode_ids=["episode-1"],
    )
    memory.store.put_procedure(dict(procedure.__dict__))
    return procedure


def test_guidance_returns_operational_memory(tmp_path):
    memory = Howdex(path=tmp_path / "guidance.db", embedder="hashing")
    _store_procedure(memory)

    guidance = memory.guidance("repair package dependency")

    assert "# HOWDEX OPERATIONAL MEMORY" in guidance
    assert "repair package dependency" in guidance


def test_guidance_includes_objective_constraints_and_environment(tmp_path):
    memory = Howdex(path=tmp_path / "constraints.db", embedder="hashing")

    guidance = memory.guidance(
        "Restore the service",
        constraints=["Do not modify lockfiles", "Run tests before finishing"],
        target_environment="Node.js 22",
    )

    assert "Objective:" in guidance
    assert "Restore the service" in guidance
    assert "Do not modify lockfiles" in guidance
    assert "Run tests before finishing" in guidance
    assert "Target environment: Node.js 22" in guidance


def test_guidance_uses_suggest_procedure_retrieval(tmp_path, monkeypatch):
    memory = Howdex(path=tmp_path / "retrieval.db", embedder="hashing")
    calls: list[dict[str, Any]] = []

    def fake_suggest(
        task: str,
        context: dict[str, Any] | str | None = None,
        top_k: int = 3,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        calls.append(
            {
                "task": task,
                "context": context,
                "top_k": top_k,
                "min_confidence": min_confidence,
            }
        )
        return [
            {
                "procedure_id": "retrieved",
                "task_signature": "retrieved procedure",
                "confidence": 0.8,
                "support_count": 2,
                "steps": [],
            }
        ]

    monkeypatch.setattr(memory, "suggest_procedure", fake_suggest)

    guidance = memory.guidance(
        "User-facing objective",
        query="retrieval-only query",
        top_k=2,
        min_confidence=0.75,
    )

    assert calls == [
        {
            "task": "retrieval-only query",
            "context": None,
            "top_k": 2,
            "min_confidence": 0.75,
        }
    ]
    assert "User-facing objective" in guidance
    assert "retrieval-only query" not in guidance
    assert "retrieved procedure" in guidance


def test_guidance_without_memory_still_returns_useful_markdown(tmp_path):
    memory = Howdex(path=tmp_path / "empty.db", embedder="hashing")

    guidance = memory.guidance("Diagnose the failing deployment")

    assert "# HOWDEX OPERATIONAL MEMORY" in guidance
    assert "Diagnose the failing deployment" in guidance
    assert "No prior procedure memory was provided." in guidance
    assert "run a real verifier command" not in guidance


def test_guidance_excludes_source_artifacts_by_default(
    tmp_path,
    monkeypatch,
):
    memory = Howdex(path=tmp_path / "source.db", embedder="hashing")

    monkeypatch.setattr(
        memory,
        "suggest_procedure",
        lambda *args, **kwargs: [
            {
                "task_signature": "source-backed procedure",
                "source_artifacts": [
                    {
                        "file_path": "private_decoder.py",
                        "content": "print('source should stay hidden')",
                    }
                ],
            }
        ],
    )

    guidance = memory.guidance("Rebuild the decoder")

    assert "private_decoder.py" not in guidance
    assert "source should stay hidden" not in guidance
    assert "Source artifacts excluded" in guidance


def test_guidance_respects_max_chars(tmp_path, monkeypatch):
    memory = Howdex(path=tmp_path / "bounded.db", embedder="hashing")
    monkeypatch.setattr(
        memory,
        "suggest_procedure",
        lambda *args, **kwargs: [
            {
                "task_signature": "large procedure",
                "learned_facts": [
                    f"operational fact {index}" for index in range(100)
                ],
            }
        ],
    )

    guidance = memory.guidance(
        "Produce bounded guidance",
        max_chars=500,
    )

    assert len(guidance) <= 500
    assert guidance.endswith("\n[Howdex guidance truncated]\n")


def test_guidance_is_deterministic_for_same_state_and_inputs(tmp_path):
    memory = Howdex(path=tmp_path / "deterministic.db", embedder="hashing")
    _store_procedure(memory)
    arguments = {
        "objective": "repair package dependency",
        "constraints": ["Keep changes minimal"],
        "target_environment": "Node.js",
    }

    first = memory.guidance(**arguments)
    second = memory.guidance(**arguments)

    assert first == second
