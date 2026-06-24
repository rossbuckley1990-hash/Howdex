from __future__ import annotations

import ast
import builtins
import importlib
import json
import sys
from pathlib import Path

import pytest

from howdex import Howdex

OPTIONAL_MODULES = {
    "autogen",
    "crewai",
    "langchain",
    "langgraph",
    "openai",
    "pyautogen",
}


def _memory(tmp_path: Path) -> Howdex:
    return Howdex(path=tmp_path / "howdex.db", embedder="hashing")


def _episodes(memory: Howdex) -> list[dict]:
    return memory.store.query_episodes(limit=100)


def _steps(episode: dict) -> list[dict]:
    return json.loads(episode["steps"])


def test_decorated_task_logs_success(tmp_path):
    from howdex.adapters.generic import howdex_task

    memory = _memory(tmp_path)

    @howdex_task(memory, objective="Recover Docker health", learn=False)
    def run_task():
        return "done"

    assert run_task() == "done"

    episodes = _episodes(memory)
    assert len(episodes) == 1
    assert episodes[0]["task"] == "Recover Docker health"
    assert episodes[0]["outcome"] == "success"
    assert memory._current_session is None


def test_decorated_task_logs_error(tmp_path):
    from howdex.adapters.generic import howdex_task

    memory = _memory(tmp_path)

    @howdex_task(memory, objective="Failing task", learn=False)
    def run_task():
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        run_task()

    episodes = _episodes(memory)
    assert len(episodes) == 1
    assert episodes[0]["task"] == "Failing task"
    assert episodes[0]["outcome"] == "failure"
    assert "ValueError" in episodes[0]["error"]
    assert memory._current_session is None


def test_decorated_tool_logs_arguments_result_and_errors(tmp_path):
    from howdex.adapters.generic import howdex_task, howdex_tool

    memory = _memory(tmp_path)

    @howdex_tool(memory, name="math.add")
    def add(left: int, right: int = 1) -> int:
        return left + right

    @howdex_tool(memory, name="math.fail")
    def fail() -> None:
        raise RuntimeError("tool exploded")

    @howdex_task(memory, objective="Use Python tools", learn=False)
    def run_task() -> None:
        assert add(2, right=3) == 5
        with pytest.raises(RuntimeError):
            fail()

    run_task()

    steps = _steps(_episodes(memory)[0])
    assert steps[0]["tool_name"] == "math.add"
    assert steps[0]["tool_args"] == {"left": 2, "right": 3}
    assert steps[0]["observation"] == "5"
    assert steps[0]["outcome"] == "success"
    assert steps[1]["tool_name"] == "math.fail"
    assert steps[1]["outcome"] == "failure"
    assert "RuntimeError" in steps[1]["error"]


def test_tool_decorator_without_active_session_does_not_crash(tmp_path):
    from howdex.adapters.generic import howdex_tool

    memory = _memory(tmp_path)

    @howdex_tool(memory)
    def echo(value: str) -> str:
        return value

    assert echo("hello") == "hello"
    assert memory.stats()["episodes"] == 0


def test_middleware_returns_guidance(tmp_path):
    from howdex.adapters.generic import HowdexMiddleware

    memory = _memory(tmp_path)
    middleware = HowdexMiddleware(memory, max_chars=900, verified_only=True)

    guidance = middleware.before_task(
        "Recover Docker health",
        constraints=["Stay inside sandbox"],
        environment={"docker": "local"},
    )
    learned = middleware.after_task("success", learn=False)

    assert guidance.startswith("# HOWDEX OPERATIONAL MEMORY")
    assert "Recover Docker health" in guidance
    assert "Stay inside sandbox" in guidance
    assert "Source artifacts excluded" in guidance
    assert len(guidance) <= 900
    assert learned == []


def test_middleware_learns_at_after_task_when_enabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from howdex.adapters.generic import HowdexMiddleware

    memory = _memory(tmp_path)
    calls: list[int] = []
    original_learn = memory.learn

    def tracked_learn(*, min_samples: int = 3, dry_run: bool = False):
        calls.append(min_samples)
        return original_learn(min_samples=min_samples, dry_run=dry_run)

    monkeypatch.setattr(memory, "learn", tracked_learn)
    middleware = HowdexMiddleware(memory, min_samples=1)

    middleware.before_task("Recover Docker health")
    middleware.after_tool("bash", {"cmd": "cat runtime.env"}, "HEALTH_MODE=degraded", "success")
    middleware.after_tool(
        "fs.write",
        {"path": "runtime.env", "content": "HEALTH_MODE=ready"},
        "wrote runtime.env",
        "success",
    )
    middleware.after_tool(
        "bash",
        {"cmd": "curl -sS -i http://127.0.0.1:52617/health"},
        "SUCCESS: HTTP 200 body=healthy",
        "success",
    )
    learned = middleware.after_task("success", learn=True)

    assert calls == [1]
    assert learned
    assert learned[0]["confidence"] > 0


def test_nested_sessions_preserve_parent_session(tmp_path):
    from howdex.adapters.generic import howdex_task, howdex_tool

    memory = _memory(tmp_path)
    parent_session_ids: list[str] = []

    @howdex_tool(memory, name="bash")
    def run_command(cmd: str) -> str:
        return f"ran {cmd}"

    @howdex_task(memory, objective="Inner task", learn=False)
    def inner_task() -> str:
        run_command("inner")
        return "inner done"

    @howdex_task(memory, objective="Outer task", learn=False)
    def outer_task() -> str:
        run_command("outer-before")
        parent_session_ids.append(memory._current_session.session_id)
        assert inner_task() == "inner done"
        assert memory._current_session is not None
        assert memory._current_session.session_id == parent_session_ids[0]
        run_command("outer-after")
        return "outer done"

    assert outer_task() == "outer done"

    episodes = {episode["task"]: episode for episode in _episodes(memory)}
    assert set(episodes) == {"Outer task", "Inner task"}
    assert episodes["Outer task"]["outcome"] == "success"
    assert episodes["Inner task"]["outcome"] == "success"
    assert [step["tool_args"]["cmd"] for step in _steps(episodes["Outer task"])] == [
        "outer-before",
        "outer-after",
    ]
    assert [step["tool_args"]["cmd"] for step in _steps(episodes["Inner task"])] == [
        "inner"
    ]
    assert memory._current_session is None


def test_importing_generic_adapter_requires_no_optional_frameworks(
    monkeypatch: pytest.MonkeyPatch,
):
    sys.modules.pop("howdex.adapters.generic", None)
    real_import = builtins.__import__

    def import_without_optional_frameworks(
        name,
        globals=None,
        locals=None,
        fromlist=(),
        level=0,
    ):
        if name.split(".", 1)[0] in OPTIONAL_MODULES:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_optional_frameworks)

    module = importlib.import_module("howdex.adapters.generic")

    assert hasattr(module, "howdex_task")
    assert hasattr(module, "howdex_tool")
    assert hasattr(module, "HowdexMiddleware")


def test_generic_adapter_has_no_top_level_optional_imports():
    source = Path("howdex/adapters/generic.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])

    assert imports.isdisjoint(OPTIONAL_MODULES)
