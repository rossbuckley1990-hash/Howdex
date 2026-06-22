"""Deterministic retrieval and prompt guidance for learned procedures."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from howdex.core.actions import canonicalize_steps
from howdex.core.receipts import procedure_verification_status
from howdex.core.retrieval import tokenize
from howdex.core.types import Procedure

MAX_PROCEDURE_SUGGESTIONS = 3
DEFAULT_GUIDANCE_MAX_CHARS = 4_000


@dataclass(frozen=True)
class ProcedureSuggestion:
    """One inspectable procedure-retrieval result."""

    procedure_id: str
    task_signature: str
    confidence: float
    success_rate: float
    support_count: int
    steps: list[dict[str, Any]]
    preconditions: list[str]
    source_episode_ids: list[str]
    score: float
    match_explanation: dict[str, Any]
    proof_status: str
    verification_status: str
    procedure_verified: bool
    verification_receipts: list[dict[str, Any]]

    @property
    def canonical_steps(self) -> list[dict[str, Any]]:
        return self.steps

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "task_signature": self.task_signature,
            "confidence": self.confidence,
            "success_rate": self.success_rate,
            "support_count": self.support_count,
            "canonical_steps": self.canonical_steps,
            "preconditions": self.preconditions,
            "source_episode_ids": self.source_episode_ids,
            "score": self.score,
            "match_explanation": self.match_explanation,
            "proof_status": self.proof_status,
            "verification_status": self.verification_status,
            "procedure_verified": self.procedure_verified,
            "verification_receipts": self.verification_receipts,
        }


def suggest_procedures(
    procedures: Iterable[Procedure],
    task: str,
    context: dict[str, Any] | str | None = None,
    *,
    top_k: int = MAX_PROCEDURE_SUGGESTIONS,
    min_confidence: float = 0.0,
) -> list[ProcedureSuggestion]:
    """Rank relevant learned procedures using deterministic local evidence."""
    task_text = " ".join(str(task or "").split())
    task_tokens = set(tokenize(task_text))
    context_text, context_actions, context_targets, context_domains = (
        _context_features(context)
    )
    task_actions = canonicalize_steps([task_text]) if task_text else []
    for action in task_actions:
        if action.canonical_name in {
            "unknown_action",
            "internal_memory_action",
        }:
            continue
        context_actions.add(action.canonical_name)
        if action.target and not action.target.startswith("args:sha256:"):
            context_targets.add(action.target)
        if "." in action.canonical_name:
            context_domains.add(action.canonical_name.split(".", 1)[0])
    context_tokens = set(tokenize(context_text))
    ranked: list[ProcedureSuggestion] = []

    for procedure in procedures:
        if procedure.confidence < min_confidence:
            continue
        task_similarity = _task_similarity(task_text, task_tokens, procedure)
        action_overlap = _action_overlap(context_actions, procedure)
        target_overlap = _target_overlap(
            context_tokens,
            context_targets,
            procedure,
        )
        domain_overlap = _domain_overlap(context_domains, procedure)
        relevance = max(
            task_similarity,
            action_overlap,
            target_overlap,
            domain_overlap,
        )
        if relevance <= 0.0:
            continue

        quality = round(
            (0.55 * _bounded(procedure.confidence))
            + (0.45 * _bounded(procedure.success_rate)),
            6,
        )
        score = round(
            (0.45 * task_similarity)
            + (0.20 * action_overlap)
            + (0.10 * target_overlap)
            + (0.05 * domain_overlap)
            + (0.20 * quality),
            6,
        )
        matched = [
            name
            for name, value in (
                ("task_signature", task_similarity),
                ("canonical_actions", action_overlap),
                ("target_hints", target_overlap),
                ("domain_hints", domain_overlap),
            )
            if value > 0.0
        ]
        verification_status = procedure_verification_status(
            procedure.receipts
        )
        ranked.append(
            ProcedureSuggestion(
                procedure_id=procedure.id,
                task_signature=procedure.task_signature,
                confidence=procedure.confidence,
                success_rate=procedure.success_rate,
                support_count=procedure.support_count,
                steps=_normalise_steps(procedure.steps),
                preconditions=list(procedure.preconditions),
                source_episode_ids=sorted(procedure.source_episode_ids),
                score=score,
                match_explanation={
                    "matched_by": matched,
                    "task_similarity": task_similarity,
                    "canonical_action_overlap": action_overlap,
                    "target_overlap": target_overlap,
                    "domain_overlap": domain_overlap,
                    "procedure_quality": quality,
                    "recency_used": False,
                },
                proof_status=_proof_status(procedure),
                verification_status=verification_status,
                procedure_verified=verification_status == "verified",
                verification_receipts=list(procedure.receipts),
            )
        )

    ranked.sort(
        key=lambda suggestion: (
            -suggestion.score,
            -suggestion.confidence,
            -suggestion.success_rate,
            -suggestion.support_count,
            suggestion.task_signature,
            suggestion.procedure_id,
        )
    )
    limit = min(
        MAX_PROCEDURE_SUGGESTIONS,
        max(0, int(top_k)),
    )
    return ranked[:limit]


def render_procedure_guidance(
    suggestions: ProcedureSuggestion | Iterable[ProcedureSuggestion],
    *,
    max_chars: int = DEFAULT_GUIDANCE_MAX_CHARS,
) -> str:
    """Render compact, deterministic guidance suitable for prompt injection."""
    if isinstance(suggestions, ProcedureSuggestion):
        items = [suggestions]
    else:
        items = list(suggestions)
    if not items or max_chars <= 0:
        return ""

    blocks = [
        "[Howdex procedure guidance]",
        "WARNING: Guidance only. Review preconditions and evidence; do not execute automatically.",
    ]
    for index, suggestion in enumerate(items, start=1):
        explanation = suggestion.match_explanation
        blocks.extend(
            [
                f"Suggestion {index}: {suggestion.task_signature}",
                (
                    f"Procedure: {suggestion.procedure_id} | "
                    f"match={suggestion.score:.4f} | "
                    f"confidence={suggestion.confidence:.4f} | "
                    f"success_rate={suggestion.success_rate:.4f} | "
                    f"support={suggestion.support_count}"
                ),
                (
                    "Matched by: "
                    + (
                        ", ".join(explanation.get("matched_by", []))
                        or "unspecified"
                    )
                ),
                (
                    "Preconditions: "
                    + (
                        ", ".join(suggestion.preconditions)
                        if suggestion.preconditions
                        else "none recorded"
                    )
                ),
                "Steps:",
            ]
        )
        for step_index, step in enumerate(suggestion.steps, start=1):
            action = str(
                step.get("parameterized_action")
                or step.get("canonical_name")
                or step.get("action")
                or "unknown_action"
            )
            details = [
                (
                    f"target="
                    f"{step.get('parameterized_target') or step.get('target')}"
                )
                if step.get("parameterized_target") or step.get("target")
                else "",
                f"intent={step['intent']}" if step.get("intent") else "",
                (
                    f"side_effect_class={step['side_effect_class']}"
                    if step.get("side_effect_class")
                    else ""
                ),
            ]
            details = [detail for detail in details if detail]
            suffix = f" ({'; '.join(details)})" if details else ""
            blocks.append(f"{step_index}. {action}{suffix}")
        blocks.extend(
            [
                f"Proof status: {suggestion.proof_status}",
                (
                    f"Verification status: "
                    f"{suggestion.verification_status} "
                    f"({len(suggestion.verification_receipts)} receipts)"
                ),
                (
                    "Source episodes: "
                    + (
                        ", ".join(suggestion.source_episode_ids)
                        if suggestion.source_episode_ids
                        else "none recorded"
                    )
                ),
            ]
        )

    return _truncate("\n".join(blocks), max_chars)


def _context_features(
    context: dict[str, Any] | str | None,
) -> tuple[str, set[str], set[str], set[str]]:
    if context is None:
        return "", set(), set(), set()
    if isinstance(context, str):
        return " ".join(context.split()), set(), set(), set()

    text = json.dumps(
        context,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    steps = _context_steps(context)
    canonical = canonicalize_steps(steps) if steps else []
    actions = {
        action.canonical_name
        for action in canonical
        if action.canonical_name not in {
            "unknown_action",
            "internal_memory_action",
        }
    }
    targets = {
        action.target
        for action in canonical
        if action.target and not action.target.startswith("args:sha256:")
    }
    domains = {
        action.canonical_name.split(".", 1)[0]
        for action in canonical
        if "." in action.canonical_name
    }
    return text, actions, targets, domains


def _context_steps(context: dict[str, Any]) -> list[Any]:
    steps = context.get("steps")
    if isinstance(steps, list):
        return steps
    actions = context.get("canonical_actions") or context.get("actions")
    if isinstance(actions, list):
        return actions
    if any(
        key in context
        for key in (
            "tool_name",
            "tool",
            "function",
            "tool_call",
            "canonical_action",
        )
    ):
        return [context]
    return []


def _task_similarity(
    task_text: str,
    task_tokens: set[str],
    procedure: Procedure,
) -> float:
    signature = " ".join(procedure.task_signature.split())
    signature_tokens = set(tokenize(signature))
    if task_text and task_text.lower() == signature.lower():
        return 1.0
    if task_text and (
        task_text.lower() in signature.lower()
        or signature.lower() in task_text.lower()
    ):
        return 0.95
    return _jaccard(task_tokens, signature_tokens)


def _action_overlap(
    context_actions: set[str],
    procedure: Procedure,
) -> float:
    procedure_actions = {
        str(step.get("canonical_name") or step.get("action"))
        for step in _normalise_steps(procedure.steps)
        if step.get("canonical_name") or step.get("action")
    }
    return _coverage(context_actions, procedure_actions)


def _target_overlap(
    context_tokens: set[str],
    context_targets: set[str],
    procedure: Procedure,
) -> float:
    procedure_targets = {
        str(step.get("target"))
        for step in _normalise_steps(procedure.steps)
        if step.get("target")
    }
    exact = _coverage(context_targets, procedure_targets)
    target_tokens = set(
        token
        for target in procedure_targets
        for token in tokenize(target)
    )
    lexical = _coverage(context_tokens, target_tokens)
    return round(max(exact, lexical), 6)


def _domain_overlap(
    context_domains: set[str],
    procedure: Procedure,
) -> float:
    procedure_domains = {
        action.split(".", 1)[0]
        for action in (
            str(step.get("canonical_name") or step.get("action") or "")
            for step in _normalise_steps(procedure.steps)
        )
        if "." in action
    }
    return _coverage(context_domains, procedure_domains)


def _proof_status(procedure: Procedure) -> str:
    if procedure.unverified_use_count > 0:
        return "pending_unverified_use"
    if procedure.source_episode_ids and procedure.support_count > 0:
        return "observed_episode_support_not_independently_verified"
    return "unverified"


def _normalise_steps(steps: list[Any]) -> list[dict[str, Any]]:
    return [
        dict(step)
        if isinstance(step, dict)
        else {"action": str(step), "canonical_name": str(step)}
        for step in steps
    ]


def _coverage(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return round(len(left & right) / len(left), 6)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return round(len(left & right) / len(left | right), 6)


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars == 1:
        return "…"
    return value[: max_chars - 1].rstrip() + "…"
