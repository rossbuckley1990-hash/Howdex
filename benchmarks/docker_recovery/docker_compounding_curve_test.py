"""
Docker Compounding Curve Benchmark

Question:
    Does Howdex performance improve as the same Docker health-recovery task
    family accumulates more verified teacher traces?

Default mode is deterministic dry-run:
    HOWDEX_COMPOUNDING_MODE=dry-run python3 docker_compounding_curve_test.py

Live mode runs fresh Docker recovery treatment agents and requires Docker plus
OPENAI_API_KEY:
    HOWDEX_COMPOUNDING_MODE=live python3 docker_compounding_curve_test.py

The dry-run validates memory support, retrieval relevance, source-safety,
irrelevant-fact filtering, and prompt budget. It does not claim live success.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance

import real_docker_recovery_ab_test as docker_ab

DEFAULT_SUPPORT_LEVELS = (1, 5, 20)
DEFAULT_TRIALS = 10
DEFAULT_MAX_TURNS = 15
DEFAULT_MAX_CHARS = 6_000
DOCKER_QUERY = "recover broken Docker Compose HTTP health endpoint"
DOCKER_TASK = "recover broken Docker Compose HTTP service until /health is 200"
IRRELEVANT_MARKERS = (
    "SHA256",
    "trailing newline",
    "OpenSSL",
    "PBKDF2",
    "vault.enc",
    "seed.txt",
    "TARGET string",
    "challenge.zb2",
    "XOR",
)


@dataclass(frozen=True)
class CurveRow:
    support_count: int
    trials: int
    successes: int | None
    success_rate: float | None
    avg_attempts: float | None
    memory_used: int | None
    source_pasted: int
    retrieval_relevance: float
    guidance_chars: int
    verdict: str


def parse_support_levels(value: str | None) -> list[int]:
    """Parse comma-separated support levels deterministically."""
    raw = value if value is not None else ",".join(map(str, DEFAULT_SUPPORT_LEVELS))
    levels: list[int] = []
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            level = int(text)
        except ValueError as exc:
            raise ValueError(f"invalid support level: {text!r}") from exc
        if level <= 0:
            raise ValueError("support levels must be positive integers")
        levels.append(level)
    if not levels:
        raise ValueError("at least one support level is required")
    return levels


def build_verified_teacher_memory(
    support_count: int,
    *,
    path: str | Path | None = None,
) -> Howdex:
    """Build a local memory store with verified Docker teacher traces."""
    if support_count <= 0:
        raise ValueError("support_count must be positive")
    db_path: str | Path = ":memory:" if path is None else Path(path)
    memory = Howdex(path=db_path, embedder="hashing")
    for index in range(1, support_count + 1):
        _record_successful_teacher_episode(memory, index)
    procedures = memory.learn(min_samples=1)
    if not procedures:
        raise RuntimeError("Howdex failed to learn a Docker recovery procedure")
    procedure = max(
        procedures,
        key=lambda item: (
            item.support_count,
            item.confidence,
            item.task_signature,
        ),
    )
    memory.verify_procedure(
        procedure.id,
        verifier_type="http_health",
        verifier_command="curl -sS -i http://127.0.0.1:<PORT>/health",
        expected_signal="HTTP 200 body=healthy",
        observed_signal="HTTP 200 body=healthy",
        exit_code=0,
        environment_fingerprint={
            "benchmark": "docker_compounding_curve",
            "support_count": support_count,
            "docker_base_image": docker_ab.BASE_IMAGE,
        },
        artifact_hashes={},
        source_episode_id=(
            procedure.source_episode_ids[-1]
            if procedure.source_episode_ids
            else None
        ),
    )
    return memory


def render_compounding_guidance(
    memory: Howdex,
    *,
    sandbox_port: int = docker_ab.PROMPT_HASH_PORT,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[str, list[Any]]:
    """Render treatment memory while respecting a deterministic char budget."""
    suggestions = memory.suggest_procedure(
        DOCKER_QUERY,
        top_k=3,
        min_confidence=0.0,
    )
    procedure_guidance = render_procedure_guidance(
        suggestions,
        max_chars=max(1_000, max_chars - 256),
    )
    guidance = docker_ab.howdex_memory_section(procedure_guidance)
    if len(guidance) > max_chars:
        marker = "\n[Howdex compounding guidance truncated]\n"
        guidance = guidance[: max_chars - len(marker)].rstrip() + marker
    prompt = docker_ab.build_treatment_docker_prompt(
        sandbox_port,
        guidance,
    )
    return prompt.memory_section, suggestions


def retrieval_relevance(suggestions: list[Any]) -> float:
    """Return the best deterministic procedure-retrieval score."""
    if not suggestions:
        return 0.0
    try:
        return round(float(getattr(suggestions[0], "score", 0.0)), 4)
    except (TypeError, ValueError):
        return 0.0


def irrelevant_fact_count(text: str) -> int:
    """Count known non-Docker fact markers that should not contaminate guidance."""
    return sum(1 for marker in IRRELEVANT_MARKERS if marker in text)


def dry_run_condition(
    support_count: int,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> CurveRow:
    """Run the deterministic no-Docker/no-OpenAI compounding check."""
    memory = build_verified_teacher_memory(support_count)
    try:
        guidance, suggestions = render_compounding_guidance(
            memory,
            max_chars=max_chars,
        )
        learned_support = _learned_support_count(memory)
        source_pasted = int(docker_ab.source_pasted_in_guidance(guidance))
        irrelevant = irrelevant_fact_count(guidance)
        budget_ok = len(guidance) <= max_chars
        memory_ok = learned_support >= support_count
        guidance_ok = (
            ("runtime.env" in guidance or "<FILE_PATH_1>" in guidance)
            and "docker compose" in guidance
            and "/health" in guidance
        )
        verdict = (
            "DRY-RUN PASS"
            if all(
                (
                    memory_ok,
                    guidance_ok,
                    budget_ok,
                    source_pasted == 0,
                    irrelevant == 0,
                    bool(suggestions),
                )
            )
            else "DRY-RUN FAIL"
        )
        return CurveRow(
            support_count=support_count,
            trials=0,
            successes=None,
            success_rate=None,
            avg_attempts=None,
            memory_used=None,
            source_pasted=source_pasted,
            retrieval_relevance=retrieval_relevance(suggestions),
            guidance_chars=len(guidance),
            verdict=verdict,
        )
    finally:
        memory.close()


def run_dry_curve(
    support_levels: list[int],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[CurveRow]:
    """Run deterministic dry-run rows for all support levels."""
    return [
        dry_run_condition(level, max_chars=max_chars)
        for level in support_levels
    ]


def run_live_curve(
    support_levels: list[int],
    *,
    trials: int,
    max_turns: int,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[CurveRow]:
    """Run live Docker/OpenAI treatment rows for all support levels."""
    availability = docker_ab.check_docker_available()
    if not availability.available:
        raise RuntimeError(f"SKIP: {availability.reason}")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for live mode")

    client = docker_ab._openai_client()
    docker_ab.MAX_TURNS = int(max_turns)
    rows: list[CurveRow] = []
    for level in support_levels:
        memory = build_verified_teacher_memory(level)
        try:
            guidance, suggestions = render_compounding_guidance(
                memory,
                max_chars=max_chars,
            )
            results = docker_ab.run_arm(
                client=client,
                arm_name=f"TREATMENT_SUPPORT_{level}",
                memory=memory,
                use_memory=True,
                trials=trials,
            )
            summary = docker_ab.summarize(results)
            rows.append(
                CurveRow(
                    support_count=level,
                    trials=summary["trials"],
                    successes=summary["successes"],
                    success_rate=summary["success_rate"],
                    avg_attempts=summary["avg_attempts"],
                    memory_used=summary["memory_used"],
                    source_pasted=summary["source_pasted"],
                    retrieval_relevance=retrieval_relevance(suggestions),
                    guidance_chars=len(guidance),
                    verdict="MEASURED",
                )
            )
        finally:
            memory.close()
    return apply_live_verdicts(rows)


def apply_live_verdicts(rows: list[CurveRow]) -> list[CurveRow]:
    """Apply the benchmark verdict policy to measured live rows."""
    if not rows:
        return []
    ordered = sorted(rows, key=lambda row: row.support_count)
    first = ordered[0]
    last = ordered[-1]
    degraded = (
        any(row.source_pasted for row in ordered)
        or _rate(last) < _rate(first)
        or _attempts(last) > _attempts(first)
    )
    if degraded:
        verdict = "FAIL"
    elif _rate(last) >= _rate(first) + 0.10 or _attempts(last) <= _attempts(first) - 1.0:
        verdict = "STRONG PASS"
    elif _rate(last) >= _rate(first) and _attempts(last) <= _attempts(first):
        verdict = "PASS"
    else:
        verdict = "HONEST FLAT"
    return [
        CurveRow(
            **{
                **asdict(row),
                "verdict": verdict if row == last else "MEASURED",
            }
        )
        for row in rows
    ]


def format_results_table(rows: list[CurveRow]) -> str:
    """Render the required benchmark table."""
    headers = [
        "support_count",
        "trials",
        "successes",
        "success_rate",
        "avg_attempts",
        "memory_used",
        "source_pasted",
        "retrieval_relevance",
        "guidance_chars",
        "verdict",
    ]
    lines = [
        " | ".join(headers),
        " | ".join("---" for _ in headers),
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    str(row.support_count),
                    str(row.trials),
                    _format_optional_int(row.successes),
                    _format_optional_float(row.success_rate),
                    _format_optional_float(row.avg_attempts),
                    _format_optional_int(row.memory_used),
                    str(row.source_pasted),
                    f"{row.retrieval_relevance:.4f}",
                    str(row.guidance_chars),
                    row.verdict,
                ]
            )
        )
    return "\n".join(lines)


def machine_summary(rows: list[CurveRow], *, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "rows": [asdict(row) for row in rows],
        "note": (
            "dry-run validates memory/guidance quality only; it does not "
            "measure live agent success"
            if mode == "dry-run"
            else "live mode measures Docker recovery agents"
        ),
    }


def main() -> int:
    support_levels = parse_support_levels(
        os.getenv("HOWDEX_COMPOUNDING_SUPPORT_LEVELS")
    )
    trials = int(os.getenv("HOWDEX_COMPOUNDING_TRIALS", str(DEFAULT_TRIALS)))
    max_turns = int(
        os.getenv("HOWDEX_COMPOUNDING_MAX_TURNS", str(DEFAULT_MAX_TURNS))
    )
    max_chars = int(
        os.getenv("HOWDEX_COMPOUNDING_MAX_CHARS", str(DEFAULT_MAX_CHARS))
    )
    mode = os.getenv("HOWDEX_COMPOUNDING_MODE", "dry-run").strip().lower()

    print("DOCKER COMPOUNDING CURVE BENCHMARK")
    print(f"mode={mode}")
    print(f"support_levels={support_levels}")
    print(f"trials={trials}")
    print(f"max_turns={max_turns}")
    print("")

    try:
        if mode == "live":
            rows = run_live_curve(
                support_levels,
                trials=trials,
                max_turns=max_turns,
                max_chars=max_chars,
            )
        elif mode in {"dry", "dry-run", "dry_run"}:
            mode = "dry-run"
            rows = run_dry_curve(support_levels, max_chars=max_chars)
        else:
            raise ValueError(
                "HOWDEX_COMPOUNDING_MODE must be 'dry-run' or 'live'"
            )
    except RuntimeError as exc:
        message = str(exc)
        if message.startswith("SKIP:"):
            print(message)
            return 0
        print(message)
        return 2

    print(format_results_table(rows))
    print("")
    if mode == "dry-run":
        if all(row.verdict == "DRY-RUN PASS" for row in rows):
            print("Verdict: DRY RUN PASS — guidance quality checks passed; no live success claim.")
            status = 0
        else:
            print("Verdict: DRY RUN FAIL — inspect memory/guidance quality.")
            status = 1
    else:
        final = rows[-1].verdict if rows else "FAIL"
        print(f"Verdict: {final}")
        status = 0 if final in {"PASS", "STRONG PASS", "HONEST FLAT"} else 1
    print("")
    print("Machine summary:")
    print(json.dumps(machine_summary(rows, mode=mode), indent=2, sort_keys=True))
    return status


def _record_successful_teacher_episode(memory: Howdex, index: int) -> None:
    task = DOCKER_TASK
    port = 43000 + index
    memory.start_session(task)
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "cat runtime.env"},
        "APP_PORT=9000\nHEALTH_MODE=degraded",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "cat health-policy.conf"},
        "required_health_mode=ready",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "docker compose logs --tail 100 app"},
        "health rejected: mode='degraded'; inspect health policy",
        outcome="partial",
    )
    memory.log_tool_call(
        "execute_fs_write",
        {
            "file_path": "runtime.env",
            "content": "APP_PORT=8000\nHEALTH_MODE=ready\n",
        },
        "wrote runtime.env",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "docker compose up -d --build --force-recreate"},
        "container recreated",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": f"curl -sS -i http://127.0.0.1:{port}/health"},
        "SUCCESS: real health verifier passed (HTTP 200 body=healthy)",
        outcome="success",
    )
    memory.end_session("success")


def _learned_support_count(memory: Howdex) -> int:
    procedures = memory.list_procedures(min_confidence=0.0, limit=None)
    if not procedures:
        return 0
    return max(procedure.support_count for procedure in procedures)


def _rate(row: CurveRow) -> float:
    return float(row.success_rate or 0.0)


def _attempts(row: CurveRow) -> float:
    return float(row.avg_attempts if row.avg_attempts is not None else 10**9)


def _format_optional_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _format_optional_int(value: int | None) -> str:
    return "n/a" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
