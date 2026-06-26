"""Tests for HTML renderers — compliance reports, guidance, dashboard."""

import pytest
from pathlib import Path

from howdex import Howdex, ComplianceReport
from howdex.html_renderers import (
    render_compliance_report_html,
    render_guidance_html,
    render_agent_dashboard_html,
)


def _seed_verified_procedure(mem):
    mem.start_session("fix_missing_dependency")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error: Cannot find module express")
    mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added packages")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
    mem.end_session("success")
    procs = mem.learn(min_samples=1)
    mem.verify_procedure(
        procedure_id=procs[0].id,
        verifier_type="bash",
        verifier_command="node app.js | grep -q 'App running'",
        expected_signal="App running",
        observed_signal="App running",
        exit_code=0,
    )
    return procs[0]


# --------------------------------------------------------------------------- #
# Compliance report HTML
# --------------------------------------------------------------------------- #
def test_compliance_report_html_contains_doctype(tmp_path):
    """HTML report should be a valid HTML document."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="soc2")
        html = report.to_html()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
    finally:
        mem.close()


def test_compliance_report_html_contains_framework_title(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="eu-ai-act")
        html = report.to_html()
        assert "EU-AI-ACT" in html
    finally:
        mem.close()


def test_compliance_report_html_contains_stats(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="soc2")
        html = report.to_html()
        assert "Total Procedures" in html
        assert "Verified" in html
        assert "Total Receipts" in html
        assert "Report hash" in html
    finally:
        mem.close()


def test_compliance_report_html_contains_controls(tmp_path):
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="soc2")
        html = report.to_html()
        assert "CC7.1" in html
        assert "CC8.1" in html
        assert "Howdex Evidence" in html
        assert "collapsible" in html
    finally:
        mem.close()


def test_compliance_report_to_file_html_extension(tmp_path):
    """to_file with .html extension should write HTML."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="soc2")
        path = report.to_file(tmp_path / "report.html")
        content = path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "SOC2" in content
    finally:
        mem.close()


def test_compliance_report_to_file_md_extension_still_works(tmp_path):
    """to_file with .md extension should still write Markdown."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        _seed_verified_procedure(mem)
        report = ComplianceReport.generate(mem, framework="soc2")
        path = report.to_file(tmp_path / "report.md")
        content = path.read_text()
        assert "# Howdex Compliance Report" in content
        assert "<!DOCTYPE" not in content
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Guidance HTML
# --------------------------------------------------------------------------- #
def test_guidance_html_contains_doctype():
    """Guidance HTML should be a valid HTML document."""
    guidance = "# HOWDEX OPERATIONAL MEMORY\n\nObjective: Fix a bug\n\nRelevant memory:\n- fix_bug"
    html = render_guidance_html(guidance, objective="Fix a bug")
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html


def test_guidance_html_contains_objective():
    guidance = "# HOWDEX OPERATIONAL MEMORY\n\nRules:\n- Do the thing"
    html = render_guidance_html(guidance, objective="Fix a Node app")
    assert "Fix a Node app" in html


def test_guidance_html_with_procedures_has_flowchart():
    """When procedures are provided, the HTML should include a flowchart."""
    guidance = "# HOWDEX OPERATIONAL MEMORY\n\nRelevant memory:\n- fix_bug"
    procedures = [
        {
            "task_signature": "fix_bug",
            "confidence": 0.9,
            "status": "verified",
            "steps": [
                {"action": "read_file"},
                {"action": "edit_file"},
                {"action": "run_tests"},
            ],
        }
    ]
    html = render_guidance_html(guidance, objective="Fix a bug", procedures=procedures)
    assert "flowchart" in html
    assert "read_file" in html
    assert "edit_file" in html
    assert "run_tests" in html
    assert "step-verified" in html  # verified procedure → green


# --------------------------------------------------------------------------- #
# Agent dashboard HTML
# --------------------------------------------------------------------------- #
def test_dashboard_html_contains_doctype():
    html = render_agent_dashboard_html(
        title="Test Dashboard",
        stats={"capital": 100000, "total_pnl": 1000, "win_rate": 60, "wins": 6, "losses": 4},
    )
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html


def test_dashboard_html_contains_stats():
    html = render_agent_dashboard_html(
        stats={"capital": 100000, "total_pnl": 1500, "win_rate": 65, "wins": 13, "losses": 7},
    )
    assert "$100,000.00" in html
    assert "1,500.00" in html  # formatted P&L
    assert "65%" in html
    assert "13W / 7L" in html


def test_dashboard_html_contains_trades():
    trades = [
        {"trade_id": "TRD-001", "action": "BUY", "entry_price": 50000, "exit_price": 51000, "pnl": 200, "receipt_id": "abc123"},
        {"trade_id": "TRD-002", "action": "SELL", "entry_price": 51000, "exit_price": 50500, "pnl": -100, "receipt_id": "def456"},
    ]
    html = render_agent_dashboard_html(trades=trades)
    assert "TRD-001" in html
    assert "TRD-002" in html
    assert "BUY" in html
    assert "SELL" in html
    assert "$200.00" in html or "$+200.00" in html


def test_dashboard_html_contains_ledger_status():
    html = render_agent_dashboard_html(
        ledger_root="abc123def456",
        ledger_blocks=42,
        ledger_valid=True,
    )
    assert "✅ Valid" in html
    assert "42" in html
    assert "Chain Root" in html


def test_dashboard_html_contains_compliance():
    html = render_agent_dashboard_html(
        compliance={"verified": 3, "total_receipts": 5, "controls": 4},
    )
    assert "Verified Procedures" in html
    assert "3" in html


def test_dashboard_html_has_pnl_chart():
    trades = [
        {"trade_id": f"TRD-{i}", "action": "BUY", "entry_price": 50000,
         "exit_price": 50000 + i * 100, "pnl": i * 100 - 200, "receipt_id": f"r{i}"}
        for i in range(5)
    ]
    html = render_agent_dashboard_html(trades=trades)
    assert "P&L Chart" in html
    assert "bar" in html  # has chart bars


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #
def test_cli_compliance_html_format(tmp_path):
    """`howdex compliance --framework soc2 --format html` should output HTML."""
    import subprocess, sys
    db = tmp_path / "test.db"
    mem = Howdex(path=str(db), embedder="hashing")
    _seed_verified_procedure(mem)
    mem.close()
    result = subprocess.run(
        [sys.executable, "-m", "howdex.cli", "--path", str(db),
         "--embedder", "hashing", "compliance", "--framework", "soc2", "--format", "html"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "<!DOCTYPE html>" in result.stdout
    assert "SOC2" in result.stdout


def test_cli_compliance_html_output_file(tmp_path):
    """`howdex compliance --framework soc2 --output report.html` should write HTML."""
    import subprocess, sys
    db = tmp_path / "test.db"
    mem = Howdex(path=str(db), embedder="hashing")
    _seed_verified_procedure(mem)
    mem.close()
    output = tmp_path / "report.html"
    result = subprocess.run(
        [sys.executable, "-m", "howdex.cli", "--path", str(db),
         "--embedder", "hashing", "compliance", "--framework", "soc2",
         "--output", str(output)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert output.exists()
    content = output.read_text()
    assert "<!DOCTYPE html>" in content
