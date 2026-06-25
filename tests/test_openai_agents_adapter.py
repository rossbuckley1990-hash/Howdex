from __future__ import annotations

import ast
import builtins
import importlib
import sys
from pathlib import Path

import pytest

from howdex import Howdex


def _memory(tmp_path: Path) -> Howdex:
    return Howdex(path=tmp_path / "howdex.db", embedder="hashing")


def test_importing_adapter_does_not_require_openai_or_agents(
    monkeypatch: pytest.MonkeyPatch,
):
    sys.modules.pop("howdex.adapters.openai_agents", None)
    real_import = builtins.__import__

    def import_without_optional_sdks(
        name,
        globals=None,
        locals=None,
        fromlist=(),
        level=0,
    ):
        if name in {"openai", "agents"}:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_optional_sdks)

    module = importlib.import_module("howdex.adapters.openai_agents")

    assert hasattr(module, "HowdexOpenAIAgentsAdapter")


def test_instructions_returns_howdex_markdown(tmp_path):
    from howdex.adapters.openai_agents import HowdexOpenAIAgentsAdapter

    adapter = HowdexOpenAIAgentsAdapter(
        _memory(tmp_path),
        verified_only=True,
        include_source=False,
    )

    guidance = adapter.instructions(
        "Recover Docker Compose health",
        constraints=["Stay inside the sandbox"],
        environment={"docker": "available"},
        max_chars=900,
    )

    assert guidance.startswith("# HOWDEX OPERATIONAL MEMORY")
    assert "Recover Docker Compose health" in guidance
    assert "Stay inside the sandbox" in guidance
    assert "Source artifacts excluded" in guidance
    assert len(guidance) <= 900


def test_start_record_end_task_lifecycle_learns(tmp_path):
    from howdex.adapters.openai_agents import HowdexOpenAIAgentsAdapter

    memory = _memory(tmp_path)
    adapter = HowdexOpenAIAgentsAdapter(memory, min_samples=1)

    session_id = adapter.start_task(
        "Recover Docker health",
        metadata={"agent": "unit-test"},
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

    learned = adapter.end_task(outcome="success", learn=True)

    assert session_id
    assert memory._current_session is None
    assert learned
    assert learned[0]["support_count"] >= 1
    assert learned[0]["confidence"] > 0


def test_as_tools_returns_plain_python_callables(tmp_path):
    from howdex.adapters.openai_agents import HowdexOpenAIAgentsAdapter

    memory = _memory(tmp_path)
    adapter = HowdexOpenAIAgentsAdapter(memory)

    tools = adapter.as_tools()

    assert {
        "howdex_guidance",
        "howdex_remember",
        "howdex_learn",
    }.issubset(tools)
    assert all(callable(tool) for tool in tools.values())
    assert tools["howdex_guidance"]("Recover Docker health").startswith(
        "# HOWDEX OPERATIONAL MEMORY"
    )
    assert tools["howdex_remember"]("Check DATABASE_URL before deployment.") == "remembered"
    assert "DATABASE_URL" in tools["inspect_howdex"]("deployment")
    assert isinstance(tools["howdex_learn"](min_samples=1), list)


def test_plain_adapter_methods_do_not_import_openai_or_agents(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from howdex.adapters.openai_agents import HowdexOpenAIAgentsAdapter

    real_import = builtins.__import__

    def import_without_optional_sdks(
        name,
        globals=None,
        locals=None,
        fromlist=(),
        level=0,
    ):
        if name in {"openai", "agents"}:
            raise AssertionError(f"unexpected optional SDK import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_optional_sdks)
    adapter = HowdexOpenAIAgentsAdapter(_memory(tmp_path))

    adapter.instructions("Recover Docker health")
    adapter.as_tools()["howdex_guidance"]("Recover Docker health")


def test_openai_adapter_has_no_top_level_optional_sdk_imports():
    source = Path("howdex/adapters/openai_agents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.add(node.module.split(".", 1)[0])

    assert "openai" not in top_level_imports
    assert "agents" not in top_level_imports


def test_openai_is_not_a_required_dependency():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    project_dependencies = text.split("dependencies = [", 1)[1].split("]", 1)[0]

    assert "openai" not in project_dependencies
    assert "openai-agents" not in project_dependencies
