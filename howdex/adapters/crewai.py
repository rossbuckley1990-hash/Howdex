"""Optional CrewAI adapter for native Howdex procedural memory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from howdex.adapters._shared import adapter_guidance, learned_summary

DEFAULT_GUIDANCE_MAX_CHARS = 6_000


class HowdexCrewAIAdapter:
    """Small CrewAI lifecycle adapter that does not import CrewAI.

    CrewAI users can call these hooks from tasks, crews, callbacks, or custom
    memory flows. The adapter records deterministic Howdex episodes locally and
    renders source-free operational guidance by default.
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

    def before_kickoff(
        self,
        objective: str,
        constraints: list[str] | None = None,
        environment: dict[str, Any] | str | None = None,
    ) -> str:
        """Return guidance to include in Crew instructions before kickoff."""
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
            adapter="crewai",
        )

    def start_task(
        self,
        objective: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Start a Howdex session for a CrewAI task run."""
        episode = self.memory.start_session(
            objective or "crewai task",
            source="crewai",
            provenance={
                "adapter": "crewai",
                "metadata": dict(metadata or {}),
            },
        )
        return episode.session_id

    def record_step(
        self,
        agent_name: str,
        action: str,
        observation: str,
        status: str = "success",
    ) -> None:
        """Record one CrewAI agent action as an episodic step."""
        self.memory.log_step(
            action or "crewai_step",
            observation,
            outcome=status,
            metadata={
                "adapter": "crewai",
                "agent_name": agent_name,
            },
        )

    def after_kickoff(
        self,
        outcome: str = "success",
        learn: bool = True,
    ) -> list[dict[str, Any]]:
        """End the CrewAI task session and optionally learn procedures."""
        self.memory.end_session(outcome=outcome)
        if not learn:
            return []
        return learned_summary(
            self.memory.learn(min_samples=self.min_samples)
        )

    def memory_bridge(self) -> dict[str, Callable[..., Any]]:
        """Return simple methods CrewAI users can plug into memory flows."""
        return {
            "before_kickoff": self.before_kickoff,
            "start_task": self.start_task,
            "record_step": self.record_step,
            "after_kickoff": self.after_kickoff,
            "guidance": self.before_kickoff,
        }


__all__ = ["HowdexCrewAIAdapter"]
