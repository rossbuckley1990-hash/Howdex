"""Regression test: instrumented tool calls survive consolidation.

The bug: _canonicalize_learning_step re-canonicalized command tools
(run_bash, execute_command) using the prose canonicalize_action. When
the command string wasn't recognized by the prose patterns (e.g.
"python -c 'import broken_pkg'"), it returned unknown_action. This
dropped the known-ratio below 0.5, causing _trace_from_episode to
return None, causing learn() to return 0 procedures.

The fix: when the prose canonicalizer returns unknown_action for a
command tool, fall back to the stored canonical from tool_call_from_step.
"""

import pytest

from howdex import Howdex, instrument, session_scope


def test_instrumented_run_bash_survives_consolidation(tmp_path):
    """A trace logged via @instrument(mem) with run_bash calls must
    produce a procedure from learn().

    Previously, run_bash was classified as a command tool, and the prose
    re-canonicalizer returned unknown_action for arbitrary commands.
    This dropped the known-ratio below 0.5 and learn() returned 0.
    """
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        @instrument(mem)
        def run_bash(cmd: str) -> str:
            return f"exit=0 :: ok"

        @instrument(mem)
        def rename_file(old: str, new: str) -> str:
            return "renamed"

        with session_scope(mem, "fix_module_not_found"):
            run_bash("python -c 'import broken_pkg'")
            run_bash("ls broken_pkg/")
            rename_file("helper.py", "helpers.py")
            run_bash("python -c 'import broken_pkg'")

        procs = mem.learn(min_samples=1)
        assert len(procs) == 1, (
            f"expected 1 procedure from instrumented trace, got {len(procs)} — "
            f"the @instrument tool calls (run_bash, rename_file) were likely "
            f"classified as unknown_action during consolidation"
        )
        # The procedure should have 4 steps (all survived)
        assert len(procs[0].steps) == 4, (
            f"expected 4 steps, got {len(procs[0].steps)}"
        )
    finally:
        mem.close()


def test_instrumented_execute_command_survives_consolidation(tmp_path):
    """Same regression for execute_command — another command-tool name
    that triggers the prose re-canonicalization path."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        @instrument(mem)
        def execute_command(cmd: str) -> str:
            return "exit=0 :: ok"

        with session_scope(mem, "run_arbitrary_command"):
            execute_command("python -c 'print(1)'")
            execute_command("python -c 'print(2)'")

        procs = mem.learn(min_samples=1)
        assert len(procs) == 1, (
            f"expected 1 procedure, got {len(procs)}"
        )
    finally:
        mem.close()


def test_full_registry_loop_resolves(tmp_path):
    """The full network-effect loop: record → learn → verify → publish →
    push to registry → second agent finds it via registry search.

    This is the end-to-end test of the unicorn thesis.
    """
    import json
    import shutil
    from pathlib import Path
    from howdex import BootProof, public_registry

    mem = Howdex(path=str(tmp_path / "agent1.db"), embedder="hashing")
    try:
        @instrument(mem)
        def run_bash(cmd: str) -> str:
            return "exit=0 :: ok"

        @instrument(mem)
        def rename_file(old: str, new: str) -> str:
            return "renamed"

        with session_scope(mem, "fix_python_module_not_found"):
            run_bash("python -c 'import broken_pkg'")
            rename_file("helper.py", "helpers.py")
            run_bash("python -c 'import broken_pkg'")

        # Learn
        procs = mem.learn(min_samples=1)
        assert len(procs) == 1

        # BootProof verify
        gate = BootProof(mem)
        gate.verify_with_exit_code(
            procedure_id=procs[0].id,
            verifier_command="python -c 'import broken_pkg'",
            exit_code=0,
        )
        verified = gate.learn(min_samples=1)
        assert len(verified) == 1

        # Publish + push to registry
        codex_path = tmp_path / "codex"
        mem.publish_codex(codex_path)
        registry_path = tmp_path / "registry"
        result = public_registry.registry_push(
            codex_path / "procedures",
            registry_path,
        )
        assert result["pushed"] == 1

        # Second agent with empty memory searches the registry
        results = public_registry.registry_search(
            "python module not found",
            registry_path,
        )
        assert len(results) >= 1, (
            "second agent should find the contributed procedure in the registry"
        )
        assert results[0]["title"] == "fix_python_module_not_found"
        assert results[0]["status"] == "verified"
    finally:
        mem.close()
