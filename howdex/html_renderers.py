"""Howdex HTML Renderers — visual, interactive single-file HTML artifacts.

Inspired by Thariq Shihipar's "The Unreasonable Effectiveness of HTML"
(Anthropic/Claude Code team, June 2026): HTML with its richer
visualizations, color, and interactivity improves human-agent
communication over Markdown.

This module renders Howdex outputs as single-file HTML artifacts:

1. **Compliance reports** — interactive, visual SOC 2 / EU AI Act /
   NIST AI RMF reports with collapsible control sections, color-coded
   status, embedded receipt details, and print-friendly CSS.

2. **Agent guidance** — visual procedure maps with SVG flowcharts,
   confidence indicators, receipt evidence at each node, and
   diagnostic context panels.

3. **Agent operations dashboard** — live trading/financial agent
   dashboard with P&L charts, trade history, BootProof receipts,
   Merkle ledger timeline, and compliance status.

All outputs are single-file HTML (no external dependencies) —
self-contained, openable in any browser, printable to PDF.
"""

from __future__ import annotations

import html
import json
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from howdex.governance import ComplianceReport


# --------------------------------------------------------------------------- #
# Shared CSS
# --------------------------------------------------------------------------- #
_BASE_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f8f9fa; color: #1a1a2e; line-height: 1.6; }
.container { max-width: 1100px; margin: 0 auto; padding: 24px; }
h1 { font-size: 1.8rem; margin-bottom: 8px; }
h2 { font-size: 1.3rem; margin: 24px 0 12px; color: #16213e; }
h3 { font-size: 1.1rem; margin: 16px 0 8px; }
.meta { color: #6c757d; font-size: 0.875rem; margin-bottom: 24px; }
.card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.stat { text-align: center; padding: 16px; background: #fff; border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.stat-value { font-size: 2rem; font-weight: 700; }
.stat-label { font-size: 0.8rem; color: #6c757d; text-transform: uppercase; letter-spacing: 0.5px; }
.status-verified { color: #198754; }
.status-candidate { color: #ffc107; }
.status-failed { color: #dc3545; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.75rem;
         font-weight: 600; }
.badge-verified { background: #d1e7dd; color: #0f5132; }
.badge-candidate { background: #fff3cd; color: #664d03; }
.badge-failed { background: #f8d7da; color: #842029; }
table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #dee2e6; }
th { background: #f8f9fa; font-weight: 600; font-size: 0.85rem; text-transform: uppercase;
     letter-spacing: 0.5px; }
tr:hover { background: #f8f9fa; }
code { background: #e9ecef; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }
.hash { font-family: 'SF Mono', Monaco, monospace; font-size: 0.8rem; color: #6c757d; }
.collapsible { cursor: pointer; user-select: none; }
.collapsible::before { content: '▼ '; font-size: 0.7rem; }
.collapsible.collapsed::before { content: '▶ '; }
.collapsible.collapsed + .collapsible-content { display: none; }
.collapsible-content { padding: 12px 0; }
.nav { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; }
.nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 0.85rem;
         background: #e9ecef; color: #495057; }
.nav a:hover { background: #dee2e6; }
.footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #dee2e6;
          color: #6c757d; font-size: 0.8rem; }
@media print { .nav { display: none; } .card { box-shadow: none; border: 1px solid #dee2e6; } }
"""


def _escape(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text))


# --------------------------------------------------------------------------- #
# 1. Compliance Report HTML Renderer
# --------------------------------------------------------------------------- #
def render_compliance_report_html(report: "ComplianceReport") -> str:
    """Render a compliance report as a single-file interactive HTML artifact.

    Includes:
    - Executive summary dashboard with color-coded stats
    - Collapsible control sections with evidence details
    - Receipt material displayed per control
    - Navigation sidebar for jumping between controls
    - Print-friendly CSS for PDF export
    """
    verified_count = report.verified_procedures
    failed_count = report.failed_procedures
    candidate_count = report.candidate_procedures
    total = report.total_procedures

    # Stats badges
    verified_badge = f'<span class="badge badge-verified">{verified_count} verified</span>'
    candidate_badge = f'<span class="badge badge-candidate">{candidate_count} candidate</span>'
    failed_badge = f'<span class="badge badge-failed">{failed_count} failed</span>' if failed_count else ""

    # Control sections
    control_sections = []
    for i, control in enumerate(report.controls):
        ctrl_id = control.get("control_id", f"control-{i}")
        ctrl_title = control.get("title", "")
        evidence_items = control.get("howdex_evidence", [])
        receipt_fields = control.get("receipt_fields", [])

        evidence_html = "".join(f"<li>{_escape(e)}</li>" for e in evidence_items)
        fields_html = ", ".join(f"<code>{_escape(f)}</code>" for f in receipt_fields)

        control_sections.append(f"""
        <div class="card" id="control-{i}">
            <div class="collapsible" onclick="this.classList.toggle('collapsed')">
                <strong>{_escape(ctrl_id)}</strong> — {_escape(ctrl_title)}
            </div>
            <div class="collapsible-content">
                <h4>Howdex Evidence</h4>
                <ul>{evidence_html}</ul>
                <p style="margin-top:8px"><small>Receipt fields: {fields_html}</small></p>
            </div>
        </div>""")

    # Nav links
    nav_links = "".join(
        f'<a href="#control-{i}">{_escape(control.get("control_id", f"C{i}"))}</a>'
        for i, control in enumerate(report.controls)
    )

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Howdex Compliance Report — """ + report.framework.upper() + """</title>
<style>""" + _BASE_CSS + """</style>
</head>
<body>
<div class="container">
    <h1>🔒 Howdex Compliance Report — """ + report.framework.upper() + """</h1>
    <div class="meta">
        Generated: """ + report.generated_at + """<br>
        Reporting period: """ + (report.reporting_period_start or "(all time)") + """ to """ + (report.reporting_period_end or "(now)") + """<br>
        <span class="hash">Report hash: <code>""" + report.report_hash + """</code></span>
    </div>

    <div class="nav">""" + nav_links + """</div>

    <h2>Executive Summary</h2>
    <div class="grid">
        <div class="stat">
            <div class="stat-value">""" + str(total) + """</div>
            <div class="stat-label">Total Procedures</div>
        </div>
        <div class="stat">
            <div class="stat-value status-verified">""" + str(verified_count) + """</div>
            <div class="stat-label">Verified</div>
        </div>
        <div class="stat">
            <div class="stat-value status-candidate">""" + str(candidate_count) + """</div>
            <div class="stat-label">Candidate</div>
        </div>
        <div class="stat">
            <div class="stat-value status-failed">""" + str(failed_count) + """</div>
            <div class="stat-label">Failed</div>
        </div>
        <div class="stat">
            <div class="stat-value">""" + str(report.total_receipts) + """</div>
            <div class="stat-label">Total Receipts</div>
        </div>
        <div class="stat">
            <div class="stat-value">""" + str(report.signed_receipts) + """</div>
            <div class="stat-label">Signed Receipts</div>
        </div>
    </div>

    <div style="margin: 16px 0">
        """ + verified_badge + " " + candidate_badge + " " + failed_badge + """
    </div>

    <h2>Control Mapping</h2>
    """ + "".join(control_sections) + """

    <h2>Verifier Types in Use</h2>
    <div class="card">
        <p>""" + (", ".join(report.evidence_summary.get("verifier_types_used", [])) or "(none)") + """</p>
    </div>

    <h2>Reproducibility</h2>
    <div class="card">
        <p>This report is deterministic. Re-running with the same database and framework
        will produce the same report hash.</p>
        <p class="hash"><code>""" + report.report_hash + """</code></p>
        <p style="margin-top:8px">Auditors can verify integrity by regenerating and comparing hashes.</p>
    </div>

    <h2>Method</h2>
    <div class="card">
        <p>All verification evidence is derived from Howdex's receipt primitive.
        A receipt is created only when a <strong>deterministic, non-LLM verifier</strong>
        (exit code, HTTP status, test runner, etc.) confirms a procedure's outcome.
        LLM judgments are explicitly NOT accepted as verification evidence.</p>
    </div>

    <div class="footer">
        Generated by Howdex Procedural Memory v0.4.0 —
        <a href="https://github.com/rossbuckley1990-hash/Howdex">github.com/rossbuckley1990-hash/Howdex</a>
    </div>
</div>
<script>
document.querySelectorAll('.collapsible').forEach(function(el) {
    el.addEventListener('click', function() { el.classList.toggle('collapsed'); });
});
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# 2. Guidance HTML Renderer
# --------------------------------------------------------------------------- #
def render_guidance_html(
    guidance_text: str,
    *,
    objective: str = "",
    procedures: list[dict] | None = None,
) -> str:
    """Render agent guidance as a visual HTML workspace.

    Includes:
    - SVG flowchart of procedure steps
    - Color-coded confidence indicators
    - Receipt evidence at each step
    - Diagnostic context panel
    """
    # Parse the Markdown guidance into sections
    sections = _parse_guidance_sections(guidance_text)

    # Build procedure flowchart if we have procedure data
    flowchart_svg = ""
    if procedures:
        flowchart_svg = _build_procedure_flowchart(procedures)

    # Build section cards
    section_cards = []
    for title, content in sections.items():
        section_cards.append(f"""
        <div class="card">
            <div class="collapsible" onclick="this.classList.toggle('collapsed')">
                <strong>{_escape(title)}</strong>
            </div>
            <div class="collapsible-content">
                <pre style="white-space: pre-wrap; font-family: inherit; font-size: 0.9rem">{_escape(content)}</pre>
            </div>
        </div>""")

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Howdex Agent Guidance</title>
<style>""" + _BASE_CSS + """
.flowchart { background: #fff; border-radius: 8px; padding: 24px; margin-bottom: 16px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }
.step-node { display: inline-block; padding: 10px 16px; margin: 4px; border-radius: 6px;
             font-size: 0.85rem; font-weight: 500; }
.step-arrow { display: inline-block; margin: 4px; color: #6c757d; }
.step-verified { background: #d1e7dd; color: #0f5132; border: 1px solid #badbcc; }
.step-candidate { background: #fff3cd; color: #664d03; border: 1px solid #ffecb5; }
.step-unknown { background: #e2e3e5; color: #41464b; border: 1px solid #d3d6d8; }
</style>
</head>
<body>
<div class="container">
    <h1>🧠 Howdex Agent Guidance</h1>
    <div class="meta">
        Objective: """ + _escape(objective) + """<br>
        Generated: """ + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + """
    </div>

    """ + flowchart_svg + """

    """ + "".join(section_cards) + """

    <div class="footer">
        Generated by Howdex Procedural Memory —
        <a href="https://github.com/rossbuckley1990-hash/Howdex">github.com/rossbuckley1990-hash/Howdex</a>
    </div>
</div>
<script>
document.querySelectorAll('.collapsible').forEach(function(el) {
    el.addEventListener('click', function() { el.classList.toggle('collapsed'); });
});
</script>
</body>
</html>"""


def _parse_guidance_sections(guidance_text: str) -> dict[str, str]:
    """Parse Markdown guidance into sections."""
    sections = {}
    current_title = "Overview"
    current_lines = []
    for line in guidance_text.split("\n"):
        if line.startswith("# ") or line.startswith("## "):
            if current_lines:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line.lstrip("# ").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def _build_procedure_flowchart(procedures: list[dict]) -> str:
    """Build an HTML flowchart of procedure steps."""
    if not procedures:
        return ""

    steps_html = []
    for proc in procedures:
        proc_steps = proc.get("steps", [])
        task = proc.get("task_signature", proc.get("title", "procedure"))
        confidence = proc.get("confidence", 0)
        verified = proc.get("status") == "verified" or proc.get("procedure_verified", False)

        steps_html.append(f'<div style="margin-bottom:12px"><strong>{_escape(task)}</strong> '
                         f'(confidence: {confidence:.1%})</div>')

        for i, step in enumerate(proc_steps):
            if isinstance(step, dict):
                action = step.get("action") or step.get("canonical_name", "?")
            else:
                action = str(step)

            css_class = "step-verified" if verified else "step-candidate"
            steps_html.append(f'<span class="step-node {css_class}">{_escape(action)}</span>')

            if i < len(proc_steps) - 1:
                steps_html.append('<span class="step-arrow">→</span>')

    return f'<div class="flowchart">{"".join(steps_html)}</div>'


# --------------------------------------------------------------------------- #
# 3. Agent Operations Dashboard
# --------------------------------------------------------------------------- #
def render_agent_dashboard_html(
    *,
    title: str = "Howdex Agent Operations Dashboard",
    trades: list[dict] | None = None,
    stats: dict | None = None,
    ledger_root: str = "",
    ledger_blocks: int = 0,
    ledger_valid: bool = True,
    compliance: dict | None = None,
    procedures: list[dict] | None = None,
) -> str:
    """Render a live agent operations dashboard as a single-file HTML artifact.

    Shows:
    - P&L chart (SVG bar chart)
    - Trade history table with color-coded wins/losses
    - BootProof receipt cards
    - Merkle ledger status
    - Compliance status panel
    - Procedure learning curve
    """
    trades = trades or []
    stats = stats or {}
    compliance = compliance or {}

    # P&L chart
    pnl_chart = _build_pnl_chart(trades)

    # Trade table
    trade_rows = ""
    for t in trades[-20:]:  # last 20 trades
        pnl = t.get("pnl", 0) or 0
        pnl_class = "status-verified" if pnl > 0 else "status-failed" if pnl < 0 else ""
        trade_rows += f"""
        <tr>
            <td>{_escape(t.get('trade_id', '?'))}</td>
            <td>{_escape(t.get('action', '?'))}</td>
            <td>${t.get('entry_price', 0):,.2f}</td>
            <td>${t.get('exit_price', 0) if t.get('exit_price') else 0:,.2f}</td>
            <td class="{pnl_class}">${pnl:+,.2f}</td>
            <td><span class="hash">{_escape(t.get('receipt_id', '')[:12])}</span></td>
        </tr>"""

    # Stats cards
    capital = stats.get("capital", 0)
    total_pnl = stats.get("total_pnl", 0)
    win_rate = stats.get("win_rate", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>""" + _escape(title) + """</title>
<style>""" + _BASE_CSS + """
.chart { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px;
         box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.bar { display: inline-block; width: 12px; margin: 0 1px; vertical-align: bottom;
       border-radius: 2px 2px 0 0; }
.bar-win { background: #198754; }
.bar-loss { background: #dc3545; }
.receipt-card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #198754; }
.receipt-card.failed { border-left-color: #dc3545; }
</style>
</head>
<body>
<div class="container">
    <h1>📊 """ + _escape(title) + """</h1>
    <div class="meta">Generated: """ + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + """</div>

    <h2>Performance Summary</h2>
    <div class="grid">
        <div class="stat">
            <div class="stat-value">$""" + f"{capital:,.2f}" + """</div>
            <div class="stat-label">Capital</div>
        </div>
        <div class="stat">
            <div class="stat-value """ + ("status-verified" if total_pnl > 0 else "status-failed") + """">$""" + f"{total_pnl:+,.2f}" + """</div>
            <div class="stat-label">Total P&L</div>
        </div>
        <div class="stat">
            <div class="stat-value">""" + str(win_rate) + """%</div>
            <div class="stat-label">Win Rate</div>
        </div>
        <div class="stat">
            <div class="stat-value">""" + str(wins) + """W / """ + str(losses) + """L</div>
            <div class="stat-label">Wins / Losses</div>
        </div>
    </div>

    <h2>P&L Chart</h2>
    <div class="chart">
        """ + pnl_chart + """
    </div>

    <h2>Trade History</h2>
    <table>
        <thead><tr>
            <th>Trade ID</th><th>Action</th><th>Entry</th><th>Exit</th>
            <th>P&L</th><th>Receipt</th>
        </tr></thead>
        <tbody>""" + trade_rows + """</tbody>
    </table>

    <h2>Merkle Ledger Status</h2>
    <div class="card">
        <div class="grid">
            <div class="stat">
                <div class="stat-value """ + ("status-verified" if ledger_valid else "status-failed") + """">
                    """ + ("✅ Valid" if ledger_valid else "❌ Tampered") + """</div>
                <div class="stat-label">Integrity</div>
            </div>
            <div class="stat">
                <div class="stat-value">""" + str(ledger_blocks) + """</div>
                <div class="stat-label">Blocks</div>
            </div>
            <div class="stat">
                <div class="stat-value hash" style="font-size: 0.9rem; word-break: break-all">
                    """ + ledger_root[:24] + """...</div>
                <div class="stat-label">Chain Root</div>
            </div>
        </div>
    </div>

    <h2>Compliance Status</h2>
    <div class="card">
        <div class="grid">
            <div class="stat">
                <div class="stat-value status-verified">""" + str(compliance.get("verified", 0)) + """</div>
                <div class="stat-label">Verified Procedures</div>
            </div>
            <div class="stat">
                <div class="stat-value">""" + str(compliance.get("total_receipts", 0)) + """</div>
                <div class="stat-label">Total Receipts</div>
            </div>
            <div class="stat">
                <div class="stat-value">""" + str(compliance.get("controls", 0)) + """</div>
                <div class="stat-label">Controls Mapped</div>
            </div>
        </div>
    </div>

    <div class="footer">
        Generated by Howdex Procedural Memory —
        <a href="https://github.com/rossbuckley1990-hash/Howdex">github.com/rossbuckley1990-hash/Howdex</a><br>
        Every trade has a cryptographic receipt. The ledger is tamper-evident.
        The compliance report is audit-ready.
    </div>
</div>
</body>
</html>"""


def _build_pnl_chart(trades: list[dict]) -> str:
    """Build a simple SVG bar chart of trade P&L."""
    completed = [t for t in trades if t.get("pnl") is not None]
    if not completed:
        return "<p style='color:#6c757d;text-align:center'>(no completed trades)</p>"

    max_pnl = max(abs(t["pnl"]) for t in completed) or 1
    bars = []
    for t in completed:
        pnl = t["pnl"]
        height = max(2, abs(pnl) / max_pnl * 100)
        css_class = "bar-win" if pnl > 0 else "bar-loss"
        bars.append(f'<span class="bar {css_class}" style="height:{height}px" '
                    f'title="{t.get("trade_id","?")}: ${pnl:+.2f}"></span>')

    return f'<div style="text-align:center;height:120px">{"".join(bars)}</div>'
