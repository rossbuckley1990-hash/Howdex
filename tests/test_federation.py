"""Tests for the federated procedure library — lifecycle, scoping, search."""

import pytest
from howdex import Howdex, Federation, FederationEntry


def _seed_procedure(mem):
    """Seed a verified procedure and return it."""
    mem.start_session("fix_missing_dependency")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error: Cannot find module express")
    mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added packages")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
    mem.end_session("success")
    procs = mem.learn(min_samples=1)
    assert procs
    proc = procs[0]
    mem.verify_procedure(
        procedure_id=proc.id,
        verifier_type="bash",
        verifier_command="node app.js | grep -q 'App running'",
        expected_signal="App running",
        observed_signal="App running",
        exit_code=0,
    )
    return proc


# --------------------------------------------------------------------------- #
# Lifecycle: submit → review → publish → deprecate
# --------------------------------------------------------------------------- #
def test_full_lifecycle(tmp_path):
    """A procedure should go through the full lifecycle."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-alpha")

        # Submit
        entry = fed.submit(proc.id, submitted_by="alice")
        assert entry.status == "proposed"
        assert entry.submitted_by == "alice"
        assert entry.receipt_hash  # should have a verified receipt

        # Review (approve)
        entry = fed.review(proc.id, reviewed_by="bob", approved=True, notes="Looks good")
        assert entry.status == "reviewed"
        assert entry.reviewed_by == "bob"
        assert entry.review_notes == "Looks good"

        # Publish
        entry = fed.publish(proc.id, published_by="alice")
        assert entry.status == "published"
        assert entry.published_by == "alice"
        assert entry.published_at is not None

        # Deprecate
        entry = fed.deprecate(proc.id, reason="Node 22 changed the API", deprecated_by="alice")
        assert entry.status == "deprecated"
        assert entry.deprecation_reason == "Node 22 changed the API"
    finally:
        mem.close()


def test_cannot_skip_review(tmp_path):
    """Cannot publish without reviewing first."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-a")

        fed.submit(proc.id, submitted_by="alice")
        with pytest.raises(ValueError, match="Cannot publish from proposed"):
            fed.publish(proc.id, published_by="alice")
    finally:
        mem.close()


