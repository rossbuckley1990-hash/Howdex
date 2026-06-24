"""Optional AutoGen adapter for native Howdex procedural memory."""

from __future__ import annotations

from typing import Any

from howdex.adapters._shared import adapter_guidance, learned_summary

DEFAULT_GUIDANCE_MAX_CHARS = 6_000


class HowdexAutoGenAdapter:
    """Small AutoGen conversation adapter that does not import AutoGen."""

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

    def system_message(
        self,
        objective: str,
        constraints: list[str] | None = None,
        environment: dict[str, Any] | str | None = None,
    ) -> str:
        """Return Howdex guidance for an AutoGen assistant/system prompt."""
        return adapter_guidance(
            self.memory,
            objective,
            constraints=constraints,
            environment=environment,
            max_chars=self.max_chars,
            verified_only=self.verified_only,
            include_source=self.include_source,
            top_k=self.top_k,
            min_confidence=self.min_confidence,
        )

    def start_conversation_task(
        self,
        objective: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Start a Howdex session for an AutoGen conversation task."""
        episode = self.memory.start_session(
            objective or "autogen conversation task",
            source="autogen",
            provenance={
                "adapter": "autogen",
                "metadata": dict(metadata or {}),
            },
        )
        return episode.session_id

    def record_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record one AutoGen conversation message as episodic evidence."""
        self.memory.log_step(
            f"autogen_message:{role or 'unknown'}",
            content,
            outcome="success",
            metadata={
                "adapter": "autogen",
                "role": role,
                **dict(metadata or {}),
            },
        )

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        observation: str,
        status: str = "success",
    ) -> None:
        """Log a structured tool call from an AutoGen agent."""
        self.memory.log_tool_call(
            tool_name,
            arguments=arguments or {},
            observation=observation,
            metadata={"adapter": "autogen"},
            outcome=status,
        )

    def end_conversation_task(
        self,
        outcome: str = "success",
        learn: bool = True,
    ) -> list[dict[str, Any]]:
        """End the AutoGen conversation task and optionally learn procedures."""
        self.memory.end_session(outcome=outcome)
        if not learn:
            return []
        return learned_summary(
            self.memory.learn(min_samples=self.min_samples)
        )


__all__ = ["HowdexAutoGenAdapter"]
