"""Tests for the failed_attempts negation heuristic.

A step whose observation mentions failure markers only as part of a
zero-count (e.g. "parsed 6/6 dates, 0 failed") is NOT a failed attempt —
it's a successful step reporting that zero sub-operations failed.
"""

from howdex.core.guidance_artifacts import _is_failure_marker_negated


def test_zero_failed_is_negated():
    assert _is_failure_marker_negated("parsed 6/6 dates, 0 failed")


def test_zero_errors_is_negated():
    assert _is_failure_marker_negated("0 errors, 0 warnings")


def test_zero_failures_is_negated():
    assert _is_failure_marker_negated("no failures detected")


def test_no_errors_is_negated():
    assert _is_failure_marker_negated("completed with no errors")


def test_failed_equals_zero_is_negated():
    assert _is_failure_marker_negated("exit=0 :: failed=0, errors=0")


def test_one_failed_is_not_negated():
    """A real failure count like '1 failed' should NOT be negated."""
    assert not _is_failure_marker_negated("1 failed, 5 passed")


def test_fatal_error_is_not_negated():
    assert not _is_failure_marker_negated("fatal: database is locked")


def test_importerror_is_not_negated():
    assert not _is_failure_marker_negated("ImportError: no module named foo")


def test_clean_observation_is_not_negated():
    """Observations with no failure markers at all return False."""
    assert not _is_failure_marker_negated("ok: 2 rows")
    assert not _is_failure_marker_negated("wrote 1024 bytes")


def test_failed_attempts_skips_zero_count_observations():
    """End-to-end: a procedure whose example step has observation
    'parsed 6/6 dates, 0 failed' should NOT appear in failed_attempts()."""
    from howdex.core.guidance_artifacts import failed_attempts

    procedure = {
        "raw_supporting_examples": [
            {
                "episode_id": "ep1",
                "outcome": "success",
                "steps": [
                    {
                        "action": "normalize_dates",
                        "tool_name": "normalize_dates",
                        "observation": "parsed 6/6 dates, 0 failed",
                    },
                    {
                        "action": "execute_command",
                        "tool_name": "execute_command",
                        "tool_args": {"cmd": "npm install missing-pkg"},
                        "observation": "Error: Cannot find module missing-pkg",
                    },
                ],
            }
        ],
    }
    failed = failed_attempts(procedure)
    # The real failure (npm install missing-pkg) should be captured.
    assert any("npm install missing-pkg" in f for f in failed), failed
    # The success summary ("0 failed") should NOT be captured.
    assert not any("normalize_dates" in f for f in failed), failed
