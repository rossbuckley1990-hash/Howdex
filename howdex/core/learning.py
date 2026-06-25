"""Canonical structured-step normalization for procedure learning."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from howdex.core.actions import CanonicalAction, canonicalize_action
from howdex.core.parallel import resolve_parallel_spans
from howdex.core.parameterize import (
    ParameterizedStep,
    parameterize_steps_for_learning,
)
from howdex.core.tool_calls import (
    normalize_tool_name,
    tool_call_from_step,
)

_COMMAND_KEYS = ("cmd", "command", "shell_command", "script")
_COMMAND_TOOL_TOKENS = {
    "bash",
    "command",
    "exec",
    "execute",
    "shell",
    "subprocess",
    "terminal",
}
_NON_ARGUMENT_KEYS = {
    "action",
    "canonical_action",
    "canonical_confidence",
    "canonical_evidence",
    "content",
    "duration_s",
    "end_time",
    "ended_at",
    "error",
    "error_ingestion",
    "finished_at",
    "function",
    "id",
    "input",
    "intent",
    "metadata",
    "name",
    "observation",
    "observation_ingestion",
    "ordering_index",
    "outcome",
    "output",
    "parallel_group_id",
    "parent_step_ids",
    "provenance",
    "result",
    "side_effect_class",
    "span_id",
    "start_time",
    "started_at",
    "step_id",
    "target",
    "task",
    "task_boundary",
    "task_signature",
    "tool",
    "tool_args",
    "tool_call",
    "tool_input",
    "tool_metadata",
    "tool_name",
    "ts",
    "type",
}


@dataclass(frozen=True)
class NormalizedLearningStep:
    """One deterministic step object used by consolidation."""

    raw_step: dict[str, Any]
    tool_name: str | None
    tool_args: dict[str, Any]
    canonical: CanonicalAction
    parameterized: ParameterizedStep
    outcome: str | None
    canonical_payload: dict[str, Any]
    identity: str


def canonical_json(value: Any) -> str:
    """Serialize recursively normalized JSON with one stable representation."""
    return json.dumps(
        normalize_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def normalize_json_value(value: Any) -> Any:
    """Recursively normalize JSON-compatible values and safe JSON strings."""
    if isinstance(value, Mapping):
        return {
            str(key): normalize_json_value(value[key])
            for key in sorted(value, key=lambda candidate: str(candidate))
        }
    if isinstance(value, (list, tuple)):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return value
            return normalize_json_value(decoded)
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def normalize_step_for_learning(step: Any) -> NormalizedLearningStep:
    """Normalize one structured or legacy step for deterministic comparison."""
    return normalize_steps_for_learning([step])[0]


def normalize_steps_for_learning(
    steps: list[Any],
    *,
    episode_id: str | None = None,
) -> list[NormalizedLearningStep]:
    """Normalize, resolve DAG metadata, canonicalize, then parameterize steps."""
    prepared = [_prepare_raw_step(step) for step in steps]
    resolved = resolve_parallel_spans(prepared, episode_id=episode_id)
    canonical_actions = [_canonicalize_learning_step(step) for step in resolved]
    parameterized_actions = parameterize_steps_for_learning(
        canonical_actions
    )
    return [
        _normalized_learning_step(step, canonical, parameterized)
        for step, canonical, parameterized in zip(
            resolved,
            canonical_actions,
            parameterized_actions, strict=False,
        )
    ]


def _prepare_raw_step(step: Any) -> dict[str, Any]:
    normalized = normalize_json_value(step)
    if isinstance(normalized, Mapping):
        output = dict(normalized)
    else:
        output = {"action": str(normalized)}

    tool_name, arguments = _structured_tool_fields(output)
    if tool_name:
        output["tool_name"] = tool_name
        output["tool_args"] = arguments
    return normalize_json_value(output)


def _structured_tool_fields(
    step: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    function = step.get("function")
    if isinstance(function, Mapping) and function.get("name"):
        return (
            str(function["name"]),
            _mapping_value(function.get("arguments")) or {},
        )

    tool_call = step.get("tool_call")
    if isinstance(tool_call, Mapping):
        name = tool_call.get("name") or tool_call.get("tool_name")
        if name:
            arguments = (
                tool_call.get("arguments")
                or tool_call.get("args")
                or tool_call.get("input")
            )
            return str(name), _mapping_value(arguments) or {}

    name = step.get("tool_name") or step.get("tool")
    explicit_arguments = (
        step.get("arguments")
        if "arguments" in step
        else step.get(
            "tool_args",
            step.get("tool_input", step.get("args", step.get("input"))),
        )
    )
    arguments = _mapping_value(explicit_arguments)
    if name and arguments is not None:
        return str(name), arguments
    if name:
        inferred = {
            str(key): normalize_json_value(value)
            for key, value in step.items()
            if str(key) not in _NON_ARGUMENT_KEYS
        }
        return str(name), inferred

    if step.get("name") and explicit_arguments is not None:
        return str(step["name"]), _mapping_value(explicit_arguments) or {}
    return None, {}


def _canonicalize_learning_step(
    step: dict[str, Any],
) -> CanonicalAction:
    stored = tool_call_from_step(step)
    tool_name = str(step.get("tool_name") or "")
    arguments = _mapping_value(step.get("tool_args")) or {}
    command = _command_value(arguments)
    stored_canonical = normalize_tool_name(
        str(step.get("canonical_action") or "")
    )
    normalized_tool = normalize_tool_name(tool_name)
    if (
        tool_name
        and command is not None
        and _is_command_tool(tool_name)
        and (
            not stored_canonical
            or stored_canonical == normalized_tool
        )
    ):
        legacy = canonicalize_action(
            command,
            _observation_value(step),
        )
        # If the prose canonicalizer didn't recognize the command (returned
        # unknown_action), fall back to the stored canonical from
        # tool_call_from_step. This prevents arbitrary commands like
        # "python -c 'import broken_pkg'" from being classified as
        # unknown_action when log_tool_call already produced a valid
        # canonical like "run_bash" or "execute_file".
        if legacy.canonical_name == "unknown_action" and stored is not None:
            return stored
        evidence = dict(legacy.evidence)
        evidence.update(
            {
                "structured_tool_name": normalize_tool_name(tool_name),
                "canonical_arguments": canonical_json(arguments),
            }
        )
        return CanonicalAction(
            raw_action=command,
            canonical_name=legacy.canonical_name,
            intent=legacy.intent,
            target=legacy.target,
            confidence=legacy.confidence,
            evidence=evidence,
            raw_name=tool_name,
            raw_args=arguments,
            provenance={"source": "structured_command"},
            matched_by="structured_command",
            side_effect_class=legacy.side_effect_class,
        )
    if stored is not None:
        return stored
    return canonicalize_action(
        str(step.get("action") or ""),
        _observation_value(step),
    )


def _normalized_learning_step(
    raw_step: dict[str, Any],
    canonical: CanonicalAction,
    parameterized: ParameterizedStep,
) -> NormalizedLearningStep:
    tool_name = (
        normalize_tool_name(str(canonical.raw_name))
        if canonical.matched_by != "legacy_prose" and canonical.raw_name
        else None
    )
    outcome = _normalize_outcome(raw_step.get("outcome"))
    canonical_payload = normalize_json_value(
        json.loads(parameterized.learning_key)
    )
    return NormalizedLearningStep(
        raw_step=normalize_json_value(raw_step),
        tool_name=tool_name,
        tool_args=normalize_json_value(canonical.raw_args),
        canonical=canonical,
        parameterized=parameterized,
        outcome=outcome,
        canonical_payload=canonical_payload,
        identity=parameterized.learning_key,
    )


def _mapping_value(value: Any) -> dict[str, Any] | None:
    normalized = normalize_json_value(value)
    return dict(normalized) if isinstance(normalized, Mapping) else None


def _command_value(arguments: Mapping[str, Any]) -> str | None:
    for key in _COMMAND_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _is_command_tool(tool_name: str) -> bool:
    normalized = normalize_tool_name(tool_name)
    tokens = {
        token
        for segment in normalized.split(".")
        for token in segment.split("_")
        if token
    }
    return bool(tokens & _COMMAND_TOOL_TOKENS)


def _observation_value(step: Mapping[str, Any]) -> str | None:
    value = (
        step.get("observation")
        or step.get("output")
        or step.get("result")
        or step.get("content")
    )
    return None if value is None else str(value)


def _normalize_outcome(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return " ".join(str(value).lower().split())
