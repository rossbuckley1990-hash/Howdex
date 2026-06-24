"""Agent-ready operational-memory Markdown rendering."""

from __future__ import annotations

from typing import Any

import howdex.telemetry as telemetry
from howdex.core.codex_staleness import (
    StalenessDecision,
    apply_staleness_confidence,
    evaluate_codex_staleness,
    has_compatibility_metadata,
    staleness_guidance_text,
)
from howdex.core.guidance_budget import (
    GuidanceProcedureSelection,
    select_guidance_procedures,
)
from howdex.core.guidance_artifacts import (
    failed_attempts,
    language_for_path,
    source_artifacts,
)
from howdex.core.guidance_facts import (
    procedure_relevant_to_objective,
    relevant_learned_facts,
    relevant_operational_data_flow,
    relevant_verification_requirements,
    text_relevant_to_objective,
)
from howdex.core.guidance_utils import (
    as_list,
    get_value,
    truncate_with_marker,
    unique_strings,
)
from howdex.core.receipts import procedure_trust_status

DEFAULT_AGENT_GUIDANCE_MAX_CHARS = 6_000


def render_agent_guidance(
    procedures: Any,
    *,
    objective: str | None = None,
    mode: str = "operational_memory",
    constraints: Any = None,
    target_environment: str | None = None,
    include_source: bool = False,
    include_failed_attempts: bool = True,
    include_verification: bool = True,
    current_environment: Any = None,
    retrieval_budget: Any = None,
    debug: bool = False,
    max_chars: int = DEFAULT_AGENT_GUIDANCE_MAX_CHARS,
) -> str:
    """Render procedure memory as deterministic agent-ready Markdown."""
    del mode  # Reserved public compatibility argument.
    items = as_list(procedures)
    selection: GuidanceProcedureSelection | None = None
    if retrieval_budget is not None:
        selection = select_guidance_procedures(
            str(objective or ""),
            items,
            retrieval_budget,
        )
        relevant_items = list(selection.selected)
        if selection.max_guidance_chars:
            max_chars = min(max_chars, selection.max_guidance_chars)
    else:
        relevant_items = _relevant_items(items, objective)
    staleness_environment = (
        current_environment if current_environment is not None else target_environment
    )
    staleness = _staleness_decisions(relevant_items, staleness_environment)
    active_items = [
        procedure
        for procedure in relevant_items
        if staleness.get(id(procedure), StalenessDecision()).status != "incompatible"
    ]
    lines = [
        "# HOWDEX OPERATIONAL MEMORY",
        "",
        (
            "Use this as prior operational memory. It is not source code "
            "unless a Source artifacts section is explicitly present."
        ),
        (
            "Treat memory as guidance, not proof. Verify in the current "
            "environment before marking the task complete."
        ),
        "",
    ]
    if objective:
        lines.extend(["Objective:", str(objective).strip(), ""])

    lines.extend(
        [
            "Rules:",
            ("- Use the memory to guide execution, but adapt it to the current environment."),
            "- Do not claim completion until a real verifier succeeds.",
            "- Do not repeat known failed attempts.",
        ]
    )
    if not include_source:
        lines.append("- Do not ask for or rely on pasted source code; use the operational facts.")
    if target_environment:
        lines.append(f"- Target environment: {target_environment}")
    lines.extend(f"- {item}" for item in unique_strings(constraints))
    lines.append("")

    if selection is not None:
        lines.extend(
            [
                "Retrieval budget:",
                f"- Selected procedures: {len(selection.selected)}",
                f"- Omitted procedures: {selection.omitted_count}",
                (
                    "- Context budget used: "
                    f"{selection.context_budget_used}/{selection.max_guidance_chars} chars"
                ),
            ]
        )
        if debug:
            lines.append("- Omission reasons:")
            if selection.excluded:
                for excluded in selection.excluded:
                    lines.append(
                        f"  - {excluded.procedure_id}: {excluded.reason} "
                        f"(score={excluded.relevance_score:.3f}, "
                        f"status={excluded.status}, "
                        f"staleness={excluded.staleness_status})"
                    )
            else:
                lines.append("  - None")
        lines.append("")

    lines.append("Relevant memory:")
    if relevant_items:
        for index, procedure in enumerate(relevant_items, start=1):
            task_signature = _procedure_label(procedure, index)
            meta: list[str] = []
            confidence = get_value(procedure, "confidence")
            if confidence is not None:
                try:
                    confidence_value = float(confidence)
                    decision = staleness.get(id(procedure))
                    if decision is not None:
                        confidence_value = apply_staleness_confidence(
                            confidence_value,
                            decision,
                        )
                        meta.append(
                            f"staleness={decision.status}"
                        )
                    meta.append(f"confidence={confidence_value:.3f}")
                except (TypeError, ValueError):
                    meta.append(f"confidence={confidence}")
            support = get_value(procedure, "support_count")
            if support is not None:
                meta.append(f"support={support}")
            suffix = f" ({'; '.join(meta)})" if meta else ""
            lines.append(f"- {task_signature}{suffix}")
    else:
        lines.append("- No prior procedure memory was provided.")
    lines.append("")

    if relevant_items:
        lines.append("Procedure trust:")
        for index, procedure in enumerate(relevant_items, start=1):
            task_signature = _procedure_label(procedure, index)
            status = procedure_trust_status(procedure)
            lines.append(f"- {task_signature}: {status}. {_trust_instruction(status)}")
        lines.append("")

    if staleness:
        lines.append("Codex staleness:")
        for index, procedure in enumerate(relevant_items, start=1):
            decision = staleness.get(id(procedure))
            if decision is None:
                continue
            lines.append(
                f"- {_procedure_label(procedure, index)}: "
                f"{staleness_guidance_text(decision)}"
            )
        lines.append("")

    blocked_items = [
        (index, procedure, decision)
        for index, procedure in enumerate(relevant_items, start=1)
        if (decision := staleness.get(id(procedure))) is not None
        and decision.status == "incompatible"
    ]
    if blocked_items:
        lines.append("Blocked/historical memory:")
        for index, procedure, decision in blocked_items:
            lines.append(
                f"- {_procedure_label(procedure, index)}: not recommended for "
                "the current environment; keep only as historical context "
                f"until reverified ({'; '.join(decision.reasons)})."
            )
        lines.append("")

    facts = unique_strings(
        [
            fact
            for procedure in active_items
            for fact in relevant_learned_facts(
                procedure,
                objective=objective,
            )
        ]
    )
    failures = unique_strings(
        [
            failed
            for procedure in active_items
            for failed in failed_attempts(procedure)
            if text_relevant_to_objective(
                failed,
                procedure,
                objective=objective,
            )
        ]
    )
    verification = unique_strings(
        [
            requirement
            for procedure in active_items
            for requirement in relevant_verification_requirements(
                procedure,
                objective=objective,
            )
        ]
    )
    for index, procedure in enumerate(relevant_items, start=1):
        decision = staleness.get(id(procedure))
        if decision is None or decision.status == "fresh":
            continue
        verification.append(
            (
                f"Reverify {_procedure_label(procedure, index)} before relying "
                f"on it because Codex staleness status is {decision.status}."
            )
        )
    artifacts = [
        artifact
        for procedure in active_items
        for artifact in source_artifacts(procedure)
    ]
    flows = [
        flow
        for procedure in active_items
        if (flow := relevant_operational_data_flow(procedure, objective=objective)).steps
    ]

    lines.append("Learned operational facts:")
    if facts:
        lines.extend(f"- {fact}" for fact in facts)
    else:
        lines.append("- No explicit operational facts were extracted.")
    lines.append("")

    if flows:
        data_flow_steps = unique_strings([step for flow in flows for step in flow.steps])
        execution_hints = unique_strings([hint for flow in flows for hint in flow.execution_hints])
        lines.append("Data flow:")
        lines.extend(f"- {step}" for step in data_flow_steps)
        lines.append("")
        lines.append("For Bash:")
        lines.extend(f"- {hint}" for hint in execution_hints)
        lines.append("")

    if include_source:
        lines.append("Source artifacts:")
        if artifacts:
            for artifact in artifacts:
                file_path = artifact["file_path"]
                lines.extend(
                    [
                        f"Write `{file_path}` with this exact content:",
                        "",
                        f"```{language_for_path(file_path)}",
                        artifact["content"].rstrip(),
                        "```",
                        "",
                    ]
                )
        else:
            lines.extend(["- No source artifacts were found.", ""])
    else:
        lines.extend(
            [
                "Source artifacts excluded:",
                "- Source code was intentionally not included in this guidance.",
                ("- Reconstruct an implementation from the learned operational facts."),
                "",
            ]
        )

    if include_failed_attempts:
        lines.append("Avoid these failed attempts:")
        if failures:
            for failed in failures:
                if "cat seed.txt | rev | printf" in failed:
                    failed += (
                        " — printf does not read from stdin. Do not pipe into "
                        "printf; printf does not read stdin. Use command "
                        "substitution such as "
                        'printf %s "$(cat seed.txt | rev)".'
                    )
                lines.append(f"- {failed}")
        else:
            lines.append("- No failed attempts were provided.")
        lines.append("")

    if include_verification:
        lines.append("Verification:")
        lines.extend(f"- {item}" for item in verification)
        lines.append("")

    lines.extend(
        [
            "Execution instruction:",
            ("- Convert this memory into concrete tool calls for the current environment."),
            ("- Prefer the shortest verified path that satisfies the constraints."),
            ("- If a verifier fails, update the plan rather than repeating the same command."),
            "",
        ]
    )
    rendered = truncate_with_marker(
        "\n".join(lines),
        max_chars,
        marker="\n[Howdex guidance truncated]\n",
    )
    with telemetry.span(
        "howdex.guidance.render",
        {
            "howdex.selected_count": len(relevant_items),
            "howdex.guidance_chars": len(rendered),
            "howdex.include_source": include_source,
        },
    ):
        for procedure in active_items:
            with telemetry.span(
                "howdex.procedure.inject",
                _procedure_trace_attributes(procedure),
            ):
                pass
    return rendered


