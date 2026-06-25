"""Tests for the Day-2 operational risk fixes.

Covers:
1. BootProof verifier gate — blocks learn() for unverified sessions
2. Trust calibration curve + needle_in_haystack_risk
3. Integration tax — @instrument decorator, session_scope, LangChain adapter
"""

import pytest

from howdex import Howdex, BootProof, instrument, session_scope


# --------------------------------------------------------------------------- #
# Fix 1: BootProof verifier gate
# --------------------------------------------------------------------------- #
def _seed_procedure(mem, task="fix_bug"):
    """Seed a procedure and return it."""
    mem.start_session(task)
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"},
                      "Error: Cannot find module express")
    mem.log_tool_call("execute_bash", {"cmd": "npm install express"},
                      "added packages")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"},
                      "App running")
    mem.end_session("success")
    procs = mem.learn(min_samples=1)
    assert procs
    return procs[0]


def test_bootproof_blocks_learn_without_receipt(tmp_path):
    """BootProof.learn() must NOT consolidate a session that has no
    verified receipt from a deterministic verifier."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        gate = BootProof(mem)
        # learn() through the gate should return [] because no receipt
        result = gate.learn(min_samples=1)
        assert result == []
        # The rejected session should be recorded
        assert len(gate.rejected_sessions) >= 1
        assert gate.rejected_sessions[0]["reason"] == "no_verified_deterministic_receipt"
    finally:
        mem.close()


def test_bootproof_allows_learn_with_exit_code_receipt(tmp_path):
    """BootProof.learn() should consolidate when a deterministic verifier
    (exit_code=0) has confirmed the procedure."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        gate = BootProof(mem)
        # Verify with a deterministic exit code
        gate.verify_with_exit_code(
            procedure_id=proc.id,
            verifier_command="node app.js | grep -q 'App running'",
            exit_code=0,
            observed_signal="App running",
        )
        # Now learn() through the gate should succeed
        result = gate.learn(min_samples=1)
        assert len(result) == 1
        assert result[0].task_signature == "fix_bug"
    finally:
        mem.close()


def test_bootproof_blocks_learn_with_failed_exit_code(tmp_path):
    """A failed exit code (non-zero) must NOT mark the session as verified."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        gate = BootProof(mem)
        gate.verify_with_exit_code(
            procedure_id=proc.id,
            verifier_command="node app.js | grep -q 'App running'",
            exit_code=1,  # FAILED
            observed_signal="",
        )
        result = gate.learn(min_samples=1)
        assert result == []  # blocked
    finally:
        mem.close()


def test_bootproof_verify_with_http_status(tmp_path):
    """HTTP 200 should mark the session as verified; 500 should not."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        gate = BootProof(mem)
        gate.verify_with_http_status(
            procedure_id=proc.id,
            verifier_command="curl -sf http://localhost:8080/health",
            status_code=200,
            observed_signal='{"status":"ok"}',
        )
        assert gate.is_verified(proc.id)
        result = gate.learn(min_samples=1)
        assert len(result) == 1
    finally:
        mem.close()


def test_bootproof_verify_with_http_status_failure(tmp_path):
    """HTTP 500 should NOT mark the session as verified."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        gate = BootProof(mem)
        gate.verify_with_http_status(
            procedure_id=proc.id,
            verifier_command="curl -sf http://localhost:8080/health",
            status_code=500,
        )
        assert not gate.is_verified(proc.id)
        result = gate.learn(min_samples=1)
        assert result == []
    finally:
        mem.close()


def test_bootproof_verify_with_test_runner(tmp_path):
    """Test runner (pytest) with exit_code=0 should verify the session."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        gate = BootProof(mem)
        gate.verify_with_test_runner(
            procedure_id=proc.id,
            verifier_command="pytest tests/",
            exit_code=0,
            observed_signal="561 passed",
        )
        assert gate.is_verified(proc.id)
        result = gate.learn(min_samples=1)
        assert len(result) == 1
    finally:
        mem.close()


