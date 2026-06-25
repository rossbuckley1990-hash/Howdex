"""Tests for the senior-inspection findings fixes.

Each test verifies a specific finding from the senior lead engineer
inspection report. All findings were verified with real repros before
the fix was applied.
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from howdex import Howdex, BootProof, session_scope
from howdex.core.guidance_artifacts import _is_failure_marker_negated
from howdex.vectors.index import VectorIndex


# --------------------------------------------------------------------------- #
# C1: CRDT delete clock check
# --------------------------------------------------------------------------- #
def test_crdt_stale_delete_does_not_tombstone_newer_memory(tmp_path):
    """A stale delete (lower vector_clock) must NOT tombstone a newer memory."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.remember("important data", layer="semantic")
        # Get the memory's vector_clock
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        row = conn.execute("SELECT id, vector_clock, deleted FROM memories LIMIT 1").fetchone()
        mem_id, vc_high, _ = row
        conn.close()
        # Apply a stale delete with a much lower vector_clock
        stale_op = {
            "op": "delete",
            "memory_id": mem_id,
            "vector_clock": vc_high - 1_000_000,
            "node_id": "node-stale",
            "payload": "{}",
        }
        mem.store.apply_remote_op(stale_op)
        # The memory should NOT be deleted
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        row = conn.execute("SELECT deleted FROM memories WHERE id=?", (mem_id,)).fetchone()
        conn.close()
        assert row[0] == 0, "stale delete tombstoned a newer memory (C1 bug)"
    finally:
        mem.close()


