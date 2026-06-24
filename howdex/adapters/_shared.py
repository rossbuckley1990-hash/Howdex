"""Shared helpers for optional framework adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from howdex.core.guidance import render_agent_guidance


def objective_from_mapping(
    values: Mapping[str, Any] | None,
    *,
    preferred_key: str = "objective",
) -> str:
    """Return the most useful objective text from framework state/input."""
    if not isinstance(values, Mapping):
        return ""
    for key in (
        preferred_key,
        "objective",
        "task",
        "input",
        "query",
        "question",
        "messages",
    ):
        value = values.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            text = " ".join(str(item) for item in value if item is not None)
        else:
            text = str(value)
        text = " ".join(text.split())
        if text:
            return text
    return ""


def adapter_guidance(
    memory: Any,
    objective: str,
    *,
    constraints: Any = None,
    environment: Any = None,
    max_chars: int = 6_000,
    verified_only: bool = False,
    include_source: bool = False,
    top_k: int = 3,
    min_confidence: float = 0.0,
) -> str:
    """Render deterministic Howdex guidance for framework adapters."""
    objective_text = " ".join(str(objective or "").split())
    if not objective_text:
        objective_text = "current agent task"
    suggestions = memory.suggest_procedure(
        objective_text,
        top_k=top_k,
        min_confidence=min_confidence,
    )
    if verified_only:
        suggestions = [
            suggestion
            for suggestion in suggestions
            if getattr(suggestion, "procedure_verified", False)
            or getattr(suggestion, "verification_status", "") == "verified"
            or getattr(suggestion, "procedure_status", "") == "verified"
        ]
    return render_agent_guidance(
        suggestions,
        objective=objective_text,
        constraints=constraints,
        target_environment=environment if isinstance(environment, str) else None,
        current_environment=environment,
        include_source=include_source,
        include_failed_attempts=True,
        include_verification=True,
        max_chars=max_chars,
    )


def learned_summary(procedures: list[Any]) -> list[dict[str, Any]]:
    """Return a stable adapter-safe summary of learned procedures."""
    return [
        {
            "procedure_id": str(getattr(procedure, "id", "")),
            "task_signature": str(getattr(procedure, "task_signature", "")),
            "support_count": int(getattr(procedure, "support_count", 0)),
            "confidence": float(getattr(procedure, "confidence", 0.0)),
        }
        for procedure in procedures
    ]


def constraints_from_mapping(values: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(values, Mapping):
        return []
    constraints = values.get("constraints")
    if constraints is None:
        return []
    if isinstance(constraints, str):
        return [constraints]
    if isinstance(constraints, (list, tuple, set)):
        return [str(item) for item in constraints if str(item).strip()]
    return [str(constraints)]


def environment_from_mapping(values: Mapping[str, Any] | None) -> Any:
    if not isinstance(values, Mapping):
        return None
    return (
        values.get("environment")
        or values.get("target_environment")
        or values.get("runtime_environment")
    )
