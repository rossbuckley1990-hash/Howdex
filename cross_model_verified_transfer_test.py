"""Compatibility wrapper for the cross-model verified transfer benchmark."""

from benchmarks.transfer.cross_model_verified_transfer_test import *  # noqa: F403
from benchmarks.transfer.cross_model_verified_transfer_test import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