def _trust_instruction(status: str) -> str:
    if status == "verified":
        return "Independent evidence exists; still verify in the current environment."
    if status == "failed_verification":
        return (
            "Independent verification failed; do not rely on this procedure without investigation."
        )
    if status == "stale":
        return "Evidence is stale; require fresh verification before relying on it."
    if status == "observed_episode_support":
        return "Successful episodes support it, but it is not independently verified."
    return "Unverified memory; treat it only as guidance until a real verifier succeeds."


def _relevant_items(items: list[Any], objective: str | None) -> list[Any]:
    """Filter suggested procedures before rendering task-specific guidance."""
    if not items:
        return []
    if not str(objective or "").strip():
        return items
    return [
        item
        for item in items
        if procedure_relevant_to_objective(item, objective=objective)
    ]


def _procedure_label(procedure: Any, index: int) -> str:
    return (
        get_value(procedure, "task_signature")
        or get_value(procedure, "name")
        or get_value(procedure, "title")
        or get_value(procedure, "procedure_id")
        or get_value(procedure, "id")
        or f"procedure_{index}"
    )


def _staleness_decisions(
    procedures: list[Any],
    current_environment: Any,
) -> dict[int, StalenessDecision]:
    decisions: dict[int, StalenessDecision] = {}
    for procedure in procedures:
        if not has_compatibility_metadata(procedure):
            continue
        decisions[id(procedure)] = evaluate_codex_staleness(
            procedure,
            current_environment,
        )
    return decisions


def _procedure_trace_attributes(procedure: Any) -> dict[str, Any]:
    source_episode_ids = as_list(get_value(procedure, "source_episode_ids"))
    status = get_value(procedure, "procedure_status") or get_value(
        procedure,
        "status",
    )
    if not status:
        try:
            status = procedure_trust_status(procedure)
        except Exception:
            status = "unknown"
    return {
        "howdex.procedure_id": (
            get_value(procedure, "procedure_id")
            or get_value(procedure, "id")
            or get_value(procedure, "task_signature")
            or ""
        ),
        "howdex.procedure_status": status,
        "howdex.relevance_score": get_value(procedure, "score") or 0.0,
        "howdex.source_episode_count": len(source_episode_ids),
    }
