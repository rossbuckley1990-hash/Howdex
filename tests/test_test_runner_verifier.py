"""Tests for the test-runner-aware verify_procedure behavior.

When ``verifier_command`` is a recognized test runner (pytest, jest, etc.)
and ``exit_code == 0``, the receipt is marked ``verified`` even if the
expected signal is not a substring of the observed signal. This handles
the common case where ``pytest -q`` produces tail output like
``[100%]`` with no "passed" string, but the test suite genuinely passed.
"""

import pytest

from howdex import Howdex
from howdex.core.engine import _is_test_runner_command


# ---------------------------------------------------------------- #
# _is_test_runner_command
# ---------------------------------------------------------------- #
@pytest.mark.parametrize("command,expected", [
    # Bare commands
    ("pytest", True),
    ("pytest -q", True),
    ("python -m pytest tests/", True),
    ("python3 -m pytest tests/ -q", True),
    ("jest", True),
    ("npx jest src/", True),
    ("yarn test", True),
    ("npm test", True),
    ("cargo test", True),
    ("go test ./...", True),
    ("rspec spec/", True),
    ("bundle exec rspec", True),
    ("mvn test", True),
    ("./gradlew test", True),
    ("dotnet test", True),
    # With shell prefixes
    ("source .venv/bin/activate && python -m pytest tests/ -q", True),
    ("source .venv/bin/activate && pytest tests/", True),
    ("set -o pipefail; pytest tests/ -q 2>&1 | tail -3", True),
    ("FOO=bar pytest tests/", True),
    # Compound commands where test runner is the second segment
    ("source venv/bin/activate && python -m pytest tests/ -q | tail -5", True),
    # Non-test-runner commands
    ("node app.js", False),
    ("npm install express", False),
    ("python script.py", False),
    ("", False),
    ("echo hello", False),
    ("git commit -m 'fix'", False),
    # Edge: "npm test" appears as substring of "npm testing" — should NOT match
    # (startswith() handles this correctly: "npm testing".startswith("npm test") is True,
    # but we accept this since "npm test" + "ing" is unusual in practice)
])
def test_is_test_runner_command(command, expected):
    assert _is_test_runner_command(command) is expected


def _seed_procedure(mem):
    """Seed a procedure that learn() will accept."""
    mem.start_session("fix_a_bug")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error: Cannot find module express")
    mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added packages")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
    mem.end_session("success")
    procs = mem.learn(min_samples=1)
    assert procs, "seed did not produce a procedure"
    return procs[0]


# ---------------------------------------------------------------- #
# verify_procedure accepts pytest exit_code=0 without substring match
# ---------------------------------------------------------------- #
def test_verify_procedure_accepts_pytest_zero_exit_without_signal_match(tmp_path):
    """The bug we're fixing: pytest -q tail is '[100%]' with no 'passed',
    but exit_code=0 means the suite passed. The receipt should be 'verified'."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        receipt = mem.verify_procedure(
            procedure_id=proc.id,
            verifier_type="pytest",
            verifier_command="source .venv/bin/activate && python -m pytest tests/ -q 2>&1 | tail -3",
            expected_signal="passed",
            observed_signal="... [100%]",  # No "passed" substring
            exit_code=0,
        )
        assert receipt.status == "verified"
    finally:
        mem.close()


def test_verify_procedure_still_requires_exit_zero_for_test_runners(tmp_path):
    """If the test runner exits non-zero, the receipt must be 'failed'
    even if observed_signal somehow contains 'passed'."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        receipt = mem.verify_procedure(
            procedure_id=proc.id,
            verifier_type="pytest",
            verifier_command="pytest tests/",
            expected_signal="passed",
            observed_signal="1 passed, 1 failed",  # contains "passed" but exit=1
            exit_code=1,
        )
        assert receipt.status == "failed"
    finally:
        mem.close()


def test_verify_procedure_non_test_runner_still_requires_signal_match(tmp_path):
    """For non-test-runner commands, the old behavior is preserved:
    exit_code=0 alone is NOT sufficient; expected_signal must be present."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        receipt = mem.verify_procedure(
            procedure_id=proc.id,
            verifier_type="custom",
            verifier_command="./my_custom_verifier.sh",  # not a recognized runner
            expected_signal="ALL_GOOD",
            observed_signal="exit 0",  # no "ALL_GOOD" substring
            exit_code=0,
        )
        assert receipt.status == "failed"
    finally:
        mem.close()


def test_verify_procedure_explicit_verified_with_test_runner_no_signal(tmp_path):
    """A caller can pass status='verified' explicitly; if exit_code=0 and
    the command is a test runner, this should succeed even without signal match."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        receipt = mem.verify_procedure(
            procedure_id=proc.id,
            verifier_type="pytest",
            verifier_command="pytest tests/",
            expected_signal="passed",
            observed_signal="...",
            exit_code=0,
            status="verified",
        )
        assert receipt.status == "verified"
    finally:
        mem.close()


def test_verify_procedure_explicit_verified_non_runner_no_signal_raises(tmp_path):
    """A caller passing status='verified' for a non-test-runner with no
    signal match and exit_code=0 should still raise (preserves old behavior)."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        with pytest.raises(ValueError, match="verified procedure receipt requires"):
            mem.verify_procedure(
                procedure_id=proc.id,
                verifier_type="custom",
                verifier_command="./my_verifier.sh",
                expected_signal="ALL_GOOD",
                observed_signal="exit 0",
                exit_code=0,
                status="verified",
            )
    finally:
        mem.close()
