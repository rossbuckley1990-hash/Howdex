from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = ROOT / "benchmarks" / "real_test_suite_benchmark.py"


def main():
    print("\n🧠 Howdex SWE-Repeat Benchmark")
    print("==============================")
    print("This runs the real failing test-suite benchmark:")
    print("- real OSS repos")
    print("- real npm install")
    print("- real clean npm test")
    print("- controlled source-code fault injection")
    print("- real failing npm test")
    print("- repair")
    print("- rerun real npm test")
    print("- no-memory vs vector-only vs Howdex procedural memory\n")

    if not BENCHMARK.exists():
        print(f"❌ Missing benchmark file: {BENCHMARK}")
        print("Create benchmarks/real_test_suite_benchmark.py first.")
        raise SystemExit(1)

    proc = subprocess.run(
        [sys.executable, str(BENCHMARK)],
        cwd=str(ROOT),
        text=True,
    )

    if proc.returncode != 0:
        print("\n❌ SWE-Repeat benchmark failed to complete.")
        raise SystemExit(proc.returncode)

    print("\n" + "=" * 100)
    print("SWE-REPEAT INTERPRETATION")
    print("=" * 100)
    print(
        """
If the benchmark above shows:

✅ howdex_success_rate_100_percent
✅ howdex_no_setup_failures
✅ howdex_beats_no_memory_repeated_test_failures
✅ howdex_beats_vector_only_repeated_test_failures
✅ howdex_learns_real_test_suite_procedures

Then the honest public claim is:

Howdex reduced repeated unsafe test failures versus no-memory and vector-only baselines
on eligible real OSS npm test suites after controlled source-code fault injection.

This is not full SWE-bench yet.

It is a smaller, repeatable, local SWE-style benchmark proving the core Howdex thesis:

Same agent.
Same repos.
Same tests.
Same fault family.
Howdex helped it stop failing the same way twice.
"""
    )


if __name__ == "__main__":
    main()
