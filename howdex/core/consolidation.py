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
from howdex.core.feedback import (
    procedure_feedback_confidence,
    procedure_success_rate,
)
from howdex.core.learning import (
    NormalizedLearningStep,
    normalize_steps_for_learning,
)
from howdex.core.parameterize import (
    ParameterizedAction,
    parameter_bindings,
    redact_parameter_evidence,
)
from howdex.core.types import Procedure
from howdex.storage import Store

MIN_SEQUENCE_SIMILARITY = 0.58
MIN_PROCEDURE_CONFIDENCE = 0.60
MAX_RAW_SUPPORTING_EXAMPLES = 12
NON_PROCEDURAL_ACTIONS = {"unknown_action", "internal_memory_action"}


@dataclass(frozen=True)
class _TraceMember:
    normalized: NormalizedLearningStep

    @property
    def raw_step(self) -> dict[str, Any]:
        return self.normalized.raw_step

    @property
    def canonical_action(self) -> CanonicalAction:
        return self.normalized.canonical

    @property
    def parameterized_action(self) -> ParameterizedAction:
        return self.normalized.parameterized

    @property
    def identity(self) -> str:
        return self.normalized.identity


@dataclass(frozen=True)
class _TraceNode:
    signature: str
    label: str
    members: tuple[_TraceMember, ...]


@dataclass(frozen=True)
class _EpisodeTrace:
    episode_id: str
    outcome: str
    raw_steps: list[Any]
    nodes: tuple[_TraceNode, ...]

    @property
    def action_names(self) -> list[str]:
        return [node.signature for node in self.nodes]

    @property
    def dag_labels(self) -> list[str]:
        return [node.label for node in self.nodes]

    @property
    def canonical_actions(self) -> list[CanonicalAction]:
        return [
            member.canonical_action
            for node in self.nodes
            for member in node.members
        ]

    @property
    def canonical_action_names(self) -> list[str]:
        return [
            action.canonical_name for action in self.canonical_actions
        ]

    @property
    def parameterized_actions(self) -> list[ParameterizedAction]:
        return [
            member.parameterized_action
            for node in self.nodes
            for member in node.members
        ]


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
    episode_id = str(
        _get(episode, "session_id")
        or _get(episode, "id")
        or f"episode-{_get(episode, 'started_at', 0)}"
    )
    normalized_steps = normalize_steps_for_learning(
        _normalise_steps(_get(episode, "steps", []) or []),
        episode_id=episode_id,
    )
    raw_steps = [step.raw_step for step in normalized_steps]
    all_actions = [step.canonical for step in normalized_steps]
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

    members = [
        _TraceMember(normalized=step)
        for step in normalized_steps
        if step.canonical.canonical_name not in NON_PROCEDURAL_ACTIONS
    ]
    nodes = _trace_nodes(members)
    if not nodes:
        return None
    return _EpisodeTrace(
        episode_id=episode_id,
        outcome=str(_get(episode, "outcome", "") or ""),
        raw_steps=raw_steps,
        nodes=tuple(nodes),
    )


def _trace_nodes(members: list[_TraceMember]) -> list[_TraceNode]:
    grouped: dict[str, list[_TraceMember]] = {}
    node_order: list[str] = []
    for member in members:
        group_id = member.raw_step.get("parallel_group_id")
        node_key = (
            f"group:{group_id}"
            if group_id
            else f"step:{member.raw_step.get('step_id')}"
        )
        if node_key not in grouped:
            grouped[node_key] = []
            node_order.append(node_key)
        grouped[node_key].append(member)

    nodes: list[_TraceNode] = []
    for node_key in node_order:
        node_members = grouped[node_key]
        if len(node_members) > 1:
            ordered = tuple(sorted(node_members, key=_trace_member_sort_key))
            identities = "|".join(
                member.identity for member in ordered
            )
            names = "|".join(
                member.canonical_action.canonical_name
                for member in ordered
            )
            signature = f"parallel[{identities}]"
            label = f"parallel[{names}]"
        else:
            ordered = tuple(node_members)
            signature = ordered[0].identity
            label = ordered[0].canonical_action.canonical_name
        nodes.append(
            _TraceNode(
                signature=signature,
                label=label,
                members=ordered,
            )
        )
    return nodes