def test_cannot_deprecate_unpublished(tmp_path):
    """Cannot deprecate a procedure that isn't published."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-a")

        fed.submit(proc.id, submitted_by="alice")
        with pytest.raises(ValueError, match="Cannot deprecate"):
            fed.deprecate(proc.id, reason="test", deprecated_by="alice")
    finally:
        mem.close()


def test_review_can_reject(tmp_path):
    """Review with approved=False sends back to proposed."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-a")

        fed.submit(proc.id, submitted_by="alice")
        entry = fed.review(proc.id, reviewed_by="bob", approved=False, notes="Needs work")
        assert entry.status == "proposed"
        assert entry.review_notes == "Needs work"
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Per-tenant scoping
# --------------------------------------------------------------------------- #
def test_tenant_isolation(tmp_path):
    """Procedures in one tenant are not visible in another."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed_a = Federation(mem, tenant_id="team-a")
        fed_b = Federation(mem, tenant_id="team-b")

        # Team A submits and publishes
        fed_a.submit(proc.id, submitted_by="alice")
        fed_a.review(proc.id, reviewed_by="bob", approved=True)
        fed_a.publish(proc.id, published_by="alice")

        # Team A sees it
        published_a = fed_a.list_published()
        assert len(published_a) == 1

        # Team B does NOT see it
        published_b = fed_b.list_published()
        assert len(published_b) == 0

        # But list_published without tenant filter (empty string) sees all
        all_published = fed_a.list_published(tenant_id="")
        assert len(all_published) == 1
    finally:
        mem.close()


def test_multiple_tenants(tmp_path):
    """Multiple tenants can each have their own published procedures."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        proc_id = proc.id

        for tenant in ["team-a", "team-b", "team-c"]:
            fed = Federation(mem, tenant_id=tenant)
            fed.submit(proc_id, submitted_by=f"user-{tenant}")
            fed.review(proc_id, reviewed_by=f"reviewer-{tenant}", approved=True)
            fed.publish(proc_id, published_by=f"user-{tenant}")

        # Each tenant sees 1 published
        for tenant in ["team-a", "team-b", "team-c"]:
            fed = Federation(mem, tenant_id=tenant)
            assert len(fed.list_published()) == 1

        # Global list sees all 3 (pass empty string for no tenant filter)
        fed = Federation(mem, tenant_id="default")
        all_published = fed.list_published(tenant_id="")
        assert len(all_published) == 3
        tenants = {e.tenant_id for e in all_published}
        assert tenants == {"team-a", "team-b", "team-c"}
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def test_search_published(tmp_path):
    """Search should find published procedures by task signature."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-a")

        fed.submit(proc.id, submitted_by="alice")
        fed.review(proc.id, reviewed_by="bob", approved=True)
        fed.publish(proc.id, published_by="alice")

        results = fed.search("fix missing dependency")
        assert len(results) >= 1
        assert results[0]["task_signature"] == "fix_missing_dependency"
        assert results[0]["status"] == "published"
    finally:
        mem.close()


def test_search_excludes_unpublished(tmp_path):
    """Search should not return proposed or reviewed entries."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-a")

        # Submit but don't publish
        fed.submit(proc.id, submitted_by="alice")

        results = fed.search("fix missing dependency")
        assert len(results) == 0  # not published yet
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def test_stats(tmp_path):
    """Stats should show counts by status and tenant."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-a")

        fed.submit(proc.id, submitted_by="alice")
        fed.review(proc.id, reviewed_by="bob", approved=True)
        fed.publish(proc.id, published_by="alice")

        stats = fed.stats()
        assert stats["total"] == 1
        assert stats["by_status"]["published"] == 1
        assert "team-a" in stats["tenants"]
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Ledger integration
# --------------------------------------------------------------------------- #
def test_federation_events_recorded_in_ledger(tmp_path):
    """Federation lifecycle events should be recorded in the Merkle ledger."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_procedure(mem)
        fed = Federation(mem, tenant_id="team-a")
        ledger = mem.ledger()

        fed.submit(proc.id, submitted_by="alice")
        fed.review(proc.id, reviewed_by="bob", approved=True)
        fed.publish(proc.id, published_by="alice")

        # Check ledger has federation events
        blocks = ledger.get_blocks(event_type="federation_submit")
        assert len(blocks) >= 1
        blocks = ledger.get_blocks(event_type="federation_review")
        assert len(blocks) >= 1
        blocks = ledger.get_blocks(event_type="federation_publish")
        assert len(blocks) >= 1

        # Ledger should still be valid
        valid, _ = ledger.verify()
        assert valid
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #
def test_cli_federation_lifecycle(tmp_path):
    """Full federation lifecycle via CLI."""
    import subprocess, sys
    db = tmp_path / "fed.db"
    # Seed a procedure
    mem = Howdex(path=str(db), embedder="hashing")
    proc = _seed_procedure(mem)
    proc_id = proc.id
    mem.close()

    def run_cli(args):
        return subprocess.run(
            [sys.executable, "-m", "howdex.cli", "--path", str(db),
             "--embedder", "hashing"] + args,
            capture_output=True, text=True, timeout=30,
        )

    # Submit
    r = run_cli(["federation", "submit", proc_id, "--tenant", "team-a", "--by", "alice"])
    assert r.returncode == 0, f"submit failed: {r.stderr}"
    assert "Submitted" in r.stdout

    # Review
    r = run_cli(["federation", "review", proc_id, "--approve", "--by", "bob", "--tenant", "team-a"])
    assert r.returncode == 0, f"review failed: {r.stderr}"
    assert "Reviewed" in r.stdout

    # Publish
    r = run_cli(["federation", "publish", proc_id, "--by", "alice", "--tenant", "team-a"])
    assert r.returncode == 0, f"publish failed: {r.stderr}"
    assert "Published" in r.stdout

    # List
    r = run_cli(["federation", "list", "--tenant", "team-a", "--status", "published"])
    assert r.returncode == 0
    assert proc_id[:8] in r.stdout or proc_id in r.stdout

    # Search
    r = run_cli(["federation", "search", "fix missing", "--tenant", "team-a"])
    assert r.returncode == 0
    assert "fix_missing_dependency" in r.stdout
