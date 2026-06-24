from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from howdex.adapters._shared import (
    adapter_guidance,
    constraints_from_mapping,
    environment_from_mapping,
    objective_from_mapping,
)


class HowdexLangChainAdapter:
    """Small LangChain adapter for Howdex.

    Usage:
        adapter = HowdexLangChainAdapter(memory)
        tools = adapter.tools()
    """

    def __init__(self, memory):
        self.memory = memory

    def inspect_howdex(self, query: str, top_k: int = 5) -> str:
        results = self.memory.search(query, top_k=top_k, min_score=0.0)

        if not results:
            return "Relevant Howdex memories: none"

        lines = ["Relevant Howdex memories:"]
        for r in results:
            content = r.memory.content.replace("\n", " ")
            lines.append(f"- score={r.score:.3f}: {content[:500]}")

        return "\n".join(lines)

    def remember_howdex(
        self,
        content: str,
        source: str = "agent",
        trust: str = "neutral",
        safety: str = "general",
    ) -> str:
        if hasattr(self.memory, "remember_trusted"):
            self.memory.remember_trusted(
                content,
                source=source,
                trust=trust,
                safety=safety,
            )
        else:
            self.memory.remember(content)

        return "remembered"

    def tools(self) -> list[Any]:
        try:
            from langchain_core.tools import tool
        except Exception as exc:
            raise ImportError(
                "LangChain adapter requires langchain-core. Install with: pip install langchain langchain-core"
            ) from exc

        adapter = self

        @tool
        def inspect_howdex(query: str) -> str:
            """Search Howdex memory for relevant prior experience."""
            return adapter.inspect_howdex(query)

        @tool
        def remember_howdex(content: str) -> str:
            """Store an important memory in Howdex."""
            return adapter.remember_howdex(content)

        return [inspect_howdex, remember_howdex]


def create_howdex_tools(memory) -> list[Any]:
    """Create LangChain tools for Howdex."""
    return HowdexLangChainAdapter(memory).tools()


class HowdexMemory:
    """LangChain-style memory/context provider backed by Howdex.

    This class deliberately avoids subclassing LangChain base classes so that
    importing it never requires LangChain to be installed. LangChain chains and
    agents can still use it because it implements the conventional
    ``load_memory_variables``, ``save_context``, and ``clear`` methods.
    """

    memory_variables = ["howdex_guidance"]

    def __init__(
        self,
        memory: Any,
        *,
        input_key: str = "input",
        output_key: str | None = None,
        memory_key: str = "howdex_guidance",
        max_chars: int = 6_000,
        verified_only: bool = False,
        include_source: bool = False,
        top_k: int = 3,
        min_confidence: float = 0.0,
        min_samples: int = 1,
    ):
        self.memory = memory
        self.input_key = input_key
        self.output_key = output_key
        self.memory_key = memory_key
        self.max_chars = int(max_chars)
        self.verified_only = bool(verified_only)
        self.include_source = bool(include_source)
        self.top_k = int(top_k)
        self.min_confidence = float(min_confidence)
        self.min_samples = int(min_samples)
        self._active_task: str | None = None

    def load_memory_variables(self, inputs: Mapping[str, Any] | None) -> dict[str, str]:
        """Return Howdex guidance under ``howdex_guidance`` by default."""
        objective = objective_from_mapping(
            inputs,
            preferred_key=self.input_key,
        )
        return {
            self.memory_key: adapter_guidance(
                self.memory,
                objective,
                constraints=constraints_from_mapping(inputs),
                environment=environment_from_mapping(inputs),
                max_chars=self.max_chars,
                verified_only=self.verified_only,
                include_source=self.include_source,
                top_k=self.top_k,
                min_confidence=self.min_confidence,
            )
        }

    def save_context(
        self,
        inputs: Mapping[str, Any] | None,
        outputs: Mapping[str, Any] | None,
    ) -> None:
        """Log one LangChain turn as a Howdex episodic step."""
        objective = objective_from_mapping(
            inputs,
            preferred_key=self.input_key,
        ) or self._active_task or "langchain task"
        if getattr(self.memory, "_current_session", None) is None:
            self.memory.start_session(
                objective,
                source="langchain",
                provenance={"adapter": "langchain"},
            )
            self._active_task = objective
        observation = self._observation(outputs)
        self.memory.log_step(
            "langchain_context",
            observation,
            outcome=self._status(outputs),
            metadata={"adapter": "langchain"},
        )

    def clear(self) -> None:
        """Close only the current adapter session; keep long-term memory."""
        if getattr(self.memory, "_current_session", None) is not None:
            self.memory.end_session("partial")
        self._active_task = None

    def _observation(self, outputs: Mapping[str, Any] | None) -> str:
        if not isinstance(outputs, Mapping):
            return "" if outputs is None else str(outputs)
        if self.output_key and outputs.get(self.output_key) is not None:
            return str(outputs[self.output_key])
        for key in ("output", "result", "answer", "observation", "content"):
            if outputs.get(key) is not None:
                return str(outputs[key])
        return str(dict(outputs))

    @staticmethod
    def _status(outputs: Mapping[str, Any] | None) -> str:
        if not isinstance(outputs, Mapping):
            return "success"
        value = str(outputs.get("status") or outputs.get("outcome") or "success")
        return value or "success"


__all__ = [
    "HowdexLangChainAdapter",
    "HowdexMemory",
    "create_howdex_tools",
]
