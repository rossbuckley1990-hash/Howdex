"""Vanilla no-memory condition for the AWM head-to-head harness."""

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


def render_prompt(task: BenchmarkTask) -> tuple[str, str]:
    """Return identical base framing and no memory guidance."""
    base_prompt = base_prompt_for(task)
    memory = "No prior workflow memory is available."
    return base_prompt, memory


def run_dry(task: BenchmarkTask, *, trials: int) -> ConditionResult:
    base_prompt, memory = render_prompt(task)
    # Deterministic local dry-run model: no memory sometimes succeeds, but
    # requires more attempts and has no extraction/auditability signal.
    successes = max(0, trials // 3)
    attempts = [6 if index < successes else 8 for index in range(trials)]
    return ConditionResult(
        condition="vanilla",
        task=task.task_id,
        trials=trials,
        successes=successes,
        success_rate=success_rate(successes, trials),
        avg_attempts=average_attempts(attempts),
        extraction_cost=0.0,
        guidance_chars=len(memory),
        source_leakage=source_leakage_score(memory, task.source_artifact_markers),
        auditability_score=auditability_score(
            has_structured_steps=False,
            has_trace_provenance=False,
            has_receipt=False,
        ),
        verification_coverage=verification_coverage(0, trials),
        calibration_coverage=calibration_coverage(0, trials),
        portability_score=portability_score(
            json_exportable=False,
            receipt_backed=False,
            framework_neutral=False,
        ),
        base_prompt_sha256=sha256_text(base_prompt),
        memory_strategy="none",
        verdict="DRY-RUN BASELINE",
        notes="No memory condition; used only for comparable harness output.",
    )
