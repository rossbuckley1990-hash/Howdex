"""Deterministic task fixtures for the AWM-style head-to-head harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    family: str
    objective: str
    base_prompt: str
    verifier_signal: str
    canonical_solution_steps: tuple[str, ...]
    source_artifact_markers: tuple[str, ...] = ()


DOCKER_DRY_TASK = BenchmarkTask(
    task_id="docker-health-config-mismatch",
    family="docker",
    objective="Recover a Docker Compose service whose /health endpoint fails after a config mismatch.",
    base_prompt=(
        "You are in a fresh local sandbox. Recover the Docker Compose service "
        "until a real /health verifier reports HTTP 200 healthy. You may inspect "
        "docker-compose.yml, runtime.env, health-policy.conf, and logs. Do not "
        "claim success before verification."
    ),
    verifier_signal="HTTP 200 healthy",
    canonical_solution_steps=(
        "inspect docker-compose.yml",
        "inspect runtime.env",
        "inspect health-policy.conf",
        "update runtime.env so HEALTH_MODE matches health-policy.conf",
        "run docker compose up -d --build --force-recreate",
        "verify curl /health returns HTTP 200 healthy",
    ),
    source_artifact_markers=(
        "FROM python:3.12-alpine",
        "class Handler",
        "def required_mode",
    ),
)


TASKS = {
    "docker": DOCKER_DRY_TASK,
}


def get_task(name: str) -> BenchmarkTask:
    try:
        return TASKS[name]
    except KeyError as exc:
        raise ValueError(f"unknown AWM head-to-head task: {name}") from exc


def base_prompt_for(task: BenchmarkTask) -> str:
    """Return the identical non-memory prompt shared by every condition."""
    return task.base_prompt
