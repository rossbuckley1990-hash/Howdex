"""Deterministic procedure feedback calculations."""

from __future__ import annotations


def procedure_success_rate(
    success_count: int,
    support_count: int,
) -> float:
    """Return the verified success fraction."""
    if support_count <= 0:
        return 0.0
    return round(success_count / support_count, 4)


def procedure_feedback_confidence(
    *,
    base_confidence: float,
    success_count: int,
    support_count: int,
) -> float:
    """Blend extraction confidence with verified outcomes deterministically.

    The original extraction confidence remains 40% of the signal. Verified
    success rate contributes 45%, while evidence volume contributes 15% and
    saturates after five verified examples.
    """
    base = _bounded(base_confidence)
    if support_count <= 0:
        return round(base, 4)
    success_rate = success_count / support_count
    evidence_volume = min(1.0, support_count / 5.0)
    return round(
        (0.40 * base)
        + (0.45 * success_rate)
        + (0.15 * evidence_volume),
        4,
    )


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
