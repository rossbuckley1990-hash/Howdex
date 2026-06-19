"""Consolidation: turn episodic memories into procedural knowledge.

Howdex may remember cognitive/internal tools, but it must only learn executable
task actions as procedures.

Example:
- remember episodically: inspect_howdex
- learn procedurally: check_DATABASE_URL, run_tests, deploy_service
"""

from __future__ import annotations

import json

from collections import defaultdict
from typing import Any

from howdex.core.types import Procedure
from howdex.storage import Store


IGNORED_PROCEDURAL_ACTIONS = {
    "",
    "unknown",
    "inspect_howdex",
    "recall",
    "howdex_search",
    "howdex_remember",
    "howdex_learn",
    "memory_lookup",
    "lookup_memory",
    "search_memory",
    "retrieve_memory",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read from either dict-like or object-like values."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_task(task: str) -> str:
    """Canonicalize a task description for clustering."""
    return " ".join((task or "").lower().split())[:200]


def _step_action(step: Any) -> str | None:
    """Extract an action/tool name from different episode step shapes."""
    if isinstance(step, dict):
        return (
            step.get("action")
            or step.get("name")
            or step.get("tool")
            or step.get("tool_name")
        )

    if isinstance(step, str):
        return step

    return (
        getattr(step, "action", None)
        or getattr(step, "name", None)
        or getattr(step, "tool", None)
        or getattr(step, "tool_name", None)
    )


def _step_observation(step: Any) -> Any:
    if isinstance(step, dict):
        return (
            step.get("observation")
            or step.get("output")
            or step.get("result")
            or step.get("content")
        )

    return (
        getattr(step, "observation", None)
        or getattr(step, "output", None)
        or getattr(step, "result", None)
        or getattr(step, "content", None)
    )


def is_procedural_action(action: str | None) -> bool:
    """Return True only for real executable task actions."""
    if not action:
        return False

    normalized = str(action).strip().lower()

    if normalized in IGNORED_PROCEDURAL_ACTIONS:
        return False

    if normalized.startswith("inspect_"):
        return False

    if "recall" in normalized:
        return False

    if "memory" in normalized and any(
        word in normalized for word in ["inspect", "lookup", "search", "retrieve"]
    ):
        return False

    return True


def _canonical_step(step: Any) -> dict[str, Any]:
    """Return a normalised procedure step with an action key."""
    action = _step_action(step)
    observation = _step_observation(step)

    if isinstance(step, dict):
        copied = dict(step)
        copied["action"] = action
        if observation is not None:
            copied["observation"] = observation
        return copied

    return {"action": action, "observation": observation or ""}



def _normalise_steps(steps: Any) -> list[Any]:
    """Normalise episode steps loaded from storage.

    Storage may return steps as:
    - list[dict]
    - list[str]
    - JSON string representing a list

    Consolidation must never iterate over a raw JSON string character by character.
    """
    if steps is None:
        return []

    if isinstance(steps, str):
        try:
            parsed = json.loads(steps)
        except json.JSONDecodeError:
            return []

        if isinstance(parsed, list):
            return parsed

        return []

    if isinstance(steps, list):
        return steps

    return []


def _filter_procedural_steps(steps: list[Any]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []

    for step in _normalise_steps(steps):
        action = _step_action(step)

        if is_procedural_action(action):
            filtered.append(_canonical_step(step))

    return filtered


def _is_subsequence(short: list[str], long: list[str]) -> bool:
    if not short:
        return True

    j = 0

    for item in long:
        if item == short[j]:
            j += 1
            if j == len(short):
                return True

    return False


def _extract_common_prefix(steps_lists: list[list[Any]]) -> list[dict[str, Any]]:
    """Find the longest executable action sequence common to most successes."""
    if not steps_lists:
        return []

    filtered_lists = [_filter_procedural_steps(steps) for steps in steps_lists]
    filtered_lists = [steps for steps in filtered_lists if steps]

    if not filtered_lists:
        return []

    ref = min(filtered_lists, key=len)
    best: list[dict[str, Any]] = []

    # Require majority support, but never less than 2 where possible.
    if len(filtered_lists) == 1:
        required_support = 1
    else:
        required_support = max(2, (len(filtered_lists) + 1) // 2)

    for size in range(len(ref), 0, -1):
        for start in range(0, len(ref) - size + 1):
            candidate_steps = ref[start : start + size]
            candidate_actions = [s["action"] for s in candidate_steps]

            support = 0

            for steps in filtered_lists:
                actions = [s["action"] for s in steps]
                if _is_subsequence(candidate_actions, actions):
                    support += 1

            if support >= required_support:
                best = candidate_steps
                break

        if best:
            break

    return best


def _extract_preconditions(success_steps: list[Any], fail_steps: list[Any]) -> list[str]:
    """Things present in successes but absent in failures → preconditions."""
    success_actions = {
        s["action"]
        for s in _filter_procedural_steps(success_steps)
        if isinstance(s, dict) and s.get("action")
    }

    fail_actions = {
        s["action"]
        for s in _filter_procedural_steps(fail_steps)
        if isinstance(s, dict) and s.get("action")
    }

    diff = success_actions - fail_actions
    return sorted(diff)



def _procedure_to_store_dict(proc: Procedure) -> dict[str, Any]:
    """Convert a Procedure object into the dict shape expected by Store."""
    if isinstance(proc, dict):
        return proc

    if hasattr(proc, "model_dump"):
        return proc.model_dump()

    if hasattr(proc, "__dict__"):
        return dict(proc.__dict__)

    raise TypeError(f"Unsupported procedure type: {type(proc)!r}")


def _write_procedure(store: Store, proc: Procedure) -> None:
    """Write procedure using whichever store method exists."""
    payload = _procedure_to_store_dict(proc)

    if hasattr(store, "upsert_procedure"):
        store.upsert_procedure(payload)
    elif hasattr(store, "save_procedure"):
        store.save_procedure(payload)
    elif hasattr(store, "put_procedure"):
        store.put_procedure(payload)
    elif hasattr(store, "store_procedure"):
        store.store_procedure(payload)
    elif hasattr(store, "add_procedure"):
        store.add_procedure(payload)
    else:
        raise AttributeError(
            "Store has no recognised procedure write method. "
            "Expected one of: upsert_procedure, save_procedure, "
            "put_procedure, store_procedure, add_procedure."
        )


def consolidate(store: Store, *, min_samples: int = 3, dry_run: bool = False) -> list[Procedure]:
    """Run consolidation. Returns the procedures that were created or updated."""
    episodes = store.query_episodes(limit=10_000)

    by_task: dict[str, list[Any]] = defaultdict(list)

    for episode in episodes:
        task = _normalize_task(_get(episode, "task", "") or "")
        if task:
            by_task[task].append(episode)

    procedures: list[Procedure] = []

    for task, task_episodes in by_task.items():
        if len(task_episodes) < min_samples:
            continue

        successes = [
            e for e in task_episodes
            if _get(e, "outcome") == "success"
        ]
        failures = [
            e for e in task_episodes
            if _get(e, "outcome") == "failure"
        ]

        if not successes:
            continue

        success_steps_lists = [_get(e, "steps", []) or [] for e in successes]

        fail_steps: list[Any] = []
        for e in failures:
            fail_steps.extend(_get(e, "steps", []) or [])

        common_steps = _extract_common_prefix(success_steps_lists)

        if not common_steps:
            continue

        success_flat: list[Any] = []
        for steps in success_steps_lists:
            success_flat.extend(steps)

        preconditions = _extract_preconditions(success_flat, fail_steps)

        success_rate = len(successes) / len(task_episodes)

        existing = store.get_procedure(task)

        if existing:
            existing_payload = dict(existing)

            proc = Procedure(
                task_signature=existing_payload.get("task_signature", task),
                steps=common_steps,
                preconditions=preconditions,
                success_rate=success_rate,
                sample_count=len(task_episodes),
            )
        else:
            proc = Procedure(
                task_signature=task,
                steps=common_steps,
                preconditions=preconditions,
                success_rate=success_rate,
                sample_count=len(task_episodes),
            )

        procedures.append(proc)

        if not dry_run:
            _write_procedure(store, proc)

    return procedures
