"""Deterministic resolution and rendering of parallel episode spans."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Parallel_Span_Resolver:
    """Resolve flat step records into additive DAG metadata."""

    def resolve(
        self,
        steps: list[Any],
        *,
        episode_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized = [
            _normalize_step(step, index, episode_id)
            for index, step in enumerate(steps)
        ]
        if not normalized:
            return []

        normalized.sort(
            key=lambda step: (
                step["ordering_index"],
                step["step_id"],
            )
        )
        explicit_parenting = any(
            step["parent_step_ids"] for step in normalized
        )
        _assign_overlapping_groups(normalized)
        nodes = _ordered_nodes(normalized)

        for ordering_index, node in enumerate(nodes):
            for step in node:
                step["ordering_index"] = ordering_index

        if not explicit_parenting:
            previous_ids: list[str] = []
            for node in nodes:
                for step in node:
                    step["parent_step_ids"] = list(previous_ids)
                previous_ids = sorted(
                    str(step["step_id"]) for step in node
                )

        return [
            step
            for node in nodes
            for step in sorted(node, key=_member_sort_key)
        ]


ParallelSpanResolver = Parallel_Span_Resolver


def resolve_parallel_spans(
    steps: list[Any],
    *,
    episode_id: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve steps with the default deterministic span resolver."""
    return Parallel_Span_Resolver().resolve(
        steps,
        episode_id=episode_id,
    )


def render_dag_steps(
    steps: list[Any],
    *,
    action_key: str = "action",
) -> list[str]:
    """Render sequential and parallel nodes without ordering group members."""
    normalized = [
        (
            dict(step)
            if isinstance(step, Mapping)
            else {
                "action": str(step),
                "ordering_index": index,
                "step_id": f"render-step-{index + 1:04d}",
            }
        )
        for index, step in enumerate(steps)
    ]
    nodes = _ordered_nodes(normalized)
    rendered: list[str] = []
    for index, node in enumerate(nodes, start=1):
        members = sorted(node, key=_member_sort_key)
        if len(members) == 1:
            rendered.append(
                f"Step {index}: {_action_text(members[0], action_key)}"
            )
            continue
        for member_index, member in enumerate(members):
            suffix = _alpha_suffix(member_index)
            rendered.append(
                f"Step {index}{suffix} (parallel): "
                f"{_action_text(member, action_key)}"
            )
    return rendered


def _normalize_step(
    step: Any,
    index: int,
    episode_id: str | None,
) -> dict[str, Any]:
    if isinstance(step, Mapping):
        normalized = dict(step)
    else:
        normalized = {"action": str(step)}

    prefix = str(episode_id or "episode")
    step_id = str(
        normalized.get("step_id")
        or f"{prefix}:step:{index + 1:04d}"
    )
    parents = normalized.get("parent_step_ids", [])
    if isinstance(parents, str):
        parent_step_ids = [parents]
    elif isinstance(parents, (list, tuple, set)):
        parent_step_ids = sorted(
            {
                str(parent)
                for parent in parents
                if parent not in (None, "")
            }
        )
    else:
        parent_step_ids = []

    started_at = _optional_float(
        normalized.get(
            "started_at",
            normalized.get("start_time", normalized.get("ts")),
        )
    )
    ended_at = _optional_float(
        normalized.get(
            "ended_at",
            normalized.get("end_time", normalized.get("finished_at")),
        )
    )
    duration = _optional_float(normalized.get("duration_s"))
    if ended_at is None and started_at is not None and duration is not None:
        ended_at = started_at + max(0.0, duration)

    ordering = normalized.get("ordering_index", index)
    try:
        ordering_index = int(ordering)
    except (TypeError, ValueError):
        ordering_index = index

    normalized.update(
        {
            "step_id": step_id,
            "parent_step_ids": parent_step_ids,
            "span_id": (
                str(normalized["span_id"])
                if normalized.get("span_id") not in (None, "")
                else None
            ),
            "parallel_group_id": (
                str(normalized["parallel_group_id"])
                if normalized.get("parallel_group_id") not in (None, "")
                else None
            ),
            "started_at": started_at,
            "ended_at": ended_at,
            "ordering_index": ordering_index,
        }
    )
    normalized.setdefault("start_time", started_at)
    normalized.setdefault("end_time", ended_at)
    return normalized