def _trace_member_sort_key(
    member: _TraceMember,
) -> tuple[str, str, str]:
    return (
        member.canonical_action.canonical_name,
        member.identity,
        str(member.raw_step.get("step_id", "")),
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
    previous_step_ids: list[str] = []
    flat_index = 0
    for ordering_index, name in enumerate(names):
        occurrence = occurrences.get(name, 0)
        occurrences[name] = occurrence + 1
        node_examples = [
            matching[occurrence]
            for trace in cluster
            if len(
                matching := [
                    node
                    for node in trace.nodes
                    if node.signature == name
                ]
            )
            > occurrence
        ]
        if not node_examples:
            continue

        member_count = len(node_examples[0].members)
        group_id = (
            f"parallel-{ordering_index + 1:04d}"
            if member_count > 1
            else None
        )
        current_step_ids: list[str] = []
        for member_index in range(member_count):
            member_examples = [
                node.members[member_index]
                for node in node_examples
                if len(node.members) > member_index
            ]
            if not member_examples:
                continue
            step_id = f"procedure-step-{flat_index + 1:04d}"
            steps.append(
                _procedure_step(
                    member_examples,
                    step_id=step_id,
                    parent_step_ids=previous_step_ids,
                    ordering_index=ordering_index,
                    parallel_group_id=group_id,
                    occurrence=occurrence + 1,
                    support_count=len(node_examples),
                )
            )
            current_step_ids.append(step_id)
            flat_index += 1
        previous_step_ids = current_step_ids
    return steps


def _procedure_step(
    examples: list[_TraceMember],
    *,
    step_id: str,
    parent_step_ids: list[str],
    ordering_index: int,
    parallel_group_id: str | None,
    occurrence: int,
    support_count: int,
) -> dict[str, Any]:
    actions = [example.canonical_action for example in examples]
    representative = max(
        actions,
        key=lambda action: (
            action.confidence,
            action.intent,
            action.target or "",
            action.raw_action,
        ),
    )
    raw_actions = sorted(
        {
            str(redact_parameter_evidence(action.raw_action))
            for action in actions
            if action.raw_action
        }
    )
    observations = sorted(
        {
            str(
                redact_parameter_evidence(
                    action.evidence.get("observation")
                )
            )
            for action in actions
            if action.evidence.get("observation")
        }
    )
    template = _representative_template(
        [example.parameterized_action for example in examples]
    )
    span_ids = sorted(
        {
            str(example.raw_step["span_id"])
            for example in examples
            if example.raw_step.get("span_id")
        }
    )
    return {
        "step_id": step_id,
        "parent_step_ids": list(parent_step_ids),
        "span_id": span_ids[0] if len(span_ids) == 1 else None,
        "parallel_group_id": parallel_group_id,
        "ordering_index": ordering_index,
        "action": representative.canonical_name,
        "canonical_name": representative.canonical_name,
        "intent": representative.intent,
        "side_effect_class": representative.side_effect_class,
        "target": representative.target,
        "confidence": round(
            sum(action.confidence for action in actions) / len(actions),
            4,
        ),
        "parameterized_action": template["action"],
        "parameterized_args": template["arguments"],
        "parameterized_target": template["target"],
        "template": template,
        "evidence": {
            "support_count": support_count,
            "occurrence": occurrence,
            "raw_actions": raw_actions,
            "observations": observations[:5],
        },
    }


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
                "steps": redact_parameter_evidence(trace.raw_steps),
                "canonical_sequence": trace.canonical_action_names,
                "dag_sequence": trace.dag_labels,
                "parameterized_sequence": [
                    action.to_dict()
                    for action in trace.parameterized_actions
                ],
                "bindings": parameter_bindings(trace.parameterized_actions),
            }
        )
    return examples


