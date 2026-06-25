from __future__ import annotations

import ast
import builtins
import importlib
import sys
from pathlib import Path

import pytest

from howdex import Howdex

OPTIONAL_MODULES = {"autogen", "crewai", "openai", "pyautogen"}


def _memory(tmp_path: Path) -> Howdex:
    return Howdex(path=tmp_path / "howdex.db", embedder="hashing")


def _block_optional_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def import_without_optional_sdks(
        name,
        globals=None,
        locals=None,
        fromlist=(),
        level=0,
    ):
        if name.split(".", 1)[0] in OPTIONAL_MODULES:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_optional_sdks)


def test_importing_adapters_does_not_require_crewai_autogen_or_openai(
    monkeypatch: pytest.MonkeyPatch,
):
    sys.modules.pop("howdex.adapters.crewai", None)
    sys.modules.pop("howdex.adapters.autogen", None)
    _block_optional_imports(monkeypatch)

    crewai = importlib.import_module("howdex.adapters.crewai")
    autogen = importlib.import_module("howdex.adapters.autogen")

    assert hasattr(crewai, "HowdexCrewAIAdapter")
    assert hasattr(autogen, "HowdexAutoGenAdapter")


def test_crewai_before_kickoff_returns_guidance_without_source(tmp_path):
    from howdex.adapters.crewai import HowdexCrewAIAdapter

    adapter = HowdexCrewAIAdapter(
        _memory(tmp_path),
        max_chars=900,
        verified_only=True,
    )

    guidance = adapter.before_kickoff(
        "Recover Docker Compose health",
        constraints=["Stay inside the sandbox"],
        environment={"docker": "local"},
    )

    assert guidance.startswith("# HOWDEX OPERATIONAL MEMORY")
    assert "Recover Docker Compose health" in guidance
    assert "Stay inside the sandbox" in guidance
    assert "Source artifacts excluded" in guidance
    assert len(guidance) <= 900


def test_crewai_lifecycle_logs_steps_and_learns(tmp_path):
    from howdex.adapters.crewai import HowdexCrewAIAdapter

    memory = _memory(tmp_path)
    adapter = HowdexCrewAIAdapter(memory, min_samples=1)

    session_id = adapter.start_task(
        "Recover Docker health",
        metadata={"crew": "unit-test"},
    )
    adapter.record_step(
        "ops_agent",
        "cat runtime.env",
        "HEALTH_MODE=degraded",
    )
    adapter.record_step(
        "ops_agent",
        "edit runtime.env set HEALTH_MODE=ready",
        "wrote runtime.env",
    )
    adapter.record_step(
        "ops_agent",
        "curl -sS -i http://127.0.0.1:52617/health",
        "SUCCESS: HTTP 200 body=healthy",
    )

    learned = adapter.after_kickoff(outcome="success", learn=True)

    assert session_id
    assert memory._current_session is None
    assert learned
    assert learned[0]["support_count"] >= 1


def test_crewai_memory_bridge_returns_plain_methods(tmp_path):
    from howdex.adapters.crewai import HowdexCrewAIAdapter

    bridge = HowdexCrewAIAdapter(_memory(tmp_path)).memory_bridge()

    assert {
        "before_kickoff",
        "start_task",
        "record_step",
        "after_kickoff",
        "guidance",
    }.issubset(bridge)
    assert all(callable(method) for method in bridge.values())
    assert bridge["guidance"]("Recover Docker health").startswith(
        "# HOWDEX OPERATIONAL MEMORY"
    )


def test_autogen_system_message_returns_guidance_without_source(tmp_path):
    from howdex.adapters.autogen import HowdexAutoGenAdapter

    adapter = HowdexAutoGenAdapter(
        _memory(tmp_path),
        max_chars=900,
        verified_only=True,
    )

    message = adapter.system_message(
        "Recover Docker Compose health",
        constraints=["Verify before success"],
        environment={"docker": "local"},
    )

    assert message.startswith("# HOWDEX OPERATIONAL MEMORY")
    assert "Recover Docker Compose health" in message
    assert "Verify before success" in message
    assert "Source artifacts excluded" in message
    assert len(message) <= 900


def test_autogen_lifecycle_logs_messages_tool_calls_and_learns(tmp_path):
    from howdex.adapters.autogen import HowdexAutoGenAdapter

    memory = _memory(tmp_path)
    adapter = HowdexAutoGenAdapter(memory, min_samples=1)

    session_id = adapter.start_conversation_task(
        "Recover Docker health",
        metadata={"conversation": "unit-test"},
    )
    adapter.record_message(
        "assistant",
        "I will inspect the runtime configuration before changing anything.",
    )
    adapter.record_tool_call(
        "bash",
        {"cmd": "cat runtime.env"},
        "HEALTH_MODE=degraded",
    )
    adapter.record_tool_call(
        "fs.write",
        {"path": "runtime.env", "content": "HEALTH_MODE=ready"},
        "wrote runtime.env",
    )
    adapter.record_tool_call(
        "bash",
        {"cmd": "curl -sS -i http://127.0.0.1:52617/health"},
        "SUCCESS: HTTP 200 body=healthy",
    )

    learned = adapter.end_conversation_task(outcome="success", learn=True)

    assert session_id
    assert memory._current_session is None
    assert learned
    assert learned[0]["confidence"] > 0


def test_plain_adapter_methods_do_not_import_optional_sdks(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from howdex.adapters.autogen import HowdexAutoGenAdapter
    from howdex.adapters.crewai import HowdexCrewAIAdapter

    _block_optional_imports(monkeypatch)

    crewai = HowdexCrewAIAdapter(_memory(tmp_path / "crew"))
    autogen = HowdexAutoGenAdapter(_memory(tmp_path / "autogen"))

    crewai.before_kickoff("Recover Docker health")
    crewai.memory_bridge()["guidance"]("Recover Docker health")
    autogen.system_message("Recover Docker health")


def test_crewai_autogen_have_no_top_level_optional_imports():
    imported = set()
    for path in (
        Path("howdex/adapters/crewai.py"),
        Path("howdex/adapters/autogen.py"),
    ):
        imported |= _top_level_imports(path.read_text(encoding="utf-8"))

    assert imported.isdisjoint(OPTIONAL_MODULES)


def test_crewai_autogen_are_not_required_dependencies():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    project_dependencies = text.split("dependencies = [", 1)[1].split("]", 1)[0]

    assert "crewai" not in project_dependencies
    assert "autogen" not in project_dependencies
    assert "pyautogen" not in project_dependencies


def _top_level_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules
