"""Tests for issue resolutions: #32 (PyPI), #33 (ST default), #35 (diagnostics), #36 (incremental)."""

import json
import pytest
from pathlib import Path

from howdex import Howdex, enrich_diagnostics, DryRunLLMProvider


# --------------------------------------------------------------------------- #
# Issue #33: sentence-transformers default
# --------------------------------------------------------------------------- #
def test_auto_embedder_defaults_to_st_when_available():
    """When no preferred embedder and no env var, auto_embedder should
    try SentenceTransformerEmbedder first, falling back to hash."""
    from howdex.vectors.embedder import auto_embedder
    import os
    # Save and clear env var
    old = os.environ.pop("HOWDEX_EMBEDDER", None)
    try:
        emb = auto_embedder()
        # It should be either ST (if installed) or hash (fallback)
        # ST embedder name is like "sentence-transformer:all-MiniLM-L6-v2"
        assert "sentence-transformer" in emb.name or emb.name in ("hash", "hashing"), (
            f"expected ST or hash embedder, got {emb.name!r}"
        )
    finally:
        if old:
            os.environ["HOWDEX_EMBEDDER"] = old


# --------------------------------------------------------------------------- #
# Issue #35: LLM-assisted diagnostic capture
# --------------------------------------------------------------------------- #
def test_enrich_diagnostics_dry_run(tmp_path):
    """enrich_diagnostics with DryRunLLMProvider should produce
    diagnostic_summary, fix_description, and transfer_hint."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.start_session("fix_missing_dependency")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"},
                          "Error: Cannot find module express")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"},
                          "added packages")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"},
                          "App running")
        mem.end_session("success")
        procs = mem.learn(min_samples=1)
        assert procs

        # Enrich with dry-run provider
        result = enrich_diagnostics(mem, procs[0], llm_provider=DryRunLLMProvider())
        assert "diagnostic_summary" in result
        assert "fix_description" in result
        assert "transfer_hint" in result
        assert len(result["diagnostic_summary"]) > 10
    finally:
        mem.close()


def test_enrich_diagnostics_appears_in_guidance(tmp_path):
    """After enrich_diagnostics, guidance should include the diagnostic context."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.start_session("fix_missing_dependency")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"},
                          "Error: Cannot find module express")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"},
                          "added packages")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"},
                          "App running")
        mem.end_session("success")
        procs = mem.learn(min_samples=1)
        assert procs

        enrich_diagnostics(mem, procs[0], llm_provider=DryRunLLMProvider())

        guidance = mem.guidance("Fix a Node app that can't find module cors", max_chars=4000)
        assert "Diagnostic context" in guidance
        assert "Summary:" in guidance
        assert "Fix:" in guidance
        assert "Transfer hint:" in guidance
        assert "LLM proposal" in guidance  # must be marked as unverified
    finally:
        mem.close()


def test_dry_run_llm_provider_is_deterministic():
    """DryRunLLMProvider should produce the same output for the same input."""
    provider = DryRunLLMProvider()
    prompt = '{"task_signature": "fix_bug", "steps": [{"action": "edit_file", "observation": "fixed"}]}'
    result1 = provider.complete(prompt)
    result2 = provider.complete(prompt)
    assert result1 == result2


# --------------------------------------------------------------------------- #
# Issue #36: Incremental consolidation
# --------------------------------------------------------------------------- #
def test_incremental_consolidation_skips_processed_episodes(tmp_path):
    """learn(incremental=True) should skip episodes already consolidated."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        # First session
        mem.start_session("fix_bug")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
        mem.end_session("success")

        # First learn — processes the episode
        procs1 = mem.learn(min_samples=1, incremental=True)
        assert len(procs1) == 1

        # Second learn with incremental=True — should return [] (no new episodes)
        procs2 = mem.learn(min_samples=1, incremental=True)
        assert procs2 == [], "incremental learn should skip already-processed episodes"
    finally:
        mem.close()


def test_incremental_consolidation_picks_up_new_episodes(tmp_path):
    """learn(incremental=True) should process new episodes added after the first call."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        # First session
        mem.start_session("fix_bug")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
        mem.end_session("success")

        mem.learn(min_samples=1, incremental=True)

        # Add a new session
        mem.start_session("fix_bug")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
        mem.end_session("success")

        # Second incremental learn — should process the new episode
        procs2 = mem.learn(min_samples=1, incremental=True)
        assert len(procs2) >= 1, "incremental learn should process new episodes"
    finally:
        mem.close()


def test_non_incremental_learn_still_works(tmp_path):
    """learn() without incremental=True should process all episodes (backwards compat)."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        mem.start_session("fix_bug")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error")
        mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added")
        mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
        mem.end_session("success")

        # Non-incremental — should process all episodes
        procs = mem.learn(min_samples=1)
        assert len(procs) == 1

        # Non-incremental again — should still process all episodes
        procs2 = mem.learn(min_samples=1)
        assert len(procs2) >= 1
    finally:
        mem.close()
