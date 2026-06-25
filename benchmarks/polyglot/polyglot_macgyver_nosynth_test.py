"""
Polyglot MacGyver No-Synthesis Benchmark

Question:
    Can Howdex transfer a Python-discovered decryption procedure into Bash-only
    execution using learned procedure memory alone?

Memory path:
    teacher run -> memory.learn() -> memory.suggest_procedure()
    -> render_agent_guidance() -> treatment prompt

This benchmark intentionally performs no source scanning, fact synthesis, or
benchmark-specific extraction from the teacher's decoder implementation.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from howdex import Howdex
from howdex.core.guidance import render_agent_guidance

DB_PATH = ".howdex_polyglot_nosynth.db"
TEACHER_MODEL = os.getenv(
    "HOWDEX_POLY_NOSYNTH_TEACHER_MODEL",
    "gpt-4o",
)
STUDENT_MODEL = os.getenv(
    "HOWDEX_POLY_NOSYNTH_STUDENT_MODEL",
    "gpt-4o-mini",
)
N_TRIALS = int(os.getenv("HOWDEX_POLY_NOSYNTH_TRIALS", "5"))
MAX_TURNS = int(os.getenv("HOWDEX_POLY_NOSYNTH_MAX_TURNS", "15"))


@dataclass
class AgentResult:
    label: str
    success: bool
    attempts: int
    actions: list[tuple[str, str]]
    used_memory: bool
    source_pasted: bool


def _shared_benchmark():
    """Load the existing harness only after credentials are validated."""
    return importlib.import_module("polyglot_macgyver_test")


def reset_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(DB_PATH + suffix)
        if path.exists():
            path.unlink()


def source_pasted_in_guidance(guidance: str) -> bool:
    """Detect Python source leakage in native treatment guidance."""
    patterns = (
        r"```",
        r"(?m)^\s*(?:from\s+\S+\s+import\s+|import\s+\S+)",
        r"(?m)^\s*(?:async\s+)?def\s+\w+\s*\(",
        r"(?m)^\s*class\s+\w+",
        r"(?m)^\s*#!.*python",
        r"\bhashlib\.",
        r"\bsubprocess(?:\.|\s+import\b)",
        r"\bseed\s*\[\s*::\s*-1\s*\]",
    )
    return any(re.search(pattern, guidance) for pattern in patterns)


def native_procedure_guidance(
    memory: Howdex,
) -> tuple[str, bool, bool]:
    """Retrieve procedures and render them without benchmark-side synthesis."""
    suggestions = memory.suggest_procedure(
        "Decrypt vault.enc and reveal the hidden TARGET string.",
        top_k=3,
        min_confidence=0.0,
    )
    guidance = render_agent_guidance(
        suggestions,
        objective="Decrypt vault.enc and reveal the hidden TARGET string.",
        constraints=[
            "Python is unavailable.",
            "Use Bash tools only.",
            "Do not paste or reconstruct Python source code.",
            "Do not claim completion until the real verifier reports SUCCESS.",
        ],
        target_environment="Bash-only student sandbox",
        include_source=False,
        include_failed_attempts=True,
        include_verification=True,
    )
    return (
        guidance,
        bool(suggestions),
        source_pasted_in_guidance(guidance),
    )


def run_treatment_agent(
    *,
    label: str,
    workdir: Path,
    expected_target: str,
    memory: Howdex,
) -> AgentResult:
    """Run the Bash-only treatment with native procedure guidance only."""
    shared = _shared_benchmark()
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    guidance, used_memory, source_pasted = native_procedure_guidance(memory)
    print("\n[HOWDEX NO-SYNTHESIS MEMORY]")
    print(guidance)
    print(f"[HOWDEX MEMORY AVAILABLE]: {used_memory}")
    print(f"[HOWDEX SOURCE PASTED]: {source_pasted}")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_bash",
                "description": "Run an allowed command in the sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                    "required": ["cmd"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_fs_write",
                "description": "Write an allowed file in the sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file_path", "content"],
                },
            },
        },
    ]
    task_prompt = f"""
You are the treatment student. Python is banned.

Objective:
Decrypt vault.enc and reveal the hidden TARGET string.

Rules:
- You may not write or run Python.
- Use local Bash tools only.
- Use Howdex operational memory if it is relevant.
- Do not claim DONE until the real verifier reports SUCCESS.
- No password-derivation algorithm is supplied outside Howdex memory.

