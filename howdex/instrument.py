"""Low-boilerplate instrumentation for Howdex (Integration Tax mitigation).

Addresses the "Integration Tax" from the Day-2 operational risk review:

    "Howdex is not a magic wrapper you can just slap around an OpenAI
    client. It requires you to structure your agent as a rigorous CI/CD
    pipeline with explicit telemetry (log_step). Developers migrating
    from LangChain will complain about the boilerplate."

This module provides three zero-boilerplate ways to instrument existing
code with Howdex telemetry:

1. **``@instrument`` decorator** — wrap any function; its calls are
   automatically logged as tool calls into the active Howdex session.

2. **``Howdex.session()`` context manager** — a single context manager
   that starts a session, yields the Howdex instance, and ends the
   session with the right outcome (success on clean exit, failure on
   exception).

3. **``auto_instrument_langchain``** — monkey-patch a LangChain
   ``BaseTool`` (or any object with a ``run`` method) so every tool
   invocation is logged without changing the agent code.

Usage (decorator)::

    from howdex import Howdex
    from howdex.instrument import instrument, session_scope

    mem = Howdex(path="...", embedder="hashing")

    @instrument(mem)
    def search_code(query: str) -> str:
        return subprocess.run(["rg", query], capture_output=True, text=True).stdout

    with session_scope(mem, "fix_bug") as m:
        result = search_code("def load_config")
        # ... do work ...
        # session is automatically ended: success on clean exit,
        # failure on exception.

Usage (LangChain adapter)::

    from howdex.instrument import auto_instrument_langchain
    from langchain.tools import Tool

    tool = Tool(name="search", func=search_fn, description="...")
    auto_instrument_langchain(mem, [tool])
    # Now every tool.run() call is logged as a Howdex tool call.
"""

from __future__ import annotations

import functools
import inspect
import traceback
from contextlib import contextmanager
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from howdex import Howdex


def instrument(mem: "Howdex", name: str | None = None) -> Callable:
    """Decorator that logs function calls as Howdex tool calls.

    The wrapped function's name (or ``name``) is used as the tool name.
    The function's keyword arguments are logged as the tool arguments.
    The return value (stringified, truncated) is logged as the observation.
    If the function raises, the exception is logged as a failure observation
    and re-raised.

    The decorator requires an active Howdex session (started via
    ``mem.start_session()`` or the :func:`session_scope` context manager).
    If no session is active, the call is still executed but not logged
    (so the decorator is safe to use outside a session).

    Example::

        @instrument(mem)
        def search_code(query: str, glob: str = "*.py") -> str:
            ...

        @instrument(mem, name="run_tests")
        def pytest_runner(target: str) -> tuple[int, str]:
            ...
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Build arguments dict from the function signature
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)
            # Don't log 'self' for methods
            arguments.pop("self", None)
            try:
                result = func(*args, **kwargs)
                obs = _stringify_result(result)
                _safe_log_tool_call(mem, tool_name, arguments, obs)
                return result
            except Exception as exc:
                obs = f"Exception: {type(exc).__name__}: {exc}"
                _safe_log_tool_call(mem, tool_name, arguments, obs)
                raise
        return wrapper
    return decorator


@contextmanager
def session_scope(
    mem: "Howdex",
    task: str,
    *,
    agent_id: str | None = None,
    provenance: dict[str, Any] | None = None,
    require_receipt: bool = False,
):
    """Context manager that starts a session and ends it with the right outcome.

    On clean exit: ``end_session("success", require_receipt=require_receipt)``.
    On exception: ``end_session("failure", error=<traceback>)``.

    This eliminates the boilerplate of try/finally + end_session that
    LangChain migrants complain about.

    Guards against the double-end_session bug: if ``end_session("success")``
    itself raises (e.g. transient storage error), the exception handler
    checks whether a session is still active before calling
    ``end_session("failure")``, and swallows any error from that second
    call so the original exception propagates cleanly.

    Example::

        with session_scope(mem, "fix_bug") as m:
            result = search_code("def load_config")
            # ... do work ...
        # session automatically ended here
    """
    mem.start_session(task, agent_id=agent_id, provenance=provenance)
    try:
        yield mem
        mem.end_session("success", require_receipt=require_receipt)
    except Exception:
        # Only call end_session("failure") if the session is still active.
        # If end_session("success") already raised and closed the session,
        # calling end_session again would double-write or corrupt state.
        if mem._current_session is not None and not mem._current_session.finished_at:
            try:
                mem.end_session("failure", error=traceback.format_exc())
            except Exception:
                # Don't mask the original exception with a secondary failure.
                pass
        raise


def auto_instrument_langchain(
    mem: "Howdex",
    tools: list[Any],
) -> None:
    """Monkey-patch LangChain tools so every ``run()`` call is logged.

    This is the one-line integration for LangChain agents. After calling
    this, every ``tool.run(...)`` invocation will be logged as a Howdex
    tool call into the active session (you still need to start a session
    via ``mem.start_session()`` or :func:`session_scope`).

    Example::

        from langchain.tools import Tool
        from howdex.instrument import auto_instrument_langchain, session_scope

        tools = [Tool(name="search", func=search_fn, description="...")]
        auto_instrument_langchain(mem, tools)

        with session_scope(mem, "agent_task"):
            agent.run("fix the bug")
        # Every tool call inside the agent is now logged.
    """
    for tool in tools:
        original_run = tool.run
        tool_name = getattr(tool, "name", tool.__class__.__name__)

        @functools.wraps(original_run)
        def patched_run(*args, _original=original_run, _name=tool_name, **kwargs):
            try:
                result = _original(*args, **kwargs)
                obs = _stringify_result(result)
                _safe_log_tool_call(mem, _name, kwargs or {"args": str(args)[:200]}, obs)
                return result
            except Exception as exc:
                obs = f"Exception: {type(exc).__name__}: {exc}"
                _safe_log_tool_call(mem, _name, kwargs or {"args": str(args)[:200]}, obs)
                raise

        tool.run = patched_run


def _safe_log_tool_call(
    mem: "Howdex",
    name: str,
    arguments: dict[str, Any],
    observation: str,
) -> None:
    """Log a tool call, but don't crash if no session is active."""
    try:
        if mem._current_session and not mem._current_session.finished_at:
            mem.log_tool_call(name, arguments, observation)
    except Exception:
        # Never let logging crash the wrapped function
        pass


def _stringify_result(result: Any, max_len: int = 500) -> str:
    """Convert a result to a truncated string for logging."""
    if result is None:
        return "ok"
    s = str(result)
    if len(s) > max_len:
        s = s[:max_len] + "..."
    return s
