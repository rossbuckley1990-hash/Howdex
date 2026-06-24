"""Runner for the Howdex vs local AWM-style head-to-head harness."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Iterable

from . import awm_baseline, howdex_condition, vanilla_condition
from .metrics import ConditionResult, ensure_comparable_schema, machine_summary
from .tasks import get_task


def run_dry(*, task_name: str = "docker", trials: int = 5) -> list[ConditionResult]:
    task = get_task(task_name)
    rows = [
        vanilla_condition.run_dry(task, trials=trials),
        awm_baseline.run_dry(task, trials=trials),
        howdex_condition.run_dry(task, trials=trials),
    ]
    enforce_identical_base_framing(rows)
    ensure_comparable_schema(rows)
    return rows


def run_live_local(*, task_name: str = "docker", trials: int = 20) -> dict:
    """Return an honest live-local placeholder without fabricating results.

    The existing Docker A/B benchmark can be wired here later. Until a real AWM
    implementation and deterministic live evaluator are integrated, this mode
    reports SKIP rather than producing fake live numbers.
    """
    task = get_task(task_name)
    return {
        "benchmark": "awm_head_to_head",
        "mode": "live-local",
        "task": task.task_id,
        "trials": trials,
        "verdict": "SKIP",
        "reason": (
            "Live-local AWM head-to-head requires a real AWM baseline or an "
            "explicit local evaluator integration. No live result fabricated."
        ),
    }


def enforce_identical_base_framing(rows: Iterable[ConditionResult]) -> None:
    hashes = {row.base_prompt_sha256 for row in rows}
    if len(hashes) != 1:
        raise ValueError("base prompt framing differs across conditions")


def format_table(rows: list[ConditionResult]) -> str:
    lines = [
        (
            "condition | trials | successes | success_rate | avg_attempts | "
            "extraction_cost | guidance_chars | source_leakage | "
            "auditability_score | verification_coverage | "
            "calibration_coverage | portability_score | verdict"
        )
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    row.condition,
                    str(row.trials),
                    str(row.successes),
                    f"{row.success_rate:.2f}",
                    f"{row.avg_attempts:.2f}",
                    f"{row.extraction_cost:.2f}",
                    str(row.guidance_chars),
                    str(row.source_leakage),
                    f"{row.auditability_score:.2f}",
                    f"{row.verification_coverage:.2f}",
                    f"{row.calibration_coverage:.2f}",
                    f"{row.portability_score:.2f}",
                    row.verdict,
                ]
            )
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Howdex against vanilla and local AWM-style workflow memory."
    )
    parser.add_argument("--task", default="docker", help="task family; default docker")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-local", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.live_local and not args.dry_run:
        payload = run_live_local(task_name=args.task, trials=args.trials)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    rows = run_dry(task_name=args.task, trials=args.trials)
    print(format_table(rows))
    print()
    print(json.dumps(machine_summary(rows, mode="dry-run"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
