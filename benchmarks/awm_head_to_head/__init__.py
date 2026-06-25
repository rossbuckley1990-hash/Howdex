"""AWM-style head-to-head benchmark harness for Howdex.

This package provides a local, deterministic comparison harness. It does not
claim that Howdex beats AWM. The ``awm_style`` condition is a clearly labelled
local approximation unless a real AWM implementation is integrated later.
"""

__all__ = [
    "awm_baseline",
    "howdex_condition",
    "metrics",
    "runner",
    "tasks",
    "vanilla_condition",
]