{guidance}
"""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": task_prompt}
    ]
    attempts = 0
    actions: list[tuple[str, str]] = []
    success = False

    for _turn in range(MAX_TURNS):
        response = shared.client.chat.completions.create(
            model=STUDENT_MODEL,
            messages=messages,
            tools=tools,
            temperature=0.7,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content and "DONE" in message.content.upper():
            if success:
                print("[DONE accepted]")
                break
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "DONE rejected. You must receive SUCCESS from the "
                        "verifier first."
                    ),
                }
            )
            continue

        if not message.tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Continue using tool calls until the real verifier "
                        "reports SUCCESS."
                    ),
                }
            )
            continue

        for tool_call in message.tool_calls:
            arguments = json.loads(tool_call.function.arguments)
            if tool_call.function.name == "execute_bash":
                attempts += 1
                output = shared.execute_bash(
                    workdir,
                    arguments["cmd"],
                    False,
                    expected_target,
                )
                actions.append(("bash", arguments["cmd"]))
                if f"SUCCESS: decrypted {expected_target}" in output:
                    success = True
            elif tool_call.function.name == "execute_fs_write":
                output = shared.execute_fs_write(
                    workdir,
                    arguments["file_path"],
                    arguments["content"],
                    False,
                )
                actions.append(("fs_write", arguments["file_path"]))
            else:
                output = "FATAL: unknown tool"

            print(f"[OUTPUT] {output[:500]}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": (
                        output
                        if len(output) <= 1000
                        else output[:1000] + "\n...[truncated]"
                    ),
                }
            )
        if success:
            print("[VERIFIER SUCCESS — stopping agent loop]")
            break

    return AgentResult(
        label=label,
        success=success,
        attempts=attempts,
        actions=actions,
        used_memory=used_memory,
        source_pasted=source_pasted,
    )


def run_benchmark() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required.")
    shared = _shared_benchmark()
    shared.MAX_TURNS = MAX_TURNS
    if not shared.openssl_available():
        raise SystemExit("openssl is required.")

    reset_db()
    memory = Howdex(path=DB_PATH, embedder="hashing")
    teacher_sandbox = shared.create_crypto_challenge(
        "howdex_poly_nosynth_teacher_",
        seed="alpha_tango_99",
        target="TARGET:OMEGA_PROTOCOL",
    )
    try:
        teacher = shared.run_agent(
            label="TEACHER — PYTHON CRYPTO DISCOVERY",
            workdir=teacher_sandbox,
            expected_target="TARGET:OMEGA_PROTOCOL",
            memory=memory,
            record_to_memory=True,
            use_memory=False,
            allow_python=True,
            model=TEACHER_MODEL,
            temperature=0.2,
        )
        print("\n[HOWDEX LEARN]")
        procedures = memory.learn(min_samples=1)
        print(f"learned_procedures={len(procedures)}")
        for procedure in procedures:
            print(
                f"- {procedure.task_signature} "
                f"confidence={procedure.confidence}"
            )
    finally:
        shutil.rmtree(teacher_sandbox, ignore_errors=True)

    if not teacher.success:
        print("\nPOLYGLOT MACGYVER NO-SYNTHESIS BENCHMARK")
        print("teacher_success=false")
        print("verdict=FAIL — no defensible no-synthesis claim.")
        return

    control_results: list[AgentResult] = []
    treatment_results: list[AgentResult] = []
    for trial in range(1, N_TRIALS + 1):
        seed = f"bravo_delta_{trial}_77"
        target = f"TARGET:POLYGLOT_NOSYNTH_{trial}"

        control_sandbox = shared.create_crypto_challenge(
            f"howdex_poly_nosynth_control_{trial}_",
            seed=seed,
            target=target,
        )
        try:
            control_results.append(
                shared.run_agent(
                    label=(
                        f"CONTROL — BASH ONLY NO MEMORY "
                        f"{trial}/{N_TRIALS}"
                    ),
                    workdir=control_sandbox,
                    expected_target=target,
                    memory=memory,
                    record_to_memory=False,
                    use_memory=False,
                    allow_python=False,
                    model=STUDENT_MODEL,
                    temperature=0.7,
                )
            )
        finally:
            shutil.rmtree(control_sandbox, ignore_errors=True)

        treatment_sandbox = shared.create_crypto_challenge(
            f"howdex_poly_nosynth_treatment_{trial}_",
            seed=seed,
            target=target,
        )
        try:
            treatment_results.append(
                run_treatment_agent(
                    label=(
                        f"TREATMENT — BASH ONLY NATIVE HOWDEX "
                        f"{trial}/{N_TRIALS}"
                    ),
                    workdir=treatment_sandbox,
                    expected_target=target,
                    memory=memory,
                )
            )
        finally:
            shutil.rmtree(treatment_sandbox, ignore_errors=True)

    control = shared.summarize(control_results)
    treatment = shared.summarize(treatment_results)
    delta = treatment["success_rate"] - control["success_rate"]
    qualifies = (
        treatment["success_rate"] > control["success_rate"]
        and treatment["success_rate"] >= 0.40
        and treatment["source_pasted"] == 0
        and treatment["memory_used"] == treatment["trials"]
    )
    strong_pass = qualifies and treatment["success_rate"] >= 0.80
    verdict = (
        "STRONG PASS — no-synthesis operational transfer."
        if strong_pass
        else (
            "PARTIAL PASS — no-synthesis signal detected."
            if qualifies
            else "FAIL — no defensible no-synthesis claim."
        )
    )

    print("\n" + "=" * 80)
    print("POLYGLOT MACGYVER NO-SYNTHESIS BENCHMARK")
    print("=" * 80)
    print("\nTeacher:")
    print(f"  success: {teacher.success}")
    print(f"  attempts: {teacher.attempts}")
    print("\nControl:")
    print(f"  trials: {control['trials']}")
    print(f"  successes: {control['successes']}")
    print(f"  success_rate: {control['success_rate']:.2f}")
    print(f"  avg_attempts: {control['avg_attempts']:.2f}")
    print("\nTreatment:")
    print(f"  trials: {treatment['trials']}")
    print(f"  successes: {treatment['successes']}")
    print(f"  success_rate: {treatment['success_rate']:.2f}")
    print(f"  avg_attempts: {treatment['avg_attempts']:.2f}")
    print(
        "  howdex_memory_used: "
        f"{treatment['memory_used']}/{treatment['trials']}"
    )
    print(
        f"  source_pasted: "
        f"{treatment['source_pasted']}/{treatment['trials']}"
    )
    print("\nDelta:")
    print(f"  success_rate_lift: {delta:+.2f}")
    print("\nVerdict:")
    print(f"  {verdict}")
    print("\nMachine summary:")
    print(
        json.dumps(
            {
                "teacher_success": teacher.success,
                "control": control,
                "treatment": treatment,
                "success_rate_lift": delta,
                "strong_pass": strong_pass,
                "pass": qualifies,
                "verdict": verdict,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    run_benchmark()
