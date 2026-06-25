"""Compatibility wrapper for the Docker compounding-curve benchmark."""

from benchmarks.docker_recovery.docker_compounding_curve_test import *  # noqa: F403
from benchmarks.docker_recovery.docker_compounding_curve_test import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