def test_bootproof_is_verified_returns_false_for_unknown(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        gate = BootProof(mem)
        assert not gate.is_verified("nonexistent-id")
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Fix 2: Trust calibration curve + needle_in_haystack_risk
# --------------------------------------------------------------------------- #
def test_trust_calibration_curve_empty(tmp_path):
    """With no procedures, the curve should report zero everything."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        curve = mem.trust_calibration_curve()
        assert curve["total_procedures"] == 0
        assert curve["verified"] == 0
        assert curve["candidate"] == 0
        assert curve["verified_ratio"] == 0.0
    finally:
        mem.close()


def test_trust_calibration_curve_with_unverified(tmp_path):
    """Procedures without receipts are 'candidate'; ratio is low."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_procedure(mem)
        curve = mem.trust_calibration_curve()
        assert curve["total_procedures"] == 1
        assert curve["candidate"] == 1
        assert curve["verified"] == 0
        assert curve["verified_ratio"] == 0.0
        # Low ratio → recommend top_k=1 and verified_only=True
        assert curve["recommended_top_k"] == 1
        assert curve["recommended_verified_only"] is True
    finally:
        mem.close()


def test_trust_calibration_curve_with_verified(tmp_path):
    """Procedures with verified receipts have a high ratio."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        mem.verify_procedure(
            procedure_id=proc.id,
            verifier_type="bash",
            verifier_command="node app.js | grep -q 'App running'",
            expected_signal="App running",
            observed_signal="App running",
            exit_code=0,
        )
        curve = mem.trust_calibration_curve()
        assert curve["total_procedures"] == 1
        assert curve["verified"] == 1
        assert curve["verified_ratio"] == 1.0
        # High ratio → recommend top_k=3
        assert curve["recommended_top_k"] == 3
        assert curve["recommended_verified_only"] is False
    finally:
        mem.close()


def test_needle_in_haystack_risk_low(tmp_path):
    """With no procedures, risk should be low."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        risk = mem.needle_in_haystack_risk("fix a bug", max_chars=6000)
        assert risk["risk_level"] == "low"
        assert risk["retrieved_count"] == 0
    finally:
        mem.close()


def test_needle_in_haystack_risk_returns_recommendation(tmp_path):
    """The risk assessment should always include a recommendation string."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_procedure(mem)
        risk = mem.needle_in_haystack_risk("fix a bug", max_chars=6000)
        assert "recommendation" in risk
        assert isinstance(risk["recommendation"], str)
        assert len(risk["recommendation"]) > 10
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Fix 3: Integration tax — @instrument decorator
# --------------------------------------------------------------------------- #
def test_instrument_decorator_logs_successful_call(tmp_path):
    """The @instrument decorator should log the function call as a tool call."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        @instrument(mem)
        def search_code(query: str, glob: str = "*.py") -> str:
            return f"found 3 matches for {query}"

        mem.start_session("test_task")
        result = search_code("def load_config")
        assert result == "found 3 matches for def load_config"
        mem.end_session("success")

        # Verify the call was logged
        eps = mem.store.query_episodes()
        assert len(eps) == 1
        # The episode should have at least 1 step
        import json
        steps = json.loads(eps[0]["steps"]) if isinstance(eps[0]["steps"], str) else eps[0]["steps"]
        assert len(steps) >= 1
        assert steps[0]["tool_name"] == "search_code"
    finally:
        mem.close()


def test_instrument_decorator_logs_exception(tmp_path):
    """The @instrument decorator should log exceptions and re-raise."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        @instrument(mem)
        def failing_function(x: int) -> int:
            raise ValueError("boom")

        mem.start_session("test_task")
        with pytest.raises(ValueError):
            failing_function(42)
        mem.end_session("failure")

        # Verify the exception was logged
        eps = mem.store.query_episodes()
        assert len(eps) == 1
        import json
        steps = json.loads(eps[0]["steps"]) if isinstance(eps[0]["steps"], str) else eps[0]["steps"]
        assert len(steps) >= 1
        assert "Exception" in steps[0].get("observation", "")
    finally:
        mem.close()


def test_instrument_decorator_custom_name(tmp_path):
    """The @instrument decorator should use the custom name if provided."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        @instrument(mem, name="run_tests")
        def pytest_runner(target: str) -> str:
            return "561 passed"

        mem.start_session("test_task")
        pytest_runner("tests/")
        mem.end_session("success")

        eps = mem.store.query_episodes()
        import json
        steps = json.loads(eps[0]["steps"]) if isinstance(eps[0]["steps"], str) else eps[0]["steps"]
        assert steps[0]["tool_name"] == "run_tests"
    finally:
        mem.close()


def test_instrument_decorator_safe_outside_session(tmp_path):
    """The @instrument decorator should not crash if no session is active."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        @instrument(mem)
        def some_function(x: int) -> int:
            return x * 2

        # No session active — should still work, just not log
        result = some_function(21)
        assert result == 42
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Fix 3: session_scope context manager
# --------------------------------------------------------------------------- #
def test_session_scope_success(tmp_path):
    """session_scope should end the session as 'success' on clean exit."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        with session_scope(mem, "fix_bug") as m:
            m.log_tool_call("execute_command", {"cmd": "ls"}, "ok")
        # Session should be ended as success
        eps = mem.store.query_episodes()
        assert len(eps) == 1
        assert eps[0]["outcome"] == "success"
    finally:
        mem.close()


def test_session_scope_failure(tmp_path):
    """session_scope should end the session as 'failure' on exception."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        with pytest.raises(RuntimeError):
            with session_scope(mem, "fix_bug") as m:
                m.log_tool_call("execute_command", {"cmd": "ls"}, "ok")
                raise RuntimeError("something went wrong")
        # Session should be ended as failure
        eps = mem.store.query_episodes()
        assert len(eps) == 1
        assert eps[0]["outcome"] == "failure"
    finally:
        mem.close()


def test_session_scope_with_require_receipt(tmp_path):
    """session_scope should pass require_receipt through to end_session."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        with session_scope(mem, "fix_bug", require_receipt=True) as m:
            # Log a failure observation to trigger the integrity check
            m.log_tool_call("execute_command", {"cmd": "make build"},
                            "Error: build failed")
        # The outcome should be downgraded to "unverified" because
        # require_receipt=True and no receipt was attached
        eps = mem.store.query_episodes()
        assert eps[0]["outcome"] == "unverified"
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Fix 3: auto_instrument_langchain
# --------------------------------------------------------------------------- #
def test_auto_instrument_langchain_logs_calls(tmp_path):
    """auto_instrument_langchain should monkey-patch tools to log calls."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        # Create a fake tool object with a .run() method
        class FakeTool:
            def __init__(self, name):
                self.name = name

            def run(self, query: str) -> str:
                return f"results for {query}"

        tool = FakeTool("search")
        from howdex.instrument import auto_instrument_langchain
        auto_instrument_langchain(mem, [tool])

        mem.start_session("agent_task")
        result = tool.run("def load_config")
        assert result == "results for def load_config"
        mem.end_session("success")

        # The call should have been logged
        eps = mem.store.query_episodes()
        import json
        steps = json.loads(eps[0]["steps"]) if isinstance(eps[0]["steps"], str) else eps[0]["steps"]
        assert len(steps) >= 1
        assert steps[0]["tool_name"] == "search"
    finally:
        mem.close()
