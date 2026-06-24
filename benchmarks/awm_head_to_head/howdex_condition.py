"""Howdex condition for the AWM-style head-to-head harness."""

from __future__ import annotations

from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance

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


def build_memory(task: BenchmarkTask) -> tuple[Howdex, str]:
    """Create a deterministic receipt-backed Howdex procedure."""
    memory = Howdex(path=":memory:", embedder="hashing")
    memory.start_session(task.objective, source="awm_head_to_head")
    for step in task.canonical_solution_steps:
        memory.log_step(step, "successful dry-run trace evidence")
    episode = memory.end_session("success")
    procedures = memory.learn(min_samples=1)
    if not procedures:
        raise RuntimeError("Howdex did not learn a procedure for dry-run task")
    procedure = procedures[0]
    memory.verify_procedure(
        procedure.id,
        verifier_type="dry_run_verifier",
        verifier_command="deterministic local verifier",
        expected_signal=task.verifier_signal,
        observed_signal=task.verifier_signal,
        exit_code=0,
        source_episode_id=episode.session_id,
        environment_fingerprint={
            "benchmark": "awm_head_to_head",
            "task": task.task_id,
        },
    )
    return memory, procedure.id


def render_prompt(task: BenchmarkTask) -> tuple[str, str, Howdex]:
    memory, _procedure_id = build_memory(task)
    suggestions = memory.suggest_procedure(task.objective, top_k=1, min_confidence=0.0)
    guidance = render_procedure_guidance(suggestions, max_chars=4000)
    return base_prompt_for(task), guidance, memory


def run_dry(task: BenchmarkTask, *, trials: int) -> ConditionResult:
    base_prompt, guidance, memory = render_prompt(task)
    try:
        procedures = memory.list_procedures()
        receipts = sum(len(procedure.receipts) for procedure in procedures)
        successes = max(0, round(trials * 0.8))
        attempts = [3 if index < successes else 6 for index in range(trials)]
        return ConditionResult(
            condition="howdex",
            task=task.task_id,
            trials=trials,
            successes=successes,
            success_rate=success_rate(successes, trials),
            avg_attempts=average_attempts(attempts),
            extraction_cost=0.0,
            guidance_chars=len(guidance),
            source_leakage=source_leakage_score(
                guidance,
                task.source_artifact_markers,
            ),
            auditability_score=auditability_score(
                has_structured_steps=True,
                has_trace_provenance=bool(procedures and procedures[0].source_episode_ids),
                has_receipt=receipts > 0,
            ),
            verification_coverage=verification_coverage(receipts, max(1, len(procedures))),
            calibration_coverage=calibration_coverage(len(procedures), max(1, len(procedures))),
            portability_score=portability_score(
                json_exportable=True,
                receipt_backed=receipts > 0,
                framework_neutral=True,
            ),
            base_prompt_sha256=sha256_text(base_prompt),
            memory_strategy="howdex_deterministic_verified_procedure_guidance",
            verdict="DRY-RUN HOWDEX CONDITION",
            notes=(
                "Uses real local Howdex extraction and receipt attachment, but "
                "dry-run success values are synthetic harness checks."
            ),
        )
    finally:
        memory.close()