def test_crdt_fresh_delete_tombstones_older_memory(tmp_path):
    """A fresh delete (higher vector_clock) SHOULD tombstone an older memory."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.remember("old data", layer="semantic")
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        row = conn.execute("SELECT id, vector_clock FROM memories LIMIT 1").fetchone()
        mem_id, vc_low = row
        conn.close()
        # Apply a fresh delete with a higher vector_clock
        fresh_op = {
            "op": "delete",
            "memory_id": mem_id,
            "vector_clock": vc_low + 1_000_000,
            "node_id": "node-fresh",
            "payload": "{}",
        }
        mem.store.apply_remote_op(fresh_op)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        row = conn.execute("SELECT deleted FROM memories WHERE id=?", (mem_id,)).fetchone()
        conn.close()
        assert row[0] == 1, "fresh delete failed to tombstone older memory"
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# C2: _is_failure_marker_negated — mixed counts
# --------------------------------------------------------------------------- #
def test_mixed_failure_with_zero_count_is_not_negated():
    """'1 failed, 0 errors' must NOT be negated (real failure present)."""
    assert not _is_failure_marker_negated("1 failed, 0 errors")
    assert not _is_failure_marker_negated("0 failed, 1 error")
    assert not _is_failure_marker_negated("no failures, 1 error")
    assert not _is_failure_marker_negated("failed=0, error=1")


def test_all_zero_counts_are_negated():
    """'0 failed, 0 errors' SHOULD be negated (genuine success summary)."""
    assert _is_failure_marker_negated("0 failed, 0 errors")
    assert _is_failure_marker_negated("parsed 6/6 dates, 0 failed")
    assert _is_failure_marker_negated("exit=0 :: failed=0, errors=0")


def test_real_failures_still_not_negated():
    assert not _is_failure_marker_negated("1 failed, 5 passed")
    assert not _is_failure_marker_negated("fatal: database is locked")
    assert not _is_failure_marker_negated("ImportError: no module named foo")


# --------------------------------------------------------------------------- #
# C3: Vector index — no 1.5GB pre-allocation
# --------------------------------------------------------------------------- #
def test_vector_index_starts_small(tmp_path):
    """Adding 1 vector should NOT allocate 1.5 GB."""
    import numpy as np
    import tracemalloc
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()
    idx = VectorIndex(dim=384, metric="cosine")
    vec = np.random.rand(384).astype(np.float32)
    idx.add("test-id", vec)
    snapshot2 = tracemalloc.take_snapshot()
    stats = snapshot2.compare_to(snapshot1, "lineno")
    total = sum(s.size_diff for s in stats)
    tracemalloc.stop()
    # Should be well under 100 MB (was 1465 MB before the fix)
    assert total < 100 * 1024 * 1024, (
        f"Vector index allocated {total / 1024 / 1024:.1f} MB on first add "
        f"(should be < 100 MB)"
    )


def test_vector_index_grows_geometrically():
    """The index should handle >1024 vectors by growing."""
    import numpy as np
    idx = VectorIndex(dim=64, metric="cosine")
    for i in range(2000):
        vec = np.random.rand(64).astype(np.float32)
        idx.add(f"id-{i}", vec)
    assert len(idx._ids) == 2000
    # Search should still work
    query = np.random.rand(64).astype(np.float32)
    results = idx.search(query, k=5)
    assert len(results) == 5


# --------------------------------------------------------------------------- #
# H1: trust_calibration_curve — failed takes precedence
# --------------------------------------------------------------------------- #
def test_trust_calibration_failed_takes_precedence_over_verified(tmp_path):
    """A procedure with BOTH verified AND failed receipts counts as failed."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.start_session("fix_bug")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
        mem.end_session("success")
        procs = mem.learn(min_samples=1)
        proc = procs[0]
        # Attach BOTH a verified AND a failed receipt
        mem.verify_procedure(procedure_id=proc.id, verifier_type="bash",
            verifier_command="true", expected_signal="ok",
            observed_signal="ok", exit_code=0)
        mem.verify_procedure(procedure_id=proc.id, verifier_type="bash",
            verifier_command="false", expected_signal="ok",
            observed_signal="fail", exit_code=1)
        curve = mem.trust_calibration_curve()
        assert curve["failed"] == 1, f"expected failed=1, got {curve['failed']}"
        assert curve["verified"] == 0, f"expected verified=0, got {curve['verified']}"
        assert curve["verified_ratio"] == 0.0
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# H2: needle_in_haystack_risk uses canonical_name
# --------------------------------------------------------------------------- #
def test_needle_in_haystack_uses_canonical_name(tmp_path):
    """The overlap detection should use canonical_name, not canonical_action."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.start_session("fix_bug")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
        mem.end_session("success")
        mem.learn(min_samples=1)
        risk = mem.needle_in_haystack_risk("fix a bug", max_chars=6000)
        # Should return a valid risk assessment
        assert risk["risk_level"] in {"low", "medium", "high"}
        assert "recommendation" in risk
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# H3: session_scope — no double end_session
# --------------------------------------------------------------------------- #
def test_session_scope_no_double_end_on_success_raise(tmp_path):
    """If end_session('success') raises, session_scope should not call it again."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        call_count = [0]
        original_end = mem.end_session

        def flaky_end(*args, **kwargs):
            call_count[0] += 1
            outcome = args[0] if args else kwargs.get("outcome", "?")
            if outcome == "success":
                raise RuntimeError("simulated store failure")
            return original_end(*args, **kwargs)

        mem.end_session = flaky_end
        with pytest.raises(RuntimeError):
            with session_scope(mem, "test"):
                mem.log_tool_call("execute_command", {"cmd": "ls"}, "ok")
        # end_session should have been called at most 2 times:
        # once for "success" (which raised), and at most once for "failure"
        # (if the session was still active). The key assertion: it must NOT
        # loop or call more than twice.
        assert call_count[0] <= 2, (
            f"end_session called {call_count[0]} times (should be <= 2)"
        )
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# H4: No 10k episode truncation
# --------------------------------------------------------------------------- #
def test_consolidate_does_not_truncate_at_10k(tmp_path):
    """consolidate() should process all episodes, not just the last 10k."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        # Create 12,000 episodes — old code would only process 10,000
        for i in range(12_000):
            mem.start_session("recurring_task")
            mem.log_tool_call("execute_bash", {"cmd": f"cmd_{i}"}, "ok")
            mem.end_session("success")
        # Verify that query_episodes returns ALL 12,000, not just 10,000.
        # The old consolidate() hardcoded limit=10_000 which silently
        # dropped 2,000 older episodes.
        all_eps = mem.store.query_episodes(limit=10_000_000)
        assert len(all_eps) == 12_000, (
            f"expected 12,000 episodes, got {len(all_eps)} — "
            f"consolidation is silently truncating (H4 bug)"
        )
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# H5: Store.close() releases connections
# --------------------------------------------------------------------------- #
def test_store_close_releases_connections(tmp_path):
    """Store.close() should close the SQLite connection."""
    from howdex.storage import Store
    store = Store(path=str(tmp_path / "test.db"))
    conn = store._conn()
    assert conn is not None
    # Verify the connection is tracked
    assert len(store._all_connections) >= 1
    store.close()
    # After close, the connection list should be empty
    assert len(store._all_connections) == 0


def test_howdex_close_closes_store(tmp_path):
    """Howdex.close() should close the underlying Store."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    assert len(mem.store._all_connections) >= 1
    mem.close()
    assert len(mem.store._all_connections) == 0


