"""Regression tests for front-door bugs found by external review.

Each test verifies a specific bug that a newcomer hits in the first
five minutes. These are the adoption-surface bugs, not internal
correctness — the ones that decide whether anyone adopts Howdex.
"""

import pytest

from howdex import Howdex


def _seed_node_procedure(mem):
    """Seed a Node.js fix-missing-dependency procedure."""
    mem.start_session("fix_missing_dependency")
    mem.log_tool_call(
        "execute_bash",
        {"cmd": "node app.js"},
        "Error: Cannot find module 'express'",
    )
    mem.log_tool_call(
        "execute_bash",
        {"cmd": "npm install express"},
        "added packages",
    )
    mem.log_tool_call(
        "execute_bash",
        {"cmd": "node app.js"},
        "App running",
    )
    mem.end_session("success")
    procs = mem.learn(min_samples=1)
    assert procs
    return procs[0]


# --------------------------------------------------------------------------- #
# The SHA256 contaminant regression
# --------------------------------------------------------------------------- #
def test_node_procedure_guidance_does_not_contain_sha256(tmp_path):
    """A Node.js procedure's guidance must NOT mention SHA256.

    This is the #1 guidance-quality bug: the parameterizer's
    `args:sha256:<hash>` fallback target caused the fact extractor
    to emit "calculate the SHA256 hex digest" for procedures that
    have nothing to do with cryptography. A newcomer asking for
    guidance on a Node bug would see crypto-hashing advice —
    nonsensical and confidence-destroying.
    """
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_node_procedure(mem)
        guidance = mem.guidance(
            "Fix a Node app that can't find module cors",
            max_chars=4000,
        )
        # The SHA256 contaminant must be gone
        assert "sha256" not in guidance.lower(), (
            "guidance for a Node.js procedure contains 'sha256' — "
            "the args:sha256: fallback target is contaminating fact extraction"
        )
        assert "SHA256" not in guidance, (
            "guidance for a Node.js procedure contains 'SHA256'"
        )
        assert "hex digest" not in guidance.lower(), (
            "guidance contains 'hex digest' — crypto fact leaked into unrelated task"
        )
        # The correct facts should be present
        assert "execute_file" in guidance or "install_dependencies" in guidance, (
            "expected Node.js facts (execute_file, install_dependencies) in guidance"
        )
    finally:
        mem.close()


def test_node_procedure_guidance_does_not_contain_crypto_facts(tmp_path):
    """Broader regression: no crypto/openssl facts for a non-crypto procedure."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_node_procedure(mem)
        guidance = mem.guidance(
            "Fix a Node app that can't find module cors",
            max_chars=4000,
        )
        crypto_markers = [
            "sha256",
            "openssl",
            "aes-256",
            "pbkdf2",
            "hex digest",
            "trailing newline",
            "reverse the input",
        ]
        for marker in crypto_markers:
            assert marker not in guidance.lower(), (
                f"guidance contains crypto marker '{marker}' for a Node.js procedure"
            )
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# The quickstart "Selected 0" regression
# --------------------------------------------------------------------------- #
def test_quickstart_guidance_surfaces_learned_procedure(tmp_path):
    """The quickstart's guidance call must surface the learned procedure.

    Previously, max_chars=2000 triggered adaptive filtering that set
    verified_only=True, excluding the unverified quickstart procedure.
    A newcomer saw "Selected procedures: 0, Omitted procedures: 1"
    and reasonably concluded it didn't work.
    """
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        # Replicate the quickstart's 3-session morning briefing task
        for _ in range(3):
            mem.start_session("send_morning_briefing")
            mem.log_tool_call(
                "fetch_calendar",
                {"source": "google_calendar", "range": "today"},
                "3 events scheduled today",
            )
            mem.log_tool_call(
                "summarize_emails",
                {"mailbox": "inbox", "max_messages": 50},
                "12 unread emails, 3 marked important",
            )
            mem.log_tool_call(
                "send_slack_message",
                {"channel": "#morning-briefing", "text": "Good morning!"},
                "message sent successfully",
            )
            mem.end_session("success")
        procs = mem.learn(min_samples=3)
        assert procs
        # The quickstart uses max_chars=4000 (after the fix)
        guidance = mem.guidance(
            "Prepare the morning briefing for the team channel",
            max_chars=4000,
        )
        # The procedure must be selected, not omitted
        assert "Selected procedures: 1" in guidance, (
            f"expected 'Selected procedures: 1' in guidance, got:\n"
            f"{guidance[:500]}"
        )
        assert "Omitted procedures: 0" in guidance
        assert "send_morning_briefing" in guidance
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# The CLI smoke test regression
# --------------------------------------------------------------------------- #
def test_cli_smoke_test_returns_match(tmp_path):
    """The README's CLI smoke test must return a match, not 'no memories matched'.

    The hash embedder is keyword-overlap only, so the search query must
    share a token with the stored memory. The README uses
    `search "python preference"` (shares 'python') — this must match.
    """
    import subprocess
    import sys
    db = tmp_path / "smoke.db"
    # init
    r = subprocess.run(
        [sys.executable, "-m", "howdex.cli", "--path", str(db),
         "--embedder", "hashing", "init"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0
    # remember
    r = subprocess.run(
        [sys.executable, "-m", "howdex.cli", "--path", str(db),
         "--embedder", "hashing", "remember", "user loves python"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0
    # search with a query that shares a token
    r = subprocess.run(
        [sys.executable, "-m", "howdex.cli", "--path", str(db),
         "--embedder", "hashing", "search", "python preference"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0
    assert "no memories matched" not in r.stdout, (
        f"search returned no matches — stdout: {r.stdout}"
    )
    assert "user loves python" in r.stdout, (
        f"expected 'user loves python' in search results, got: {r.stdout}"
    )
