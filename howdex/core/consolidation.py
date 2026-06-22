"""Deterministic consolidation from messy episodes into inspectable procedures."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any

from howdex.core.actions import (
    CanonicalAction,
    canonical_sequence_similarity,
    canonicalize_steps,
)
from howdex.core.tool_calls import redact_secrets
from howdex.core.types import Procedure
from howdex.storage import Store

MIN_SEQUENCE_SIMILARITY = 0.58
MIN_PROCEDURE_CONFIDENCE = 0.60
MAX_RAW_SUPPORTING_EXAMPLES = 12
NON_PROCEDURAL_ACTIONS = {"unknown_action", "internal_memory_action"}


@dataclass(frozen=True)
class _EpisodeTrace:
    episode_id: str
    outcome: str
    raw_steps: list[Any]
    canonical_actions: list[CanonicalAction]

    @property
    def action_names(self) -> list[str]:
        return [action.canonical_name for action in self.canonical_actions]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_task(task: str) -> str:
    return " ".join((task or "").lower().split())[:200]


def _normalise_steps(steps: Any) -> list[Any]:
    """Decode list-like episode steps from SQLite or object-backed stores."""
    if steps is None:
        return []
    if isinstance(steps, str):
        try:
            parsed = json.loads(steps)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return steps if isinstance(steps, list) else []


def is_procedural_action(action: str | None) -> bool:
    """Return whether a raw action canonicalises to executable know-how."""
    if not action:
        return False
    canonical = canonicalize_steps([action])[0]
    return canonical.canonical_name not in NON_PROCEDURAL_ACTIONS


def _trace_from_episode(episode: Any) -> _EpisodeTrace | None:
    raw_steps = _normalise_steps(_get(episode, "steps", []) or [])
    all_actions = canonicalize_steps(raw_steps)
    non_internal = [
        action
        for action in all_actions
        if action.canonical_name != "internal_memory_action"
    ]
    actionable = [
        action
        for action in non_internal
        if action.canonical_name != "unknown_action"
    ]

    if not actionable or not non_internal:
        return None

    known_ratio = len(actionable) / len(non_internal)
    if known_ratio < 0.5:
        return None

    episode_id = str(
        _get(episode, "session_id")
        or _get(episode, "id")
        or f"episode-{_get(episode, 'started_at', 0)}"
    )
    return _EpisodeTrace(
        episode_id=episode_id,
        outcome=str(_get(episode, "outcome", "") or ""),
        raw_steps=raw_steps,
        canonical_actions=actionable,
    )


def _cluster_successes(
    traces: list[_EpisodeTrace],
    *,
    threshold: float = MIN_SEQUENCE_SIMILARITY,
) -> list[list[_EpisodeTrace]]:
    """Greedily complete-link cluster traces in deterministic order."""
    ordered = sorted(traces, key=lambda trace: (tuple(trace.action_names), trace.episode_id))
    clusters: list[list[_EpisodeTrace]] = []

    for trace in ordered:
        candidates: list[tuple[float, int]] = []
        for index, cluster in enumerate(clusters):
            scores = [
                canonical_sequence_similarity(trace.action_names, member.action_names)
                for member in cluster
            ]
            if scores and min(scores) >= threshold:
                candidates.append((sum(scores) / len(scores), index))

        if not candidates:
            clusters.append([trace])
            continue

        _, best_index = max(candidates, key=lambda item: (item[0], -item[1]))
        clusters[best_index].append(trace)

    return clusters


def _cluster_cohesion(cluster: list[_EpisodeTrace]) -> float:
    if len(cluster) <= 1:
        return 1.0
    scores: list[float] = []
    for left_index, left in enumerate(cluster):
        for right in cluster[left_index + 1 :]:
            scores.append(
                canonical_sequence_similarity(left.action_names, right.action_names)
            )
    return sum(scores) / len(scores)


def _medoid(cluster: list[_EpisodeTrace]) -> _EpisodeTrace:
    def average_similarity(trace: _EpisodeTrace) -> float:
        scores = [
            canonical_sequence_similarity(trace.action_names, other.action_names)
            for other in cluster
        ]
        return sum(scores) / len(scores)

    return max(
        cluster,
        key=lambda trace: (
            average_similarity(trace),
            -len(trace.action_names),
            tuple(trace.action_names),
            trace.episode_id,
        ),
    )


def _is_subsequence(short: list[str], long: list[str]) -> bool:
    if not short:
        return True
    index = 0
    for item in long:
        if item == short[index]:
            index += 1
            if index == len(short):
                return True
    return False


def _common_canonical_names(cluster: list[_EpisodeTrace]) -> list[str]:
    """Find the longest contiguous medoid slice supported as a subsequence."""
    medoid = _medoid(cluster)
    reference = medoid.action_names
    required_support = max(2, math.ceil(len(cluster) * 0.6)) if len(cluster) > 1 else 1

    for size in range(len(reference), 0, -1):
        for start in range(0, len(reference) - size + 1):
            candidate = reference[start : start + size]
            support = sum(
                1 for trace in cluster if _is_subsequence(candidate, trace.action_names)
            )
            if support >= required_support:
                return candidate
    return []


def _canonical_steps(
    names: list[str],
    cluster: list[_EpisodeTrace],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    for name in names:
        occurrence = occurrences.get(name, 0)
        occurrences[name] = occurrence + 1
        examples = [
            matching[occurrence]
            for trace in cluster
            if len(
                matching := [
                    action
                    for action in trace.canonical_actions
                    if action.canonical_name == name
                ]
            )
            > occurrence
        ]
        if not examples:
            continue

        representative = max(
            examples,
            key=lambda action: (
                action.confidence,
                action.intent,
                action.target or "",
                action.raw_action,
            ),
        )
        raw_actions = sorted({action.raw_action for action in examples if action.raw_action})
        observations = sorted(
            {
                str(action.evidence.get("observation"))
                for action in examples
                if action.evidence.get("observation")
            }
        )
        steps.append(
            {
                "action": name,
                "canonical_name": name,
                "intent": representative.intent,
                "side_effect_class": representative.side_effect_class,
                "target": representative.target,
                "confidence": round(
                    sum(action.confidence for action in examples) / len(examples),
                    4,
                ),
                "evidence": {
                    "support_count": len(
                        {
                            trace.episode_id
                            for trace in cluster
                            if sum(
                                action.canonical_name == name
                                for action in trace.canonical_actions
                            )
                            > occurrence
                        }
                    ),
                    "occurrence": occurrence + 1,
                    "raw_actions": raw_actions,
                    "observations": observations[:5],
                },
            }
        )
    return steps


def _matching_traces(
    representative: _EpisodeTrace,
    traces: list[_EpisodeTrace],
) -> list[_EpisodeTrace]:
    return [
        trace
        for trace in traces
        if canonical_sequence_similarity(
            representative.action_names,
            trace.action_names,
        )
        >= MIN_SEQUENCE_SIMILARITY
    ]


def _raw_examples(traces: list[_EpisodeTrace]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for trace in sorted(traces, key=lambda item: item.episode_id)[
        :MAX_RAW_SUPPORTING_EXAMPLES
    ]:
        examples.append(
            {
                "episode_id": trace.episode_id,
                "outcome": trace.outcome,
                "steps": redact_secrets(trace.raw_steps)[0],
                "canonical_sequence": trace.action_names,
            }
        )
    return examples


def _preconditions(
    canonical_names: list[str],
    failure_traces: list[_EpisodeTrace],
) -> list[str]:
    failed_actions = {
        name
        for trace in failure_traces
        for name in trace.action_names
    }
    return sorted({name for name in canonical_names if name not in failed_actions})


def _procedure_confidence(
    cluster: list[_EpisodeTrace],
    support_traces: list[_EpisodeTrace],
    canonical_steps: list[dict[str, Any]],
    *,
    min_samples: int,
) -> float:
    cohesion = _cluster_cohesion(cluster)
    success_count = sum(trace.outcome == "success" for trace in support_traces)
    success_rate = success_count / len(support_traces)
    action_confidence = (
        sum(step["confidence"] for step in canonical_steps) / len(canonical_steps)
        if canonical_steps
        else 0.0
    )
    support_factor = min(1.0, len(cluster) / max(min_samples, 3))
    confidence = (
        (0.40 * cohesion)
        + (0.30 * success_rate)
        + (0.20 * action_confidence)
        + (0.10 * support_factor)
    )
    return round(min(1.0, max(0.0, confidence)), 4)


def _write_procedure(store: Store, procedure: Procedure) -> None:
    store.put_procedure(dict(procedure.__dict__))


def consolidate(
    store: Store,
    *,
    min_samples: int = 3,
    dry_run: bool = False,
) -> list[Procedure]:
    """Consolidate canonical near-matching successful traces into procedures."""
    episodes = store.query_episodes(limit=10_000)
    by_task: dict[str, list[Any]] = {}
    for episode in episodes:
        task = _normalize_task(_get(episode, "task", "") or "")
        if task:
            by_task.setdefault(task, []).append(episode)

    procedures: list[Procedure] = []
    for task in sorted(by_task):
        traces = [
            trace
            for episode in by_task[task]
            if (trace := _trace_from_episode(episode)) is not None
        ]
        success_traces = [
            trace for trace in traces if trace.outcome == "success"
        ]
        if len(success_traces) < min_samples:
            continue

        clusters = [
            cluster
            for cluster in _cluster_successes(success_traces)
            if len(cluster) >= min_samples
        ]
        if not clusters:
            continue

        cluster = max(
            clusters,
            key=lambda candidate: (
                len(candidate),
                _cluster_cohesion(candidate),
                tuple(_medoid(candidate).action_names),
            ),
        )
        canonical_names = _common_canonical_names(cluster)
        if not canonical_names:
            continue

        steps = _canonical_steps(canonical_names, cluster)
        if not steps:
            continue

        representative = _medoid(cluster)
        support_traces = _matching_traces(representative, traces)
        support_count = len(support_traces)
        success_count = sum(
            trace.outcome == "success" for trace in support_traces
        )
        success_rate = success_count / support_count if support_count else 0.0
        confidence = _procedure_confidence(
            cluster,
            support_traces,
            steps,
            min_samples=min_samples,
        )
        if confidence < MIN_PROCEDURE_CONFIDENCE:
            continue

        failure_traces = [
            trace for trace in support_traces if trace.outcome != "success"
        ]
        existing = store.get_procedure(task)
        procedure = Procedure(
            id=str(_get(existing, "id") or Procedure().id),
            task_signature=task,
            steps=steps,
            preconditions=_preconditions(canonical_names, failure_traces),
            expected_outcome="success",
            success_rate=round(success_rate, 4),
            sample_count=support_count,
            support_count=support_count,
            success_count=success_count,
            confidence=confidence,
            raw_supporting_examples=_raw_examples(support_traces),
            source_episode_ids=sorted(
                trace.episode_id for trace in support_traces
            ),
            created_at=float(_get(existing, "created_at", time.time())),
            last_used_at=_get(existing, "last_used_at"),
            use_count=int(_get(existing, "use_count", 0)),
        )
        procedures.append(procedure)
        if not dry_run:
            _write_procedure(store, procedure)

    return procedures
