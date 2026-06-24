"""Local AWM-style workflow-memory approximation.

This is not an official AWM implementation. It approximates the broad idea of
extracting a workflow summary from successful traces and injecting that summary
into later tasks. Integrating a real AWM implementation should replace this
module or add a fourth condition.
"""

from __future__ import annotations

from .metrics import (
    ConditionResult,
    auditability_score,
    average_attempts,
    calibration_coverage,
    portability_score,
    sha256_text,
    source_leakage_score,
    success_rate,
    verification_coverage,
)
from .tasks import BenchmarkTask, base_prompt_for


def extract_workflow_summary(task: BenchmarkTask) -> str:
    """Summarise successful traces as freeform workflow memory."""
    lines = [
        "Local AWM-style workflow summary approximation.",
        "This is a freeform summary extracted from a successful workflow.",
        "Suggested workflow:",
    ]
    for index, step in enumerate(task.canonical_solution_steps, start=1):
        lines.append(f"{index}. {step}")
    lines.append("Verify the health endpoint before claiming success.")
    return "\n".join(lines)


def render_prompt(task: BenchmarkTask) -> tuple[str, str]:
    return base_prompt_for(task), extract_workflow_summary(task)


def run_dry(task: BenchmarkTask, *, trials: int) -> ConditionResult:
    base_prompt, memory = render_prompt(task)
    # Deterministic local dry-run model: freeform workflow summaries help, but
    # have weaker provenance/receipt/auditability than Howdex procedures.
    successes = max(0, round(trials * 0.65))
    attempts = [4 if index < successes else 7 for index in range(trials)]
    return ConditionResult(
        condition="awm_style",
        task=task.task_id,
        trials=trials,
        successes=successes,
        success_rate=success_rate(successes, trials),
        avg_attempts=average_attempts(attempts),
        extraction_cost=1.0,
        guidance_chars=len(memory),
        source_leakage=source_leakage_score(memory, task.source_artifact_markers),
        auditability_score=auditability_score(
            has_structured_steps=False,
            has_trace_provenance=True,
            has_receipt=False,
            freeform_summary=True,
        ),
        verification_coverage=verification_coverage(0, trials),
        calibration_coverage=calibration_coverage(0, trials),
        portability_score=portability_score(
            json_exportable=False,
            receipt_backed=False,
            framework_neutral=True,
        ),
        base_prompt_sha256=sha256_text(base_prompt),
        memory_strategy="local_awm_style_workflow_summary_approximation",
        verdict="DRY-RUN APPROXIMATION",
        notes=(
            "Local AWM-style approximation only; not an official AWM result "
            "and not a victory claim."
        ),
    )
