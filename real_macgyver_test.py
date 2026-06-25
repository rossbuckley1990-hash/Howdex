"""Compatibility wrapper for the real MacGyver filesystem benchmark."""

from benchmarks.macgyver.real_macgyver_test import *  # noqa: F403
from benchmarks.macgyver.real_macgyver_test import (
    run_real_macgyver_benchmark as _main,
)


if __name__ == "__main__":
    _main()
