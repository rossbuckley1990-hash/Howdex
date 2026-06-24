"""Compatibility wrapper for the procedure trust calibration benchmark."""

from benchmarks.trust_calibration.procedure_trust_calibration_test import *  # noqa: F403
from benchmarks.trust_calibration.procedure_trust_calibration_test import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
