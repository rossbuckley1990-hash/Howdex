"""CI regression test: README examples must run verbatim and read as success.

This test runs the exact commands documented in the README and asserts
they produce output that reads as success to a newcomer. If any of
these fail, the front door is broken and the PR should be blocked.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from howdex import Howdex


def _run_cli(args, env=None):
    """Run the howdex CLI via subprocess (matches what a user types)."""
    return subprocess.run(
        [sys.executable, "-m", "howdex.cli"] + args,
        capture_output=True, text=True, timeout=30, env=env,
    )


def test_readme_cli_smoke_test_returns_match(tmp_path):
    """The README's CLI smoke test must return a match, not 'no memories matched'.

    README says:
        howdex --path /tmp/howdex.db init
        howdex --path /tmp/howdex.db remember "user loves python"
        howdex --path /tmp/howdex.db search "python preference"
    """
    db = tmp_path / "howdex.db"
    # init
    r = _run_cli(["--path", str(db), "init"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    # remember
    r = _run_cli(["--path", str(db), "remember", "user loves python"])
    assert r.returncode == 0, f"remember failed: {r.stderr}"
    # search — must return a match
    r = _run_cli(["--path", str(db), "search", "python preference"])
    assert r.returncode == 0, f"search failed: {r.stderr}"
    assert "no memories matched" not in r.stdout.lower(), (
        f"search returned no matches — stdout: {r.stdout}"
    )
    assert "user loves python" in r.stdout, (
        f"expected 'user loves python' in search results, got: {r.stdout}"
    )


def test_readme_python_quickstart_runs_clean(tmp_path):
    """The README's Python quickstart must run without errors."""
    db = tmp_path / "quickstart.db"
    # Reproduce the README quickstart code
    mem = Howdex(path=str(db), embedder="hashing")
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
    procedures = mem.learn(min_samples=1)
    assert procedures, "learn() should return at least 1 procedure"
    guidance = mem.guidance(
        "Fix a Node app that cannot find module cors",
        max_chars=4000,
    )
    assert "HOWDEX OPERATIONAL MEMORY" in guidance
    assert "fix_missing_dependency" in guidance
    mem.close()


def test_first_time_dev_script_runs_clean(tmp_path, monkeypatch):
    """examples/first_time_dev.py must run end-to-end without errors."""
    monkeypatch.chdir(tmp_path)
    repo_root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, str(repo_root / "examples" / "first_time_dev.py")],
        capture_output=True, text=True, timeout=60,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, (
        f"first_time_dev.py failed:\nstdout: {result.stdout[-500:]}\n"
        f"stderr: {result.stderr[-500:]}"
    )
    # Must show success indicators
    assert "verified" in result.stdout.lower(), (
        f"expected 'verified' in output, got: {result.stdout[-300:]}"
    )
    assert "codex lint passed" in result.stdout.lower(), (
        f"expected 'codex lint passed' in output, got: {result.stdout[-300:]}"
    )


def test_learn_returns_diagnostic_when_empty(tmp_path):
    """learn() should warn with a helpful message when it returns 0 procedures."""
    import warnings
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            procs = mem.learn(min_samples=1)
            assert procs == []
            # Should have emitted a warning explaining why
            assert len(w) >= 1
            warning_msg = str(w[0].message)
            assert "0 procedures" in warning_msg or "no episodes" in warning_msg.lower()
    finally:
        mem.close()


def test_learn_diagnostic_when_no_successes(tmp_path):
    """learn() should warn when episodes exist but none are 'success'."""
    import warnings
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.start_session("failing_task")
        mem.log_tool_call("execute_bash", {"cmd": "false"}, "error")
        mem.end_session("failure")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            procs = mem.learn(min_samples=1)
            assert procs == []
            assert len(w) >= 1
            warning_msg = str(w[0].message)
            assert "0 had outcome='success'" in warning_msg or "success" in warning_msg.lower()
    finally:
        mem.close()
