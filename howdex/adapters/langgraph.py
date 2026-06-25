"""Optional LangGraph adapter for native Howdex procedural memory."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from howdex.adapters._shared import (
    adapter_guidance,
    constraints_from_mapping,
    environment_from_mapping,
    learned_summary,
    objective_from_mapping,
)


class HowdexLangGraphAdapter:
    """Small state-dict adapter for LangGraph-style workflows.

    The class intentionally does not import LangGraph. It works with the plain
    state dictionaries LangGraph nodes already pass around, so developers can
    drop it into a graph without adding Howdex-specific node plumbing.
    """

    def __init__(
        self,
        memory: Any,
        *,
        max_chars: int = 6_000,
        verified_only: bool = False,
        include_source: bool = False,
        top_k: int = 3,
        min_confidence: float = 0.0,
        min_samples: int = 1,
        guidance_key: str = "howdex_guidance",
        session_key: str = "howdex_session_id",
        learned_key: str = "howdex_learned_procedures",
    ):
        self.memory = memory
        self.max_chars = int(max_chars)
        self.verified_only = bool(verified_only)
        self.include_source = bool(include_source)
        self.top_k = int(top_k)
        self.min_confidence = float(min_confidence)
        self.min_samples = int(min_samples)
        self.guidance_key = guidance_key
        self.session_key = session_key
        self.learned_key = learned_key

    def before_node(
        self,
        state: Mapping[str, Any],
        objective_key: str = "objective",
    ) -> dict[str, Any]:
        """Return a copy of state with ``howdex_guidance`` added."""
        next_state = dict(state)
        objective = objective_from_mapping(next_state, preferred_key=objective_key)
        next_state[self.guidance_key] = adapter_guidance(
            self.memory,
            objective,
            constraints=constraints_from_mapping(next_state),
            environment=environment_from_mapping(next_state),
            max_chars=self.max_chars,
            verified_only=self.verified_only,
            include_source=self.include_source,
            top_k=self.top_k,
            min_confidence=self.min_confidence,
            adapter="langgraph",
        )
        return next_state

    def start_task(
        self,
        state: Mapping[str, Any],
        task_key: str = "objective",
    ) -> dict[str, Any]:
        """Start a Howdex session and store its id in returned state."""
        next_state = dict(state)
        task = objective_from_mapping(next_state, preferred_key=task_key)
        episode = self.memory.start_session(
            task or "langgraph task",
            source="langgraph",
            provenance={"adapter": "langgraph"},
        )
        next_state[self.session_key] = episode.session_id
        return next_state

    def after_tool_call(
        self,
        state: Mapping[str, Any],
        tool_name: str,
        arguments: dict[str, Any] | None,
        observation: str,
        status: str = "success",
    ) -> dict[str, Any]:
        """Log a structured tool-call step into the active Howdex session."""
        self.memory.log_tool_call(
            tool_name,
            arguments=arguments or {},
            observation=observation,
            metadata={"adapter": "langgraph"},
            outcome=status,
        )
        next_state = dict(state)
        next_state["howdex_last_tool"] = tool_name
        next_state["howdex_last_status"] = status
        next_state["howdex_logged_steps"] = int(
            next_state.get("howdex_logged_steps", 0)
        ) + 1
        return next_state

    def end_task(
        self,
        state: Mapping[str, Any],
        outcome: str = "success",
        error: str | None = None,
    ) -> dict[str, Any]:
        """End the active session, learn, and attach learned summaries."""
        episode = self.memory.end_session(outcome=outcome, error=error)
        procedures = self.memory.learn(min_samples=self.min_samples)
        next_state = dict(state)
        next_state["howdex_episode_id"] = episode.session_id
        next_state[self.learned_key] = learned_summary(procedures)
        return next_state

    def middleware(self, node: Callable[..., Any] | None = None):
        """Return a callable wrapper for LangGraph node functions.

        Usage:
            graph.add_node("worker", adapter.middleware(worker_node))
        """

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            def wrapped(state: Mapping[str, Any], *args: Any, **kwargs: Any):
                prepared = self.before_node(state)
                return fn(prepared, *args, **kwargs)

            return wrapped

        if node is None:
            return decorate
        return decorate(node)


__all__ = ["HowdexLangGraphAdapter"]
