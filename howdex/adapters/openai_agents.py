from __future__ import annotations

from collections.abc import Callable
from typing import Any

from howdex.adapters._shared import adapter_guidance, learned_summary

DEFAULT_GUIDANCE_MAX_CHARS = 6_000


class HowdexOpenAIAgentsAdapter:
    """Optional OpenAI Agents SDK adapter for Howdex.

    The adapter is intentionally plain Python. Importing this module does not
    import ``openai`` or the Agents SDK; SDK-wrapped tools are created only when
    :meth:`tools` is called.
    """

    def __init__(
        self,
        memory: Any,
        *,
        max_chars: int = DEFAULT_GUIDANCE_MAX_CHARS,
        verified_only: bool = False,
        include_source: bool = False,
        top_k: int = 3,
        min_confidence: float = 0.0,
        min_samples: int = 1,
    ):
        self.memory = memory
        self.max_chars = int(max_chars)
        self.verified_only = bool(verified_only)
        self.include_source = bool(include_source)
        self.top_k = int(top_k)
        self.min_confidence = float(min_confidence)
        self.min_samples = int(min_samples)

    def instructions(
        self,
        objective: str,
        constraints: list[str] | None = None,
        environment: dict[str, Any] | str | None = None,
        max_chars: int = DEFAULT_GUIDANCE_MAX_CHARS,
    ) -> str:
        """Return agent-ready Howdex operational guidance Markdown."""
        return adapter_guidance(
            self.memory,
            objective,
            constraints=constraints,
            environment=environment,
            max_chars=self._resolve_max_chars(max_chars),
            verified_only=self.verified_only,
            include_source=self.include_source,
            top_k=self.top_k,
            min_confidence=self.min_confidence,
            adapter="openai_agents",
        )

    def start_task(
        self,
        objective: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Start a Howdex session for an OpenAI Agents task."""
        episode = self.memory.start_session(
            objective or "openai agents task",
            source="openai_agents",
            provenance={
                "adapter": "openai_agents",
                "metadata": dict(metadata or {}),
            },
        )
        return episode.session_id

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        observation: str,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a structured tool call into the active Howdex session."""
        self.memory.log_tool_call(
            tool_name,
            arguments=arguments or {},
            observation=observation,
            metadata={
                "adapter": "openai_agents",
                **dict(metadata or {}),
            },
            outcome=status,
        )

    def end_task(
        self,
        outcome: str = "success",
        error: str | None = None,
        learn: bool = True,
    ) -> list[dict[str, Any]]:
        """Close the active task session and optionally learn procedures."""
        self.memory.end_session(outcome=outcome, error=error)
        if not learn:
            return []
        return learned_summary(
            self.memory.learn(min_samples=self.min_samples)
        )

    def _resolve_max_chars(self, max_chars: int) -> int:
        """Use the configured default unless the caller overrides it."""
        if (
            int(max_chars) == DEFAULT_GUIDANCE_MAX_CHARS
            and self.max_chars != DEFAULT_GUIDANCE_MAX_CHARS
        ):
            return self.max_chars
        return int(max_chars)

    def inspect_howdex_text(self, query: str, top_k: int = 5) -> str:
        results = self.memory.search(query, top_k=top_k, min_score=0.0)

        if not results:
            return "Relevant Howdex memories: none"

        lines = ["Relevant Howdex memories:"]
        for r in results:
            content = r.memory.content.replace("\n", " ")
            lines.append(f"- score={r.score:.3f}: {content[:500]}")

        return "\n".join(lines)

    def remember_howdex_text(self, content: str) -> str:
        if hasattr(self.memory, "remember_trusted"):
            self.memory.remember_trusted(
                content,
                source="agent",
                trust="neutral",
                safety="general",
            )
        else:
            self.memory.remember(content)

        return "remembered"

    def as_tools(self) -> dict[str, Callable[..., Any]]:
        """Return plain Python callables usable as agent tools.

        These functions do not require the OpenAI Agents SDK. Frameworks that
        can wrap ordinary Python callables can use them directly.
        """
        adapter = self

        def howdex_guidance(
            objective: str,
            constraints: list[str] | None = None,
            environment: dict[str, Any] | str | None = None,
            max_chars: int = DEFAULT_GUIDANCE_MAX_CHARS,
        ) -> str:
            """Return Howdex operational guidance for an objective."""
            return adapter.instructions(
                objective,
                constraints=constraints,
                environment=environment,
                max_chars=max_chars,
            )

        def howdex_remember(content: str) -> str:
            """Store an important memory in Howdex."""
            return adapter.remember_howdex_text(content)

        def howdex_learn(min_samples: int | None = None) -> list[dict[str, Any]]:
            """Learn procedures from stored Howdex episodes."""
            return learned_summary(
                adapter.memory.learn(
                    min_samples=(
                        adapter.min_samples
                        if min_samples is None
                        else int(min_samples)
                    )
                )
            )

        def inspect_howdex(query: str) -> str:
            """Compatibility helper: search Howdex memory text."""
            return adapter.inspect_howdex_text(query)

        return {
            "howdex_guidance": howdex_guidance,
            "howdex_remember": howdex_remember,
            "howdex_learn": howdex_learn,
            "inspect_howdex": inspect_howdex,
        }

    def tools(self) -> list[Any]:
        """Return OpenAI Agents SDK function tools.

        The Agents SDK is optional and imported lazily here. Use
        :meth:`as_tools` when plain Python callables are enough.
        """
        try:
            from agents import function_tool
        except Exception as exc:
            raise ImportError(
                "OpenAI Agents adapter requires openai-agents. Install with: pip install openai-agents"
            ) from exc

        plain_tools = self.as_tools()

        @function_tool
        def howdex_guidance(
            objective: str,
            constraints: list[str] | None = None,
            max_chars: int = 6_000,
        ) -> str:
            """Return Howdex operational guidance for an agent objective."""
            return plain_tools["howdex_guidance"](
                objective,
                constraints=constraints,
                max_chars=max_chars,
            )

        @function_tool
        def remember_howdex(content: str) -> str:
            """Store an important memory in Howdex."""
            return plain_tools["howdex_remember"](content)

        @function_tool
        def howdex_learn(min_samples: int | None = None) -> list[dict[str, Any]]:
            """Learn procedures from stored Howdex episodes."""
            return plain_tools["howdex_learn"](min_samples)

        @function_tool
        def inspect_howdex(query: str) -> str:
            """Compatibility helper: search Howdex memory text."""
            return plain_tools["inspect_howdex"](query)

        return [
            howdex_guidance,
            remember_howdex,
            howdex_learn,
            inspect_howdex,
        ]


def create_howdex_tools(memory) -> list[Any]:
    """Create OpenAI Agents SDK function tools for Howdex."""
    return HowdexOpenAIAgentsAdapter(memory).tools()


__all__ = [
    "HowdexOpenAIAgentsAdapter",
    "create_howdex_tools",
]
