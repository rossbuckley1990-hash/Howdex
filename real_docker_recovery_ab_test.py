"""Compatibility wrapper for the Docker recovery A/B benchmark."""

from benchmarks.docker_recovery.real_docker_recovery_ab_test import *  # noqa: F403
from benchmarks.docker_recovery.real_docker_recovery_ab_test import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
