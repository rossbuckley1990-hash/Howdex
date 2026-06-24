from __future__ import annotations

import ast
import importlib
from pathlib import Path

from howdex import Howdex


def _memory(tmp_path: Path) -> Howdex:
    return Howdex(path=tmp_path / "howdex.db", embedder="hashing")


def test_adapters_import_without_langgraph_or_langchain_installed():
    langgraph = importlib.import_module("howdex.adapters.langgraph")
    langchain = importlib.import_module("howdex.adapters.langchain")

    assert hasattr(langgraph, "HowdexLangGraphAdapter")
    assert hasattr(langchain, "HowdexMemory")


def test_before_node_adds_guidance_without_mutating_unrelated_fields(tmp_path):
    from howdex.adapters.langgraph import HowdexLangGraphAdapter

    memory = _memory(tmp_path)
    adapter = HowdexLangGraphAdapter(memory, max_chars=900, verified_only=True)
    state = {
        "objective": "Recover Docker health endpoint",
        "keep": {"nested": True},
        "constraints": ["Use local Docker only"],
    }

    updated = adapter.before_node(state)

    assert "howdex_guidance" not in state
    assert updated["keep"] == {"nested": True}
    assert updated["howdex_guidance"].startswith("# HOWDEX OPERATIONAL MEMORY")
    assert len(updated["howdex_guidance"]) <= 900
    assert "Source artifacts excluded" in updated["howdex_guidance"]


def test_after_tool_call_logs_steps(tmp_path):
    from howdex.adapters.langgraph import HowdexLangGraphAdapter

    memory = _memory(tmp_path)
    adapter = HowdexLangGraphAdapter(memory)
    state = adapter.start_task({"objective": "Inspect runtime"})

    updated = adapter.after_tool_call(
        state,
        "bash",
        {"cmd": "cat runtime.env"},
        "HEALTH_MODE=ready",
    )

    assert updated["howdex_last_tool"] == "bash"
    assert updated["howdex_logged_steps"] == 1
    assert memory._current_session is not None
    assert len(memory._current_session.steps) == 1
    assert memory._current_session.steps[0]["tool_name"] == "bash"


def test_start_task_end_task_lifecycle_learns(tmp_path):
    from howdex.adapters.langgraph import HowdexLangGraphAdapter

    memory = _memory(tmp_path)
    adapter = HowdexLangGraphAdapter(memory, min_samples=1)
    state = adapter.start_task({"objective": "Recover Docker health"})
    state = adapter.after_tool_call(
        state,
        "bash",
        {"cmd": "cat runtime.env"},
        "HEALTH_MODE=degraded",
    )
    state = adapter.after_tool_call(
        state,
        "fs.write",
        {"path": "runtime.env", "content": "HEALTH_MODE=ready"},
        "wrote runtime.env",
    )
    state = adapter.after_tool_call(
        state,
        "bash",
        {"cmd": "curl -sS -i http://127.0.0.1:52617/health"},
        "SUCCESS: HTTP 200 body=healthy",
    )

    ended = adapter.end_task(state)

    assert ended["howdex_episode_id"] == state["howdex_session_id"]
    assert ended["howdex_learned_procedures"]
    assert ended["howdex_learned_procedures"][0]["confidence"] > 0
    assert memory._current_session is None


def test_langgraph_middleware_wraps_node(tmp_path):
    from howdex.adapters.langgraph import HowdexLangGraphAdapter

    memory = _memory(tmp_path)
    adapter = HowdexLangGraphAdapter(memory)

    def node(state):
        return {"saw_guidance": "howdex_guidance" in state}

    wrapped = adapter.middleware(node)

    assert wrapped({"objective": "Do the task"}) == {"saw_guidance": True}


def test_langchain_memory_load_memory_variables_returns_guidance(tmp_path):
    from howdex.adapters.langchain import HowdexMemory

    memory = _memory(tmp_path)
    adapter = HowdexMemory(memory, max_chars=800, verified_only=True)

    variables = adapter.load_memory_variables(
        {"input": "Recover Docker health", "constraints": ["No source paste"]}
    )

    assert set(variables) == {"howdex_guidance"}
    assert variables["howdex_guidance"].startswith("# HOWDEX OPERATIONAL MEMORY")
    assert len(variables["howdex_guidance"]) <= 800
    assert "Source artifacts excluded" in variables["howdex_guidance"]


def test_langchain_save_context_logs_step_and_clear_closes_session(tmp_path):
    from howdex.adapters.langchain import HowdexMemory

    memory = _memory(tmp_path)
    adapter = HowdexMemory(memory)

    adapter.save_context(
        {"input": "Recover Docker health"},
        {"output": "Checked runtime.env", "status": "success"},
    )

    assert memory._current_session is not None
    assert len(memory._current_session.steps) == 1
    assert memory._current_session.steps[0]["action"] == "langchain_context"

    adapter.clear()

    assert memory._current_session is None
    assert memory.stats()["episodes"] == 1


def test_langchain_existing_tool_adapter_still_imports_and_inspects(tmp_path):
    from howdex.adapters.langchain import HowdexLangChainAdapter

    memory = _memory(tmp_path)
    memory.remember("Check DATABASE_URL before deployment.")
    adapter = HowdexLangChainAdapter(memory)

    assert "DATABASE_URL" in adapter.inspect_howdex("deployment")


def test_adapters_have_no_openai_or_required_framework_imports():
    langgraph_source = Path("howdex/adapters/langgraph.py").read_text(encoding="utf-8")
    langchain_source = Path("howdex/adapters/langchain.py").read_text(encoding="utf-8")
    imported = _imported_modules(langgraph_source) | _imported_modules(langchain_source)

    assert "openai" not in imported
    assert "langgraph" not in imported
    assert "langchain" not in imported


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules
