"""Compatibility wrapper for the no-synthesis polyglot benchmark."""

from benchmarks.polyglot.polyglot_macgyver_nosynth_test import *  # noqa: F403
from benchmarks.polyglot.polyglot_macgyver_nosynth_test import run_benchmark as _main


if __name__ == "__main__":
    _main()
