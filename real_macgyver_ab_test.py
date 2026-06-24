"""Compatibility wrapper for the real MacGyver A/B benchmark."""

from benchmarks.macgyver.real_macgyver_ab_test import *  # noqa: F403
from benchmarks.macgyver.real_macgyver_ab_test import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
