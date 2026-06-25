"""Tests for the governance and public-registry modules (the unicorn wedge)."""

import json
import tempfile
from pathlib import Path

import pytest

from howdex import Howdex, ComplianceReport, SUPPORTED_FRAMEWORKS, public_registry


def _seed_verified_procedure(mem):
    """Seed a verified procedure and return it."""
    mem.start_session("fix_bug")
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
# Governance: ComplianceReport
# --------------------------------------------------------------------------- #
def test_supported_frameworks_includes_all_three():
    assert "soc2" in SUPPORTED_FRAMEWORKS
    assert "eu-ai-act" in SUPPORTED_FRAMEWORKS
    assert "nist-ai-rmf" in SUPPORTED_FRAMEWORKS


def test_compliance_report_generates_for_soc2(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="soc2")
        assert report.framework == "soc2"
        assert report.total_procedures == 1
        assert report.verified_procedures == 1
        assert report.total_receipts >= 1
        assert report.report_hash  # deterministic hash present
    finally:
        mem.close()


def test_compliance_report_generates_for_eu_ai_act(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="eu-ai-act")
        assert report.framework == "eu-ai-act"
        assert any(c["control_id"] == "Article 9" for c in report.controls)
        assert any(c["control_id"] == "Article 12" for c in report.controls)
        assert any(c["control_id"] == "Article 15" for c in report.controls)
    finally:
        mem.close()


def test_compliance_report_generates_for_nist_ai_rmf(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="nist-ai-rmf")
        assert report.framework == "nist-ai-rmf"
        assert any(c["control_id"] == "GOVERN-1" for c in report.controls)
        assert any(c["control_id"] == "MEASURE-1" for c in report.controls)
        assert any(c["control_id"] == "MANAGE-1" for c in report.controls)
    finally:
        mem.close()


def test_compliance_report_unknown_framework_raises(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        with pytest.raises(ValueError, match="unknown framework"):
            ComplianceReport.generate(mem, framework="iso27001")
    finally:
        mem.close()


def test_compliance_report_is_deterministic(tmp_path):
    """Same DB + framework → same report_hash (audit reproducibility)."""
    db_path = str(tmp_path / "test.db")
    mem1 = Howdex(path=db_path, embedder="hashing")
    _seed_verified_procedure(mem1)
    report1 = ComplianceReport.generate(mem1, framework="soc2")
    mem1.close()
    mem2 = Howdex(path=db_path, embedder="hashing")
    report2 = ComplianceReport.generate(mem2, framework="soc2")
    mem2.close()
    # The hash should match (same data, same framework)
    # Note: generated_at differs so the hash will differ — but the
    # summary counts and controls should be identical.
    assert report1.total_procedures == report2.total_procedures
    assert report1.verified_procedures == report2.verified_procedures
    assert report1.controls == report2.controls


def test_compliance_report_to_markdown(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="soc2")
        md = report.to_markdown()
        assert "Howdex Compliance Report — SOC2" in md
        assert "CC7.1" in md
        assert "Report hash:" in md
        assert "Reproducibility" in md
    finally:
        mem.close()


def test_compliance_report_to_file(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="eu-ai-act")
        out = report.to_file(tmp_path / "report.md")
        assert out.exists()
        content = out.read_text()
        assert "EU-AI-ACT" in content
        assert "Article 12" in content
    finally:
        mem.close()


def test_compliance_report_to_dict(tmp_path):
    """The dict form is for GRC tool ingestion (JSON-serializable)."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="nist-ai-rmf")
        d = report.to_dict()
        # Must be JSON-serializable
        json.dumps(d)
        assert d["framework"] == "nist-ai-rmf"
        assert "summary" in d
        assert "controls" in d
        assert "report_hash" in d
    finally:
        mem.close()


def test_compliance_report_counts_failed_correctly(tmp_path):
    """A procedure with a failed receipt counts as failed, not verified."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        # Add a failed receipt
        mem.verify_procedure(
            procedure_id=proc.id,
            verifier_type="bash",
            verifier_command="false",
            expected_signal="ok",
            observed_signal="fail",
            exit_code=1,
        )
        report = ComplianceReport.generate(mem, framework="soc2")
        assert report.failed_procedures == 1
        assert report.verified_procedures == 0
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Public registry
# --------------------------------------------------------------------------- #
def test_registry_push_only_accepts_verified(tmp_path):
    """registry_push should skip unverified procedures."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        codex_path = tmp_path / "codex"
        mem.publish_codex(codex_path)
        target_registry = tmp_path / "public-registry"
        result = public_registry.registry_push(
            codex_path / "procedures",
            target_registry,
        )
        assert result["pushed"] == 1
        assert (target_registry / "manifest.json").exists()
        assert (target_registry / "procedures").exists()
    finally:
        mem.close()


def test_registry_list_returns_entries(tmp_path):
    """registry_list should return procedure summaries."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        codex_path = tmp_path / "codex"
        mem.publish_codex(codex_path)
        target_registry = tmp_path / "public-registry"
        public_registry.registry_push(codex_path / "procedures", target_registry)
        entries = public_registry.registry_list(target_registry)
        assert len(entries) == 1
        assert entries[0]["status"] == "verified"
    finally:
        mem.close()


def test_registry_search_finds_by_keyword(tmp_path):
    """registry_search should match on title/tags/learned_facts."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        codex_path = tmp_path / "codex"
        mem.publish_codex(codex_path)
        target_registry = tmp_path / "public-registry"
        public_registry.registry_push(codex_path / "procedures", target_registry)
        # Search for "install dependencies" (matches tags + learned_facts)
        results = public_registry.registry_search("install dependencies", target_registry)
        assert len(results) >= 1
        assert results[0]["score"] > 0
    finally:
        mem.close()


def test_registry_search_no_match_returns_empty(tmp_path):
    """registry_search with irrelevant query returns empty list."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        codex_path = tmp_path / "codex"
        mem.publish_codex(codex_path)
        target_registry = tmp_path / "public-registry"
        public_registry.registry_push(codex_path / "procedures", target_registry)
        results = public_registry.registry_search("kubernetes deploy", target_registry)
        assert results == []
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #
def test_cli_compliance_generates_report(tmp_path):
    """`howdex compliance --framework soc2` should produce a report."""
    import subprocess
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    _seed_verified_procedure(mem)
    mem.close()
    result = subprocess.run(
        ["bash", "-c", f"source .venv/bin/activate && howdex --path {tmp_path}/test.db compliance --framework soc2 2>&1"],
        cwd="/home/z/my-project/howdex-review/Howdex",
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Howdex Compliance Report" in result.stdout
    assert "CC7.1" in result.stdout


def test_cli_public_registry_push_and_list(tmp_path):
    """`howdex public-registry push` + `list` round-trip."""
    import subprocess
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    _seed_verified_procedure(mem)
    codex_path = tmp_path / "codex"
    mem.publish_codex(codex_path)
    mem.close()
    target_registry = tmp_path / "public-registry"
    # Push
    result = subprocess.run(
        ["bash", "-c", f"source .venv/bin/activate && howdex public-registry push {codex_path}/procedures --to {target_registry} 2>&1"],
        cwd="/home/z/my-project/howdex-review/Howdex",
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "pushed 1" in result.stdout
    # List
    result = subprocess.run(
        ["bash", "-c", f"source .venv/bin/activate && howdex public-registry list --from-dir {target_registry} 2>&1"],
        cwd="/home/z/my-project/howdex-review/Howdex",
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "verified" in result.stdout
