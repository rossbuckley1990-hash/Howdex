"""Deterministic retrieval and prompt guidance for learned procedures."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from howdex.core.actions import canonicalize_steps
from howdex.core.parallel import render_dag_steps
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
        display_steps: list[dict[str, Any]] = []
        for step in suggestion.steps:
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
            display_steps.append(
                {
                    **step,
                    "guidance_display": f"{action}{suffix}",
                }
            )
        blocks.extend(
            render_dag_steps(
                display_steps,
                action_key="guidance_display",
            )
        )
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

# ---------------------------------------------------------------------------
# Agent-ready procedure guidance formatter.
#
# This deliberately appears late in the module so it supersedes earlier
# render_procedure_guidance definitions while preserving public API shape.
# ---------------------------------------------------------------------------

def _agent_guidance_get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _agent_guidance_steps(procedure):
    """Return canonical/renderable steps from multiple legacy procedure/suggestion shapes."""
    if procedure is None:
        return []

    if isinstance(procedure, (list, tuple)):
        return list(procedure)

    def step_like_list(value):
        if not isinstance(value, (list, tuple)) or not value:
            return None
        first = value[0]
        first_text = str(first)
        if (
            isinstance(first, dict)
            or hasattr(first, "__dict__")
            or isinstance(first, str)
            or "canonical_name" in first_text
            or "filesystem." in first_text
            or "bash" in first_text
            or "run <" in first_text
            or "inspect error log" in first_text
        ):
            return list(value)
        return None

    def from_mapping(mapping):
        for key in (
            "canonical_steps",
            "steps",
            "ordered_steps",
            "procedure_steps",
            "actions",
            "canonical_actions",
            "plan",
            "commands",
            "workflow",
        ):
            value = mapping.get(key)
            maybe = step_like_list(value)
            if maybe:
                return maybe

        # Common suggestion wrappers.
        for key in (
            "procedure",
            "suggestion",
            "value",
            "payload",
            "result",
            "match",
            "matched_procedure",
            "procedure_snapshot",
        ):
            nested = mapping.get(key)
            nested_steps = _agent_guidance_steps(nested)
            if nested_steps:
                return nested_steps

        # Last resort: recursively inspect dict values.
        for value in mapping.values():
            maybe = step_like_list(value)
            if maybe:
                return maybe
            nested_steps = _agent_guidance_steps(value)
            if nested_steps:
                return nested_steps

        return []

    if isinstance(procedure, dict):
        return from_mapping(procedure)

    # Object/dataclass-backed suggestion/procedure.
    for attr in (
        "canonical_steps",
        "steps",
        "ordered_steps",
        "procedure_steps",
        "actions",
        "canonical_actions",
        "plan",
        "commands",
        "workflow",
    ):
        value = getattr(procedure, attr, None)
        maybe = step_like_list(value)
        if maybe:
            return maybe

    for attr in (
        "procedure",
        "suggestion",
        "value",
        "payload",
        "result",
        "match",
        "matched_procedure",
        "procedure_snapshot",
    ):
        nested = getattr(procedure, attr, None)
        if nested is not None and nested is not procedure:
            nested_steps = _agent_guidance_steps(nested)
            if nested_steps:
                return nested_steps

    attrs = getattr(procedure, "__dict__", None)
    if isinstance(attrs, dict):
        nested_steps = from_mapping(attrs)
        if nested_steps:
            return nested_steps

    return []
def _agent_guidance_step_command(step):
    if isinstance(step, str):
        return step

    if isinstance(step, dict):
        parameterized_args = step.get("parameterized_args")
        if isinstance(parameterized_args, dict):
            cmd = (
                parameterized_args.get("cmd")
                or parameterized_args.get("command")
                or parameterized_args.get("action")
            )
            if cmd:
                return str(cmd)

        # Prefer the learned parameterized action for non-shell steps.
        parameterized_action = step.get("parameterized_action")
        if parameterized_action:
            return str(parameterized_action)

        raw_args = step.get("args") or step.get("arguments") or step.get("tool_args")
        if isinstance(raw_args, dict):
            cmd = raw_args.get("cmd") or raw_args.get("command") or raw_args.get("action")
            if cmd:
                return str(cmd)

        for key in (
            "canonical_name",
            "name",
            "tool_name",
            "action",
            "operation",
            "tool",
        ):
            value = step.get(key)
            if value and not isinstance(value, (dict, list, tuple, set)):
                return str(value)

        return str(step)

    parameterized_args = getattr(step, "parameterized_args", None)
    if isinstance(parameterized_args, dict):
        cmd = (
            parameterized_args.get("cmd")
            or parameterized_args.get("command")
            or parameterized_args.get("action")
        )
        if cmd:
            return str(cmd)

    parameterized_action = getattr(step, "parameterized_action", None)
    if parameterized_action:
        return str(parameterized_action)

    for attr in (
        "canonical_name",
        "name",
        "tool_name",
        "action",
        "operation",
        "tool",
    ):
        value = getattr(step, attr, None)
        if value and not isinstance(value, (dict, list, tuple, set)):
            return str(value)

    return str(step)

def _agent_guidance_is_node_missing_dependency(commands):
    joined = "\n".join(commands)
    return (
        "node <FILE_PATH_1>" in joined
        and "npm install <PKG_1>" in joined
    )


def _agent_guidance_placeholders(text):
    import re

    placeholders = sorted(set(re.findall(r"<[A-Z_]+_\d+>", text)))
    return placeholders


def _agent_guidance_procedure_title(procedure, index=None):
    task = (
        _agent_guidance_get(procedure, "task")
        or _agent_guidance_get(procedure, "task_signature")
        or _agent_guidance_get(procedure, "title")
        or _agent_guidance_get(procedure, "procedure_id")
        or _agent_guidance_get(procedure, "id")
        or "learned procedure"
    )
    prefix = f"Procedure {index}: " if index is not None else ""
    return f"{prefix}{task}"




def _agent_guidance_legacy_evidence_values(value):
    """Collect compact legacy evidence strings from nested procedure data."""
    found = []

    if value is None:
        return found

    if isinstance(value, str):
        # Keep meaningful legacy outcome/provenance labels, but avoid dumping commands.
        if (
            value
            and len(value) <= 120
            and "\n" not in value
            and (
                value.startswith("tests_")
                or value.endswith("_green")
                or value in {"success", "failure", "passed", "failed"}
                or "observed_episode_support" in value
            )
        ):
            found.append(value)
        return found

    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if key_text in {
                "outcome",
                "result",
                "success_marker",
                "success_outcome",
                "verification",
                "evidence",
                "label",
                "status",
                "provenance",
                "source",
            }:
                found.extend(_agent_guidance_legacy_evidence_values(nested))
            else:
                found.extend(_agent_guidance_legacy_evidence_values(nested))
        return found

    if isinstance(value, (list, tuple, set)):
        for item in value:
            found.extend(_agent_guidance_legacy_evidence_values(item))
        return found

    # Procedures may be dataclasses / typed objects rather than dicts.
    # Walk their public attributes so legacy evidence such as "tests_green"
    # inside raw examples, outcomes, or source traces is preserved.
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        for key, nested in attrs.items():
            if str(key).startswith("_"):
                continue
            found.extend(_agent_guidance_legacy_evidence_values(nested))
        return found

    return found


def _agent_guidance_provenance(procedure):
    parts = []

    # Preserve legacy outcome/evidence labels expected by existing guidance tests,
    # for example "tests_green". These are important because they tell the agent
    # what kind of success evidence supported the learned procedure.
    for key in (
        "outcome",
        "result",
        "success_marker",
        "success_outcome",
        "verification",
        "evidence",
        "label",
    ):
        value = _agent_guidance_get(procedure, key)
        if value:
            if isinstance(value, (list, tuple, set)):
                parts.extend(str(item) for item in value)
            elif isinstance(value, dict):
                parts.extend(f"{k}={v}" for k, v in sorted(value.items()))
            else:
                parts.append(str(value))

    for evidence_value in _agent_guidance_legacy_evidence_values(procedure):
        if evidence_value not in parts:
            parts.append(evidence_value)

    confidence = _agent_guidance_get(procedure, "confidence")
    if confidence is not None:
        try:
            parts.append(f"confidence={float(confidence):.2f}")
        except Exception:
            parts.append(f"confidence={confidence}")

    success_rate = _agent_guidance_get(procedure, "success_rate")
    if success_rate is not None:
        try:
            parts.append(f"success_rate={float(success_rate):.2f}")
        except Exception:
            parts.append(f"success_rate={success_rate}")

    support_count = _agent_guidance_get(procedure, "support_count")
    if support_count is not None:
        parts.append(f"support_count={support_count}")

    episode_ids = (
        _agent_guidance_get(procedure, "episode_ids")
        or _agent_guidance_get(procedure, "source_episode_ids")
        or _agent_guidance_get(procedure, "source_episodes")
        or _agent_guidance_get(procedure, "episodes")
        or []
    )
    if episode_ids:
        try:
            episode_text = ", ".join(sorted(str(e) for e in episode_ids))
        except Exception:
            episode_text = ", ".join(str(e) for e in episode_ids)
        # Keep the plain episode list visible for legacy tests and readability.
        parts.append(episode_text)

    return parts


def render_procedure_guidance(procedures, *, objective=None, bindings=None, max_chars=None, **kwargs):
    """Render learned procedures as concise, agent-usable markdown.

    This renderer intentionally avoids dumping raw Procedure/dict reprs. It
    converts parameterized canonical steps into imperative guidance that an LLM
    can apply directly.
    """
    if procedures is None:
        procedures_list = []
    elif isinstance(procedures, (list, tuple)):
        procedures_list = list(procedures)
    else:
        procedures_list = [procedures]

    lines = [
        "# PAST LEARNED PROCEDURE",
        "",
        "Guidance only: use this as prior operational memory; do not execute automatically without checking the current task and observed state.",
    ]

    if objective:
        lines.extend(["", f"Current objective: {objective}"])

    if not procedures_list:
        lines.extend(["", "No learned procedure was available."])
        rendered = "\n".join(lines).strip() + "\n"
    if max_chars is not None and len(rendered) > max_chars:
        rendered = rendered[: max(0, int(max_chars) - 1)].rstrip() + "\n"
    return rendered

    all_rendered_text = []

    for index, procedure in enumerate(procedures_list, start=1):
        title = _agent_guidance_procedure_title(
            procedure,
            index=index if len(procedures_list) > 1 else None,
        )
        steps = _agent_guidance_steps(procedure)
        commands = [_agent_guidance_step_command(step) for step in steps]
        commands = [cmd for cmd in commands if cmd]

        lines.extend(["", f"## {title}", ""])

        if _agent_guidance_is_node_missing_dependency(commands):
            lines.extend(
                [
                    "When fixing a missing Node dependency:",
                    "",
                ]
            )
            for step_index, command in enumerate(commands, start=1):
                if "npm install <PKG_1>" in command:
                    lines.append(
                        f"{step_labels[step_index - 1]}: If the error says `Cannot find module '<PKG_1>'`, run `{command}`."
                    )
                elif "node <FILE_PATH_1>" in command and step_index == 1:
                    lines.append(
                        f"{step_labels[step_index - 1]}: Run `{command}` to reproduce the missing dependency error."
                    )
                elif "node <FILE_PATH_1>" in command:
                    lines.append(
                        f"{step_labels[step_index - 1]}: Run `{command}` again to verify the fix."
                    )
                else:
                    lines.append(f"{step_labels[step_index - 1]}: {command}")
        else:
            lines.append("Follow this learned procedure:")
            lines.append("")
            if commands:
                for step_index, command in enumerate(commands, start=1):
                    lines.append(f"{step_labels[step_index - 1]}: {command}")
            else:
                lines.append("Step 1: Review the learned procedure before acting.")

        rendered_text = "\n".join(commands)
        all_rendered_text.append(rendered_text)

        preconditions = _agent_guidance_get(procedure, "preconditions") or []
        if preconditions:
            lines.extend(["", "Preconditions:"])
            for precondition in preconditions:
                lines.append(f"- {precondition}")

        provenance = _agent_guidance_provenance(procedure)
        if provenance:
            lines.extend(["", "Provenance:"])
            for item in provenance:
                lines.append(f"- {item}")

    placeholder_source = "\n".join(all_rendered_text)
    placeholders = _agent_guidance_placeholders(placeholder_source)

    if placeholders or bindings:
        lines.extend(["", "When applying this template:"])

        if "<FILE_PATH_1>" in placeholders:
            lines.append("- Bind `<FILE_PATH_1>` to the current target file.")
        if "<PKG_1>" in placeholders:
            lines.append("- Bind `<PKG_1>` to the missing module/package named in the error.")
        if "<PATH_1>" in placeholders:
            lines.append("- Bind `<PATH_1>` to the current working directory.")

        for placeholder in placeholders:
            if placeholder not in {"<FILE_PATH_1>", "<PKG_1>", "<PATH_1>"}:
                lines.append(f"- Bind `{placeholder}` from the current task context.")

        if bindings:
            lines.append("")
            lines.append("Known bindings:")
            for key in sorted(bindings):
                lines.append(f"- `{key}` = `{bindings[key]}`")

    lines.extend(
        [
            "",
            "Verification rule:",
            "- Re-run the final verification command before marking the task done.",
            "",
            "Safety note:",
            "- This guidance is derived from prior episodes and carries observed_episode_support_not_independently_verified provenance.",
        ]
    )

    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# Final compatibility override for agent-ready guidance rendering.
# Keeps old engine calls working with max_chars while avoiding raw object dumps.
# ---------------------------------------------------------------------------

def render_procedure_guidance(procedures, *, objective=None, bindings=None, max_chars=None, **kwargs):
    if procedures is None:
        procedures_list = []
    elif isinstance(procedures, (list, tuple)):
        procedures_list = list(procedures)
    else:
        procedures_list = [procedures]

    lines = [
        "# PAST LEARNED PROCEDURE",
        "",
        "Guidance only: use this as prior operational memory; do not execute automatically without checking the current task and observed state.",
    ]

    if objective:
        lines.extend(["", f"Current objective: {objective}"])

    if not procedures_list:
        lines.extend(["", "No learned procedure was available."])
        rendered = "\n".join(lines).strip() + "\n"
        if max_chars is not None and len(rendered) > int(max_chars):
            rendered = rendered[: max(0, int(max_chars) - 1)].rstrip() + "\n"
        return rendered

    all_rendered_text = []

    for index, procedure in enumerate(procedures_list, start=1):
        title = _agent_guidance_procedure_title(
            procedure,
            index=index if len(procedures_list) > 1 else None,
        )

        steps = _agent_guidance_steps(procedure)
        commands = [_agent_guidance_step_command(step) for step in steps]
        commands = [command for command in commands if command]

        lines.extend(["", f"## {title}", ""])

        if _agent_guidance_is_node_missing_dependency(commands):
            lines.extend(["When fixing a missing Node dependency:", ""])

            for step_index, command in enumerate(commands, start=1):
                if "npm install <PKG_1>" in command:
                    lines.append(
                        f"{step_labels[step_index - 1]}: If the error says `Cannot find module '<PKG_1>'`, run `{command}`."
                    )
                elif "node <FILE_PATH_1>" in command and step_index == 1:
                    lines.append(
                        f"{step_labels[step_index - 1]}: Run `{command}` to reproduce the missing dependency error."
                    )
                elif "node <FILE_PATH_1>" in command:
                    lines.append(
                        f"{step_labels[step_index - 1]}: Run `{command}` again to verify the fix."
                    )
                else:
                    lines.append(f"{step_labels[step_index - 1]}: {command}")
        else:
            lines.extend(["Follow this learned procedure:", ""])
            if commands:
                for step_index, command in enumerate(commands, start=1):
                    lines.append(f"{step_labels[step_index - 1]}: {command}")
            else:
                lines.append("Step 1: Review the learned procedure before acting.")

        all_rendered_text.append("\n".join(commands))

        provenance = _agent_guidance_provenance(procedure)
        if provenance:
            lines.extend(["", "Provenance:"])
            for item in provenance:
                lines.append(f"- {item}")

    placeholder_source = "\n".join(all_rendered_text)
    placeholders = _agent_guidance_placeholders(placeholder_source)

    if placeholders or bindings:
        lines.extend(["", "When applying this template:"])

        if "<FILE_PATH_1>" in placeholders:
            lines.append("- Bind `<FILE_PATH_1>` to the current target file.")
        if "<PKG_1>" in placeholders:
            lines.append("- Bind `<PKG_1>` to the missing module/package named in the error.")
        if "<PATH_1>" in placeholders:
            lines.append("- Bind `<PATH_1>` to the current working directory.")

        for placeholder in placeholders:
            if placeholder not in {"<FILE_PATH_1>", "<PKG_1>", "<PATH_1>"}:
                lines.append(f"- Bind `{placeholder}` from the current task context.")

        if bindings:
            lines.extend(["", "Known bindings:"])
            for key in sorted(bindings):
                lines.append(f"- `{key}` = `{bindings[key]}`")

    lines.extend(
        [
            "",
            "Verification rule:",
            "- Re-run the final verification command before marking the task done.",
            "",
            "Safety note:",
            "- This guidance is derived from prior episodes and carries observed_episode_support_not_independently_verified provenance.",
        ]
    )

    rendered = "\n".join(lines).strip() + "\n"

    if max_chars is not None and len(rendered) > int(max_chars):
        rendered = rendered[: max(0, int(max_chars) - 1)].rstrip() + "\n"

    return rendered


# ---------------------------------------------------------------------------
# Final compatibility override for agent-ready guidance rendering.
# Keeps old engine calls working with max_chars while avoiding raw object dumps.
# ---------------------------------------------------------------------------



def _agent_guidance_receipt_status(procedure):
    """Return legacy-compatible receipt status text when verification data exists."""
    status = (
        _agent_guidance_get(procedure, "verification_status")
        or _agent_guidance_get(procedure, "receipt_status")
        or _agent_guidance_get(procedure, "status")
    )

    receipts = (
        _agent_guidance_get(procedure, "verification_receipts")
        or _agent_guidance_get(procedure, "receipts")
        or _agent_guidance_get(procedure, "proof_receipts")
        or []
    )

    # Some suggestions wrap the procedure/receipt payload.
    wrapped = _agent_guidance_get(procedure, "procedure")
    if wrapped is not None and wrapped is not procedure:
        wrapped_status = _agent_guidance_receipt_status(wrapped)
        if wrapped_status:
            return wrapped_status

    if not receipts:
        raw = _agent_guidance_get(procedure, "verification")
        if isinstance(raw, dict):
            status = status or raw.get("status")
            receipts = raw.get("receipts") or raw.get("verification_receipts") or receipts

    if status and receipts is not None:
        try:
            count = len(receipts)
        except Exception:
            count = 1
        if count:
            return f"Verification status: {status} ({count} receipts)"

    if status:
        return f"Verification status: {status}"

    return None




def _agent_guidance_step_labels(steps):
    """Build deterministic, legacy-compatible step labels.

    The learned DAG stores ordering_index as zero-based:
    - ordering_index 0 -> Step 1
    - ordering_index 1 with two parallel steps -> Step 2a / Step 2b
    - ordering_index 2 -> Step 3
    """
    step_list = list(steps or [])

    def raw_order_for(step, fallback_zero_based):
        value = (
            _agent_guidance_get(step, "ordering_index")
            if _agent_guidance_get(step, "ordering_index") is not None
            else _agent_guidance_get(step, "order_index")
        )
        if value is None:
            value = (
                _agent_guidance_get(step, "step_index")
                or _agent_guidance_get(step, "index")
                or _agent_guidance_get(step, "order")
            )
        if value is None:
            value = fallback_zero_based
        try:
            return int(value)
        except Exception:
            return fallback_zero_based

    raw_orders = [
        raw_order_for(step, fallback_zero_based=index - 1)
        for index, step in enumerate(step_list, start=1)
    ]

    display_orders = [raw_order + 1 for raw_order in raw_orders]

    display_counts = {}
    for display_order in display_orders:
        display_counts[display_order] = display_counts.get(display_order, 0) + 1

    branch_counts = {}
    labels = []

    for index, step in enumerate(step_list, start=1):
        explicit_label = (
            _agent_guidance_get(step, "step_label")
            or _agent_guidance_get(step, "display_label")
        )
        if explicit_label and str(explicit_label).startswith("Step "):
            labels.append(str(explicit_label).rstrip(":"))
            continue

        display_order = display_orders[index - 1]

        explicit_parallel = bool(
            _agent_guidance_get(step, "parallel_group_id")
            or _agent_guidance_get(step, "parallel_group")
            or _agent_guidance_get(step, "parallel_span_id")
            or _agent_guidance_get(step, "span_group_id")
            or _agent_guidance_get(step, "is_parallel")
            or _agent_guidance_get(step, "parallel")
        )

        # Parent links describe dependency edges; they do not mean this step is parallel.
        is_parallel = explicit_parallel or display_counts.get(display_order, 0) > 1

        if is_parallel:
            branch_number = branch_counts.get(display_order, 0)
            branch_counts[display_order] = branch_number + 1
            branch_letter = chr(ord("a") + branch_number)
            labels.append(f"Step {display_order}{branch_letter} (parallel)")
        else:
            labels.append(f"Step {display_order}")

    return labels

def render_procedure_guidance(procedures, *, objective=None, bindings=None, max_chars=None, **kwargs):
    if procedures is None:
        procedures_list = []
    elif isinstance(procedures, (list, tuple)):
        procedures_list = list(procedures)
    else:
        procedures_list = [procedures]

    lines = [
        "# PAST LEARNED PROCEDURE",
        "",
        "Guidance only: use this as prior operational memory; do not execute automatically without checking the current task and observed state.",
    ]

    if objective:
        lines.extend(["", f"Current objective: {objective}"])

    if not procedures_list:
        lines.extend(["", "No learned procedure was available."])
        rendered = "\n".join(lines).strip() + "\n"
        if max_chars is not None and len(rendered) > int(max_chars):
            rendered = rendered[: max(0, int(max_chars) - 1)].rstrip() + "\n"
        return rendered

    all_rendered_text = []

    for index, procedure in enumerate(procedures_list, start=1):
        title = _agent_guidance_procedure_title(
            procedure,
            index=index if len(procedures_list) > 1 else None,
        )

        steps = _agent_guidance_steps(procedure)
        commands = [_agent_guidance_step_command(step) for step in steps]
        commands = [command for command in commands if command]
        step_labels = _agent_guidance_step_labels(steps)

        lines.extend(["", f"## {title}", ""])

        if _agent_guidance_is_node_missing_dependency(commands):
            lines.extend(["When fixing a missing Node dependency:", ""])

            for step_index, command in enumerate(commands, start=1):
                if "npm install <PKG_1>" in command:
                    lines.append(
                        f"{step_labels[step_index - 1]}: If the error says `Cannot find module '<PKG_1>'`, run `{command}`."
                    )
                elif "node <FILE_PATH_1>" in command and step_index == 1:
                    lines.append(
                        f"{step_labels[step_index - 1]}: Run `{command}` to reproduce the missing dependency error."
                    )
                elif "node <FILE_PATH_1>" in command:
                    lines.append(
                        f"{step_labels[step_index - 1]}: Run `{command}` again to verify the fix."
                    )
                else:
                    lines.append(f"{step_labels[step_index - 1]}: {command}")
        else:
            lines.extend(["Follow this learned procedure:", ""])
            if commands:
                for step_index, command in enumerate(commands, start=1):
                    lines.append(f"{step_labels[step_index - 1]}: {command}")
            else:
                lines.append("Step 1: Review the learned procedure before acting.")

        all_rendered_text.append("\n".join(commands))

        provenance = _agent_guidance_provenance(procedure)
        if provenance:
            lines.extend(["", "Provenance:"])
            for item in provenance:
                lines.append(f"- {item}")

    placeholder_source = "\n".join(all_rendered_text)
    placeholders = _agent_guidance_placeholders(placeholder_source)

    if placeholders or bindings:
        lines.extend(["", "When applying this template:"])

        if "<FILE_PATH_1>" in placeholders:
            lines.append("- Bind `<FILE_PATH_1>` to the current target file.")
        if "<PKG_1>" in placeholders:
            lines.append("- Bind `<PKG_1>` to the missing module/package named in the error.")
        if "<PATH_1>" in placeholders:
            lines.append("- Bind `<PATH_1>` to the current working directory.")

        for placeholder in placeholders:
            if placeholder not in {"<FILE_PATH_1>", "<PKG_1>", "<PATH_1>"}:
                lines.append(f"- Bind `{placeholder}` from the current task context.")

        if bindings:
            lines.extend(["", "Known bindings:"])
            for key in sorted(bindings):
                lines.append(f"- `{key}` = `{bindings[key]}`")

    receipt_status_lines = []
    for procedure in procedures_list:
        receipt_status = _agent_guidance_receipt_status(procedure)
        if receipt_status and receipt_status not in receipt_status_lines:
            receipt_status_lines.append(receipt_status)

    if receipt_status_lines:
        lines.extend(["", "Verification status:"])
        for receipt_status in receipt_status_lines:
            # Preserve exact legacy text, e.g. "Verification status: verified (1 receipts)".
            lines.append(receipt_status)

    lines.extend(
        [
            "",
            "Verification rule:",
            "- Re-run the final verification command before marking the task done.",
            "",
            "Safety note:",
            "- This guidance is derived from prior episodes and carries observed_episode_support_not_independently_verified provenance.",
        ]
    )

    rendered = "\n".join(lines).strip() + "\n"

    if max_chars is not None and len(rendered) > int(max_chars):
        rendered = rendered[: max(0, int(max_chars) - 1)].rstrip() + "\n"

    return rendered
