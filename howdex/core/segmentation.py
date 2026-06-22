"""Deterministic segmentation for long structured agent sessions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from howdex.core.types import Episode

DEFAULT_MAX_SEGMENT_STEPS = 50
DEFAULT_IDLE_GAP_S = 900.0


def segment_episode(
    episode: Episode,
    *,
    max_steps: int = DEFAULT_MAX_SEGMENT_STEPS,
    idle_gap_s: float = DEFAULT_IDLE_GAP_S,
) -> list[Episode]:
    """Return child episodes when deterministic boundaries split a session."""
    if not episode.steps:
        return []

    max_steps = max(1, int(max_steps))
    idle_gap_s = max(0.0, float(idle_gap_s))
    groups: list[tuple[list[dict[str, Any]], str, str, int]] = []
    current: list[dict[str, Any]] = []
    current_task = episode.task
    current_reason = "session_start"
    current_start_index = 0

    for index, step in enumerate(episode.steps):
        boundary_task = _explicit_boundary_task(step, episode.task)
        reason: str | None = None
        if current and boundary_task is not None:
            reason = "explicit_task_boundary"
        elif current and _idle_gap(current[-1], step) > idle_gap_s:
            reason = "idle_gap"
        elif len(current) >= 2 and _major_target_change(current[-1], step):
            reason = "major_target_change"
        elif current and len(current) >= max_steps:
            reason = "max_step_count"

        if reason is not None:
            groups.append(
                (
                    current,
                    current_task,
                    current_reason,
                    current_start_index,
                )
            )
            current = []
            current_start_index = index
            current_reason = reason
            if boundary_task is not None:
                current_task = boundary_task
        elif boundary_task is not None:
            current_task = boundary_task

        current.append(dict(step))

    groups.append(
        (current, current_task, current_reason, current_start_index)
    )
    if len(groups) <= 1:
        return []

    children: list[Episode] = []
    for child_index, (steps, task, reason, start_index) in enumerate(
        groups,
        start=1,
    ):
        started_at = _step_start(steps[0], episode.started_at)
        finished_at = _step_end(
            steps[-1],
            episode.finished_at or started_at,
        )
        child_error = _segment_error(steps)
        if child_error is None and child_index == len(groups):
            child_error = episode.error
        child_outcome = _segment_outcome(
            steps,
            episode.outcome,
            is_last=child_index == len(groups),
        )
        provenance = dict(episode.provenance)
        provenance.update(
            {
                "segmentation_rule": reason,
                "segment_index": child_index,
                "step_start_index": start_index,
                "step_end_index": start_index + len(steps) - 1,
            }
        )
        children.append(
            replace(
                episode,
                session_id=f"{episode.session_id}:segment:{child_index:03d}",
                task=task,
                steps=steps,
                outcome=child_outcome,
                error=child_error,
                duration_s=max(0.0, finished_at - started_at),
                started_at=started_at,
                finished_at=finished_at,
                parent_session_id=episode.session_id,
                source=episode.source,
                provenance=provenance,
                is_segment=True,
            )
        )
    return children


def _explicit_boundary_task(
    step: dict[str, Any],
    default_task: str,
) -> str | None:
    boundary = step.get("task_boundary")
    if not boundary:
        return None
    if isinstance(boundary, str):
        value = " ".join(boundary.split())
        return value or default_task
    value = step.get("task_signature") or step.get("task")
    return " ".join(str(value or default_task).split())


def _major_target_change(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    previous_target = _target_identity(previous)
    current_target = _target_identity(current)
    if previous_target is None or current_target is None:
        return False
    if previous_target == current_target:
        return False
    previous_namespace = _tool_namespace(previous)
    current_namespace = _tool_namespace(current)
    previous_key = previous_target.split("=", 1)[0]
    current_key = current_target.split("=", 1)[0]
    return (
        previous_key != current_key
        or (
            previous_namespace is not None
            and current_namespace is not None
            and previous_namespace != current_namespace
        )
    )


def _target_identity(step: dict[str, Any]) -> str | None:
    target = step.get("target")
    if target is None:
        return None
    normalized = " ".join(str(target).lower().split())
    return normalized or None


def _tool_namespace(step: dict[str, Any]) -> str | None:
    name = step.get("canonical_action") or step.get("tool_name")
    if not name:
        return None
    normalized = str(name).lower()
    return normalized.split(".", 1)[0]


def _idle_gap(previous: dict[str, Any], current: dict[str, Any]) -> float:
    previous_end = _step_end(previous, _step_start(previous, 0.0))
    current_start = _step_start(current, previous_end)
    return max(0.0, current_start - previous_end)


def _step_start(step: dict[str, Any], fallback: float) -> float:
    value = step.get("started_at", step.get("start_time", step.get("ts")))
    return _float_or(value, fallback)


def _step_end(step: dict[str, Any], fallback: float) -> float:
    value = step.get(
        "ended_at",
        step.get("end_time", step.get("finished_at")),
    )
    if value is not None:
        return _float_or(value, fallback)
    start = _step_start(step, fallback)
    duration = _float_or(step.get("duration_s"), 0.0)
    return start + max(0.0, duration)


def _segment_error(steps: list[dict[str, Any]]) -> str | None:
    for step in steps:
        error = step.get("error")
        if error:
            return str(error)
    return None


def _segment_outcome(
    steps: list[dict[str, Any]],
    parent_outcome: str | None,
    *,
    is_last: bool,
) -> str | None:
    outcomes = [
        str(step.get("outcome")).lower()
        for step in steps
        if step.get("outcome")
    ]
    if any(outcome in {"failure", "failed", "error"} for outcome in outcomes):
        return "failure"
    if outcomes and all(outcome in {"success", "succeeded", "ok"} for outcome in outcomes):
        return "success"
    if parent_outcome == "failure" and not is_last:
        return "partial"
    return parent_outcome


def _float_or(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)
