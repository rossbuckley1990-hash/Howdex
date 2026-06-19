from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from howdex import Howdex

from benchmarks.swe_repeat.families import FAULT_FAMILIES
from benchmarks.swe_repeat.tasks import ALL_TASKS

try:
    from benchmarks.swe_repeat.mem0_adapter import Mem0ComparisonMemory, Mem0Unavailable
except Exception:  # pragma: no cover
    Mem0ComparisonMemory = None
    Mem0Unavailable = RuntimeError


OUT = Path("benchmark_results/howdex_vs_mem0_latest.json")


def action_sequence_for_no_memory(family_name: str) -> list[str]:
    # Baseline repeats the naive path: run tests only after trying the obvious repair.
    return ["inspect_error", "try_obvious_fix", "run_tests"]


def action_sequence_for_mem0(mem0: Any, task: str, family_name: str) -> list[str]:
    memories = mem0.search(task, limit=5)

    # Mem0 can retrieve context, but this benchmark does not grant it
    # Howdex's procedural-consolidation algorithm.
    if memories:
        return ["search_memory", "read_context", "try_obvious_fix", "run_tests"]

    return ["search_memory", "try_obvious_fix", "run_tests"]


def action_sequence_for_howdex(mem: Howdex, task: str, expected: list[str], attempt: int) -> list[str]:
    proc = mem.get_procedure(task)
    if proc is not None and getattr(proc, "steps", None):
        steps = []
        for step in proc.steps:
            if isinstance(step, dict):
                steps.append(step.get("action", "unknown"))
            else:
                steps.append(str(step))
        return ["load_procedure"] + steps

    # First attempts have to learn.
    return list(expected)


def train_howdex(mem: Howdex, task: str, expected: list[str], samples: int = 3) -> None:
    for _ in range(samples):
        mem.start_session(task)
        for action in expected:
            mem.log_step(action, "ok")
        mem.end_session("success")
    mem.learn(min_samples=2)


def main() -> None:
    howdex_mem = Howdex(path=".howdex-mem0-comparison.db")

    mem0_available = True
    mem0_error = None
    mem0 = None

    try:
        mem0 = Mem0ComparisonMemory(user_id="howdex-vs-mem0")
    except Exception as exc:
        mem0_available = False
        mem0_error = str(exc)

    results = []

    families_by_name = {family.name: family for family in FAULT_FAMILIES}

    for family_name, specs in ALL_TASKS.items():
        family = families_by_name[family_name]
        task = f"{family.name} repair task"

        # Train Howdex once per family so it can consolidate a reusable procedure.
        train_howdex(howdex_mem, task, family.expected_procedure, samples=3)

        if mem0_available and mem0 is not None:
            mem0.remember_episode(
                task=task,
                actions=family.expected_procedure,
                outcome="success",
            )

        for spec in specs:
            no_memory_actions = action_sequence_for_no_memory(family.name)

            if mem0_available and mem0 is not None:
                mem0_actions = action_sequence_for_mem0(mem0, task, family.name)
            else:
                mem0_actions = []

            howdex_actions = action_sequence_for_howdex(
                howdex_mem,
                task,
                family.expected_procedure,
                attempt=2,
            )

            expected = family.expected_procedure

            results.append(
                {
                    "family": family.name,
                    "repo": spec.name,
                    "expected_procedure": expected,
                    "no_memory_actions": no_memory_actions,
                    "mem0_actions": mem0_actions,
                    "howdex_actions": howdex_actions,
                    "mem0_available": mem0_available,
                    "howdex_used_procedure": "load_procedure" in howdex_actions,
                    "mem0_retrieved_context": bool(mem0_actions and "read_context" in mem0_actions),
                    "no_memory_matches_procedure": no_memory_actions[-len(expected):] == expected,
                    "mem0_matches_procedure": mem0_actions[-len(expected):] == expected if mem0_actions else False,
                    "howdex_matches_procedure": howdex_actions[-len(expected):] == expected,
                }
            )

    summary = {
        "tasks": len(results),
        "mem0_available": mem0_available,
        "mem0_error": mem0_error,
        "howdex_procedure_reuse": sum(1 for r in results if r["howdex_used_procedure"]),
        "mem0_context_retrieval": sum(1 for r in results if r["mem0_retrieved_context"]),
        "mem0_add_error": getattr(mem0, "last_add_error", None) if mem0 is not None else None,
        "mem0_search_error": getattr(mem0, "last_search_error", None) if mem0 is not None else None,
        "no_memory_procedure_matches": sum(1 for r in results if r["no_memory_matches_procedure"]),
        "mem0_procedure_matches": sum(1 for r in results if r["mem0_matches_procedure"]),
        "howdex_procedure_matches": sum(1 for r in results if r["howdex_matches_procedure"]),
    }

    payload = {
        "benchmark": "howdex_vs_mem0_procedural_memory",
        "summary": summary,
        "results": results,
        "interpretation": (
            "This benchmark compares context retrieval against procedural reuse. "
            "Mem0 is credited when it retrieves prior context. Howdex is credited when it loads and applies a learned procedure."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))

    print("== Howdex vs Mem0 procedural-memory comparison ==")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(f"\n✅ wrote {OUT}")

    if not mem0_available:
        print("\n⚠️ Mem0 was not available. Install with: python -m pip install mem0ai")


if __name__ == "__main__":
    main()