def _assign_overlapping_groups(steps: list[dict[str, Any]]) -> None:
    ungrouped = [
        step
        for step in steps
        if not step.get("parallel_group_id")
        and _has_interval(step)
    ]
    adjacency: dict[str, set[str]] = defaultdict(set)
    by_id = {str(step["step_id"]): step for step in ungrouped}
    for left_index, left in enumerate(ungrouped):
        for right in ungrouped[left_index + 1 :]:
            if _explicit_dependency(left, right):
                continue
            if _overlaps(left, right):
                left_id = str(left["step_id"])
                right_id = str(right["step_id"])
                adjacency[left_id].add(right_id)
                adjacency[right_id].add(left_id)

    used_ids = {
        str(step["parallel_group_id"])
        for step in steps
        if step.get("parallel_group_id")
    }
    visited: set[str] = set()
    for step_id in sorted(
        adjacency,
        key=lambda item: (
            by_id[item]["ordering_index"],
            item,
        ),
    ):
        if step_id in visited:
            continue
        pending = [step_id]
        component: list[str] = []
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            pending.extend(sorted(adjacency[current] - visited))
        if len(component) < 2:
            continue
        minimum_order = min(
            int(by_id[item]["ordering_index"])
            for item in component
        )
        base = f"parallel-{minimum_order + 1:04d}"
        group_id = base
        suffix = 2
        while group_id in used_ids:
            group_id = f"{base}-{suffix}"
            suffix += 1
        used_ids.add(group_id)
        for item in component:
            by_id[item]["parallel_group_id"] = group_id


def _ordered_nodes(
    steps: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    singles: list[list[dict[str, Any]]] = []
    for step in steps:
        group_id = step.get("parallel_group_id")
        if group_id:
            groups[str(group_id)].append(step)
        else:
            singles.append([step])
    nodes = [*singles, *groups.values()]
    nodes.sort(
        key=lambda node: (
            min(int(step.get("ordering_index", 0)) for step in node),
            min(str(step.get("step_id", "")) for step in node),
        )
    )
    return nodes


def _has_interval(step: dict[str, Any]) -> bool:
    started_at = step.get("started_at")
    ended_at = step.get("ended_at")
    return (
        isinstance(started_at, (int, float))
        and not isinstance(started_at, bool)
        and isinstance(ended_at, (int, float))
        and not isinstance(ended_at, bool)
        and float(ended_at) > float(started_at)
    )


def _overlaps(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    return (
        float(left["started_at"]) < float(right["ended_at"])
        and float(right["started_at"]) < float(left["ended_at"])
    )


def _explicit_dependency(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    left_id = str(left["step_id"])
    right_id = str(right["step_id"])
    return (
        left_id in right.get("parent_step_ids", [])
        or right_id in left.get("parent_step_ids", [])
    )


def _member_sort_key(step: dict[str, Any]) -> tuple[str, str]:
    action = str(
        step.get("canonical_action")
        or step.get("canonical_name")
        or step.get("action")
        or ""
    )
    return action, str(step.get("step_id", ""))


def _action_text(step: dict[str, Any], action_key: str) -> str:
    return str(
        step.get(action_key)
        or step.get("parameterized_action")
        or step.get("canonical_name")
        or step.get("canonical_action")
        or step.get("action")
        or "unknown_action"
    )


def _alpha_suffix(index: int) -> str:
    value = index
    output = ""
    while True:
        value, remainder = divmod(value, 26)
        output = chr(ord("a") + remainder) + output
        if value == 0:
            return output
        value -= 1


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
