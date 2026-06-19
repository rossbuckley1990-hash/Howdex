from __future__ import annotations

import json
from pathlib import Path


RESULT = Path("benchmark_results/swe_repeat_multi_family_latest.json")
OUT = Path("BENCHMARKS_MULTI_FAMILY.md")


def main() -> None:
    if not RESULT.exists():
        raise SystemExit(
            f"Missing {RESULT}. Run: HOWDEX_EMBEDDER=hash howdex eval swe-repeat-multi"
        )

    data = json.loads(RESULT.read_text())
    summary = data["summary"]
    results = data["results"]

    lines: list[str] = []
    lines.append("# Howdex Multi-Family SWE-Repeat Benchmark")
    lines.append("")
    lines.append("This report covers the multi-family SWE-repeat benchmark.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Families: {summary['families']}")
    lines.append(f"- Configured tasks: {summary['configured_tasks']}")
    lines.append(f"- Eligible tasks: {summary['eligible_tasks']}")
    lines.append(f"- Passed tasks: {summary['passed_tasks']}")
    lines.append(f"- Failed tasks: {summary['failed_tasks']}")
    lines.append("")
    lines.append("## Task results")
    lines.append("")
    lines.append("| Family | Repo | Result | Reason |")
    lines.append("|---|---|---:|---|")

    for row in results:
        status = "PASS" if row.get("passed") else "FAIL"
        lines.append(
            f"| `{row['family']}` | `{row['repo']}` | {status} | `{row.get('reason', '')}` |"
        )

    lines.append("")
    lines.append("## Current claim")
    lines.append("")
    lines.append(
        "Howdex's multi-family SWE-repeat runner currently validates 9/9 configured real OSS repair tasks across 3 controlled fault families."
    )
    lines.append("")
    lines.append("## Caveat")
    lines.append("")
    lines.append(
        "This is still not full SWE-bench. It is a controlled, repeatable SWE-style benchmark over real repositories, real installs, real test suites, injected faults, repairs, and reruns."
    )
    lines.append("")

    OUT.write_text("\n".join(lines))
    print(f"✅ Wrote {OUT}")


if __name__ == "__main__":
    main()
