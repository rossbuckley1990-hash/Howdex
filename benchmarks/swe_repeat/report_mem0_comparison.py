from __future__ import annotations

import json
from pathlib import Path


RESULT = Path("benchmark_results/howdex_vs_mem0_latest.json")
OUT = Path("BENCHMARKS_HOWDEX_VS_MEM0.md")


def main() -> None:
    if not RESULT.exists():
        raise SystemExit("Missing comparison result. Run: python -m benchmarks.swe_repeat.compare_mem0")

    data = json.loads(RESULT.read_text())
    summary = data["summary"]
    results = data["results"]

    lines = []
    lines.append("# Howdex vs Mem0 Procedural Memory Comparison")
    lines.append("")
    lines.append("This benchmark compares context retrieval against procedural reuse.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")

    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Family | Repo | Mem0 retrieved context | Howdex used procedure | Howdex matched procedure |")
    lines.append("|---|---|---:|---:|---:|")

    for row in results:
        lines.append(
            f"| `{row['family']}` | `{row['repo']}` | "
            f"{row['mem0_retrieved_context']} | "
            f"{row['howdex_used_procedure']} | "
            f"{row['howdex_matches_procedure']} |"
        )

    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(data["interpretation"])
    lines.append("")
    lines.append("## Caveat")
    lines.append("")
    lines.append(
        "This is a procedural-memory comparison, not a general long-term-memory benchmark. "
        "Mem0 should also be evaluated on its own strongest use cases: personalization, user preference recall, and long-session context continuity."
    )
    lines.append("")

    OUT.write_text("\n".join(lines))
    print(f"✅ Wrote {OUT}")


if __name__ == "__main__":
    main()