def _representative_template(
    examples: list[ParameterizedAction],
) -> dict[str, Any]:
    if not examples:
        return {"action": "", "arguments": {}, "target": None}
    candidates: dict[str, tuple[int, dict[str, Any]]] = {}
    for example in examples:
        template = {
            "action": example.parameterized_action,
            "arguments": example.parameterized_args,
            "target": example.parameterized_target,
        }
        identity = json.dumps(
            template,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        count, _ = candidates.get(identity, (0, template))
        candidates[identity] = (count + 1, template)
    return max(
        candidates.items(),
        key=lambda item: (item[1][0], item[0]),
    )[1][1]


def _example_bindings(
    traces: list[_EpisodeTrace],
) -> list[dict[str, Any]]:
    return [
        {
            "episode_id": trace.episode_id,
            "bindings": parameter_bindings(trace.parameterized_actions),
        }
        for trace in sorted(traces, key=lambda item: item.episode_id)[
            :MAX_RAW_SUPPORTING_EXAMPLES
        ]
        if parameter_bindings(trace.parameterized_actions)
    ]


def _preconditions(
    canonical_names: list[str],
    failure_traces: list[_EpisodeTrace],
) -> list[str]:
    failed_actions = {
        name
        for trace in failure_traces
        for name in trace.canonical_action_names
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
    child_ids = {
        str(_get(episode, "session_id"))
        for episode in episodes
        if _get(episode, "is_segment", False)
    }
    segmented_parent_ids: set[str] = set()
    for episode in episodes:
        if _get(episode, "is_segment", False):
            continue
        provenance = _get(episode, "provenance", {}) or {}
        expected_children = (
            provenance.get("segment_ids", [])
            if isinstance(provenance, dict)
            else []
        )
        if expected_children and all(
            str(child_id) in child_ids for child_id in expected_children
        ):
            segmented_parent_ids.add(str(_get(episode, "session_id", "")))
    episodes = [
        episode
        for episode in episodes
        if _get(episode, "is_segment", False)
        or str(_get(episode, "session_id", "")) not in segmented_parent_ids
    ]
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
        canonical_nodes = _common_canonical_names(cluster)
        if not canonical_nodes:
            continue

        steps = _canonical_steps(canonical_nodes, cluster)
        if not steps:
            continue

        representative = _medoid(cluster)
        support_traces = _matching_traces(representative, traces)
        learned_support_count = len(support_traces)
        learned_success_count = sum(
            trace.outcome == "success" for trace in support_traces
        )
        base_confidence = _procedure_confidence(
            cluster,
            support_traces,
            steps,
            min_samples=min_samples,
        )
        if base_confidence < MIN_PROCEDURE_CONFIDENCE:
            continue

        failure_traces = [
            trace for trace in support_traces if trace.outcome != "success"
        ]
        existing = store.get_procedure(task)
        feedback_success_count = int(
            _get(existing, "feedback_success_count", 0)
        )
        feedback_failure_count = int(
            _get(existing, "feedback_failure_count", 0)
        )
        support_count = (
            learned_support_count
            + feedback_success_count
            + feedback_failure_count
        )
        success_count = learned_success_count + feedback_success_count
        failure_count = support_count - success_count
        success_rate = procedure_success_rate(
            success_count,
            support_count,
        )
        if feedback_success_count or feedback_failure_count:
            confidence = procedure_feedback_confidence(
                base_confidence=base_confidence,
                success_count=success_count,
                support_count=support_count,
            )
        else:
            confidence = base_confidence
        learned_episode_ids = {
            trace.episode_id for trace in support_traces
        }
        existing_episode_ids = {
            str(episode_id)
            for episode_id in _get(existing, "source_episode_ids", []) or []
        }
        procedure = Procedure(
            id=str(_get(existing, "id") or Procedure().id),
            task_signature=task,
            steps=steps,
            preconditions=_preconditions(
                [
                    str(step["canonical_name"])
                    for step in steps
                    if step.get("canonical_name")
                ],
                failure_traces,
            ),
            expected_outcome="success",
            success_rate=success_rate,
            sample_count=learned_support_count,
            support_count=support_count,
            success_count=success_count,
            failure_count=failure_count,
            confidence=confidence,
            base_confidence=base_confidence,
            feedback_success_count=feedback_success_count,
            feedback_failure_count=feedback_failure_count,
            suggestion_count=int(_get(existing, "suggestion_count", 0)),
            unverified_use_count=int(
                _get(existing, "unverified_use_count", 0)
            ),
            raw_supporting_examples=_raw_examples(support_traces),
            parameter_bindings=_example_bindings(support_traces),
            source_episode_ids=sorted(
                learned_episode_ids | existing_episode_ids
            ),
            created_at=float(_get(existing, "created_at", time.time())),
            last_used_at=_get(existing, "last_used_at"),
            use_count=int(_get(existing, "use_count", 0)),
        )
        procedures.append(procedure)
        if not dry_run:
            _write_procedure(store, procedure)

    return procedures
