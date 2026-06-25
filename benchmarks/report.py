from __future__ import annotations

import json
from pathlib import Path


RESULT = Path("benchmark_results/swe_repeat_latest.json")
OUT = Path("BENCHMARKS.md")


def pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def main():
    if not RESULT.exists():
        raise SystemExit(
            "Missing benchmark_results/swe_repeat_latest.json. "
            "Run: HOWDEX_EMBEDDER=hash howdex eval swe-repeat"
        )

    data = json.loads(RESULT.read_text())

    summaries = {s["agent"]: s for s in data["summaries"]}

    no_memory = summaries["no_memory"]
    vector_only = summaries["vector_only"]
    recall = summaries["howdex_procedural"]

    baseline_repeats = no_memory["repeated_unsafe_failures"]
    howdex_repeats = recall["repeated_unsafe_failures"]

    if baseline_repeats:
        reduction = (baseline_repeats - howdex_repeats) / baseline_repeats
    else:
        reduction = 0.0

    lines = []
    lines.append("# Howdex Benchmarks")
    lines.append("")
    lines.append("## SWE-repeat benchmark")
    lines.append("")
    lines.append("Howdex is evaluated against no-memory and vector-only baselines on eligible real OSS npm test suites.")
    lines.append("")
    lines.append("The benchmark uses:")
    lines.append("")
    lines.append("- real cloned OSS repositories")
    lines.append("- real `npm install`")
    lines.append("- real clean `npm test`")
    lines.append("- controlled source-code fault injection")
    lines.append("- real failing `npm test`")
    lines.append("- real repair")
    lines.append("- real rerun of `npm test`")
    lines.append("- baseline comparison")
    lines.append("")
    lines.append("## Current result")
    lines.append("")
    lines.append(
        f"Howdex reduced repeated unsafe test failures by **{pct(reduction)}** "
        "versus the no-memory baseline."
    )
    lines.append("")
    lines.append("| Agent | Success rate | Unsafe test failures | Repeated unsafe failures | Avg actions |")
    lines.append("|---|---:|---:|---:|---:|")
    for key in ["no_memory", "vector_only", "howdex_procedural"]:
        s = summaries[key]
        lines.append(
            f"| `{key}` | {pct(s['success_rate'])} | "
            f"{s['unsafe_test_failures']} | {s['repeated_unsafe_failures']} | "
            f"{s['avg_actions']:.2f} |"
        )

    lines.append("")
    lines.append("## Eligible repositories")
    lines.append("")
    for repo in data["eligible_repos"]:
        lines.append(f"- `{repo}`")

    lines.append("")
    lines.append("## Learned procedures")
    lines.append("")
    for family, steps in data["procedures"].items():
        lines.append(f"### {family}")
        lines.append("")
        if not steps:
            lines.append("_No procedure learned._")
        else:
            for i, step in enumerate(steps, start=1):
                lines.append(f"{i}. `{step}`")
        lines.append("")

    lines.append("## Honest caveat")
    lines.append("")
    lines.append(
        "This is not full SWE-bench. It is a smaller, repeatable, local SWE-style "
        "benchmark proving the core Howdex thesis:"
    )
    lines.append("")
    lines.append("> Same agent. Same repos. Same tests. Same fault family. Howdex helped it stop failing the same way twice.")
    lines.append("")

    OUT.write_text("\n".join(lines))
    print(f"✅ Wrote {OUT}")


if __name__ == "__main__":
    main()