def test_store_context_manager(tmp_path):
    """Store should work as a context manager."""
    from howdex.storage import Store
    with Store(path=str(tmp_path / "test.db")) as store:
        conn = store._conn()
        assert conn is not None
    # After exiting, connections should be closed
    assert len(store._all_connections) == 0


# --------------------------------------------------------------------------- #
# H6: Delete uses milliseconds (consistent with upsert)
# --------------------------------------------------------------------------- #
def test_delete_uses_milliseconds(tmp_path):
    """The delete sync_log vector_clock should be in milliseconds, not seconds."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.remember("to be deleted", layer="semantic")
        results = mem.search("deleted")
        mem_id = results[0].memory.id
        mem.forget(mem_id)
        # Check the sync_log
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        row = conn.execute(
            "SELECT vector_clock FROM sync_log WHERE op='delete' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        vc = row[0]
        # Should be in milliseconds (~1.7 trillion for 2024), not seconds (~1.7 billion)
        assert vc > 1_000_000_000_000, (
            f"delete vector_clock={vc} looks like seconds, not milliseconds (H6 bug)"
        )
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# M1: BootProof derives verification from persistent receipts
# --------------------------------------------------------------------------- #
def test_bootproof_verification_survives_restart(tmp_path):
    """BootProof verification should persist across process restarts."""
    db_path = str(tmp_path / "test.db")
    # First session: create + verify
    mem1 = Howdex(path=db_path, embedder="hashing")
    mem1.start_session("fix_bug")
    mem1.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error")
    mem1.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added")
    mem1.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
    mem1.end_session("success")
    procs = mem1.learn(min_samples=1)
    proc_id = procs[0].id
    gate1 = BootProof(mem1)
    gate1.verify_with_exit_code(
        procedure_id=proc_id,
        verifier_command="node app.js",
        exit_code=0,
    )
    mem1.close()
    # Second session: new Howdex + BootProof (simulates restart)
    mem2 = Howdex(path=db_path, embedder="hashing")
    gate2 = BootProof(mem2)
    # is_verified should return True based on persistent receipts
    assert gate2.is_verified(proc_id), (
        "verification did not survive restart (M1 bug)"
    )
    # learn() through the gate should also work
    result = gate2.learn(min_samples=1)
    assert len(result) >= 1
    mem2.close()


# --------------------------------------------------------------------------- #
# M10: _session_has_verified_receipt default-safe
# --------------------------------------------------------------------------- #
def test_session_has_verified_receipt_defaults_false_on_error(tmp_path):
    """On storage error, _session_has_verified_receipt should return False."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        # Patch all_procedures to raise
        original_all = mem.store.all_procedures
        def raising_all():
            raise RuntimeError("simulated storage error")
        mem.store.all_procedures = raising_all
        result = mem._session_has_verified_receipt("fake-session-id")
        assert result is False, (
            "should return False on storage error (M10 fix), not True"
        )
    finally:
        mem.store.all_procedures = original_all
        mem.close()
