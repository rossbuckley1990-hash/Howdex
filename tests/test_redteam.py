"""Tests for the Howdex red-team harness.

These tests assert that:

1. Every vector in ATTACK_LIBRARY runs cleanly against a fresh Howdex
   instance and produces a structured AttackResult.
2. Each defense holds — i.e. every result is classified ``blocked`` or
   ``review`` (never ``vulnerable``). If a vector returns ``vulnerable``,
   the corresponding defense in Howdex is broken and the test fails loud.
3. The harness API is stable: ``RedTeamHarness.run_all()``,
   ``RedTeamHarness.run_vector(id)``, and the report renderers
   (``to_text``, ``to_markdown``, ``to_json``, ``to_html``) all work.
4. The CLI ``howdex redteam run|list|show`` works end-to-end.

These tests are deterministic — no LLM, no network. Safe to run in CI.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from howdex.redteam import (
    ATTACK_LIBRARY,
    AttackResult,
    AttackVector,
    RedTeamHarness,
    RedTeamReport,
    CLASS_BLOCKED,
    CLASS_REVIEW,
    CLASS_VULNERABLE,
    get_vector,
    list_vectors,
)
from howdex.html_renderers import render_redteam_report_html


# --------------------------------------------------------------------------- #
# Attack library structure
# --------------------------------------------------------------------------- #
def test_attack_library_is_non_empty():
    """The library must ship with a canonical set of attack vectors."""
    assert len(ATTACK_LIBRARY) >= 10, (
        f"expected at least 10 canonical vectors, got {len(ATTACK_LIBRARY)}"
    )


def test_attack_library_ids_are_unique():
    """Every vector id must be unique — operators use them as filter keys."""
    ids = [v.id for v in ATTACK_LIBRARY]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"


def test_attack_library_metadata_is_complete():
    """Each vector must have id, name, threat_model, expected, remediation."""
    for v in ATTACK_LIBRARY:
        assert v.id, "vector missing id"
        assert v.name, f"vector {v.id} missing name"
        assert v.threat_model, f"vector {v.id} missing threat_model"
        assert v.expected, f"vector {v.id} missing expected"
        assert v.remediation, f"vector {v.id} missing remediation"
        assert callable(v.runner), f"vector {v.id} runner is not callable"


def test_list_vectors_returns_dicts():
    """``list_vectors()`` returns plain dicts (CLI-safe, JSON-serializable)."""
    vectors = list_vectors()
    assert len(vectors) == len(ATTACK_LIBRARY)
    for v in vectors:
        assert isinstance(v, dict)
        assert {"id", "name", "threat_model", "expected", "remediation"} <= set(v.keys())
        # Must be JSON-serializable.
        json.dumps(v)


def test_get_vector_returns_attack_vector():
    """``get_vector(id)`` returns the AttackVector or None."""
    first = ATTACK_LIBRARY[0]
    found = get_vector(first.id)
    assert found is not None
    assert found.id == first.id
    assert get_vector("does_not_exist_xyz") is None


# --------------------------------------------------------------------------- #
# Per-vector tests (parametrized — one test per vector)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("vector", ATTACK_LIBRARY, ids=[v.id for v in ATTACK_LIBRARY])
def test_vector_runs_and_defense_holds(vector: AttackVector):
    """Each attack vector must run cleanly and its defense must hold.

    A ``vulnerable`` classification is a hard failure — the defense is
    broken. A ``review`` classification is acceptable (the test was
    ambiguous) but should be investigated.
    """
    result: AttackResult = vector.runner()

    # Structure
    assert isinstance(result, AttackResult)
    assert result.vector_id == vector.id
    assert result.name == vector.name
    assert result.classification in {
        CLASS_BLOCKED,
        CLASS_VULNERABLE,
        CLASS_REVIEW,
    }
    assert result.expected
    assert result.actual

    # Defense held (or was inconclusive — never broken).
    assert result.classification != CLASS_VULNERABLE, (
        f"DEFENSE BROKEN: {vector.id} — {vector.name}\n"
        f"  threat: {vector.threat_model}\n"
        f"  expected: {vector.expected}\n"
        f"  actual: {result.actual}\n"
        f"  remediation: {vector.remediation}"
    )


# --------------------------------------------------------------------------- #
# Harness API
# --------------------------------------------------------------------------- #
def test_run_all_returns_report_with_all_vectors():
    """``RedTeamHarness.run_all()`` returns a report covering every vector."""
    harness = RedTeamHarness()
    report = harness.run_all()
    assert isinstance(report, RedTeamReport)
    assert report.total == len(ATTACK_LIBRARY)
    assert report.blocked_count + report.vulnerable_count + report.review_count == report.total


def test_run_all_default_classmethod_works():
    """The convenience classmethod ``run_all_default`` works without instantiation."""
    report = RedTeamReport  # noqa: F841 — just to make the test name clear
    report = RedTeamHarness.run_all_default()
    assert report.total == len(ATTACK_LIBRARY)


def test_run_vector_by_id():
    """``run_vector(id)`` runs exactly one vector and returns its result."""
    harness = RedTeamHarness()
    first_id = ATTACK_LIBRARY[0].id
    result = harness.run_vector(first_id)
    assert result.vector_id == first_id
    assert result.duration_ms >= 0


def test_run_vector_unknown_id_raises():
    """Unknown vector ids raise KeyError, not silently return None."""
    harness = RedTeamHarness()
    with pytest.raises(KeyError):
        harness.run_vector("nonexistent_vector_id")


def test_run_all_with_only_filter():
    """The ``only`` parameter filters the vectors run."""
    harness = RedTeamHarness()
    target_ids = [ATTACK_LIBRARY[0].id, ATTACK_LIBRARY[1].id]
    report = harness.run_all(only=target_ids)
    assert report.total == 2
    assert {r.vector_id for r in report.results} == set(target_ids)


def test_run_all_all_defenses_hold():
    """The full run must not report any vulnerable defense.

    This is the canonical CI gate: if this test fails, a Howdex defense
    is broken and the release is blocked.
    """
    report = RedTeamHarness.run_all_default()
    assert report.vulnerable_count == 0, (
        f"{report.vulnerable_count} defense(s) broken:\n"
        + "\n".join(
            f"  - {r.vector_id}: {r.actual}"
            for r in report.results
            if r.classification == CLASS_VULNERABLE
        )
    )
    assert report.all_passed is True


# --------------------------------------------------------------------------- #
# Report renderers
# --------------------------------------------------------------------------- #
def test_report_to_text_contains_verdict():
    """``to_text()`` includes the verdict line."""
    report = RedTeamHarness.run_all_default()
    text = report.to_text()
    assert "Howdex Red-Team Report" in text
    assert "VERDICT:" in text
    assert "Vectors:" in text
    assert "Pass rate:" in text


def test_report_to_markdown_is_valid_markdown():
    """``to_markdown()`` produces a valid Markdown document."""
    report = RedTeamHarness.run_all_default()
    md = report.to_markdown()
    assert md.startswith("# Howdex Red-Team Report")
    assert "## Summary" in md
    assert "## Findings" in md
    # Each vector gets a heading
    for v in ATTACK_LIBRARY:
        assert v.id in md


def test_report_to_json_is_valid_json():
    """``to_json()`` produces valid JSON with the expected structure."""
    report = RedTeamHarness.run_all_default()
    data = json.loads(report.to_json())
    assert "started_at" in data
    assert "finished_at" in data
    assert "summary" in data
    assert data["summary"]["total"] == len(ATTACK_LIBRARY)
    assert data["summary"]["blocked"] + data["summary"]["vulnerable"] + data["summary"]["review"] == data["summary"]["total"]
    assert len(data["results"]) == len(ATTACK_LIBRARY)
    # Each result has the expected fields.
    for r in data["results"]:
        assert {"vector_id", "name", "threat_model", "classification", "expected", "actual"} <= set(r.keys())


def test_report_to_dict_is_serializable():
    """``to_dict()`` produces a JSON-serializable plain dict."""
    report = RedTeamHarness.run_all_default()
    d = report.to_dict()
    json.dumps(d)  # raises if not serializable
    assert d["summary"]["total"] == len(ATTACK_LIBRARY)


def test_report_html_rendering():
    """``render_redteam_report_html`` produces a complete HTML document."""
    report = RedTeamHarness.run_all_default()
    html = render_redteam_report_html(report)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    # Contains all vector ids as anchors.
    for v in ATTACK_LIBRARY:
        assert v.id in html
    # Has the verdict banner.
    assert "VERDICT" in html.upper() or "DEFENSES HELD" in html or "DEFENSE(S) BROKEN" in html


def test_report_pass_rate_property():
    """``pass_rate`` is blocked_count / total, rounded to 3 decimals."""
    report = RedTeamHarness.run_all_default()
    expected = round(report.blocked_count / report.total, 3)
    assert report.pass_rate == expected


# --------------------------------------------------------------------------- #
# CLI smoke tests
# --------------------------------------------------------------------------- #
def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run ``python -m howdex redteam ...`` and return the completed process."""
    repo_root = Path(__file__).resolve().parent.parent
    env = {
        "PYTHONPATH": str(repo_root),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    return subprocess.run(
        [sys.executable, "-m", "howdex", "redteam", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_cli_redteam_list():
    """``howdex redteam list`` lists all attack vectors."""
    proc = _run_cli("list")
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "attack vectors available" in proc.stdout
    # Each vector id appears in the listing.
    for v in ATTACK_LIBRARY:
        assert v.id in proc.stdout


def test_cli_redteam_show():
    """``howdex redteam show <id>`` shows vector details."""
    target = ATTACK_LIBRARY[0].id
    proc = _run_cli("show", target)
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert target in proc.stdout
    assert "Threat model:" in proc.stdout
    assert "Expected:" in proc.stdout
    assert "Remediation:" in proc.stdout


def test_cli_redteam_show_unknown_id():
    """``howdex redteam show <bad>`` exits 1 with an error."""
    proc = _run_cli("show", "nonexistent_vector")
    assert proc.returncode == 1
    assert "unknown vector id" in proc.stderr


def test_cli_redteam_run_text(tmp_path: Path):
    """``howdex redteam run --format text`` writes a text report to stdout."""
    proc = _run_cli("run", "--format", "text")
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "VERDICT:" in proc.stdout
    assert "ALL DEFENSES HELD" in proc.stdout


def test_cli_redteam_run_json_output(tmp_path: Path):
    """``howdex redteam run --output report.json`` infers JSON format."""
    out = tmp_path / "report.json"
    proc = _run_cli("run", "--output", str(out))
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["summary"]["total"] == len(ATTACK_LIBRARY)


def test_cli_redteam_run_html_output(tmp_path: Path):
    """``howdex redteam run --output report.html`` infers HTML format."""
    out = tmp_path / "report.html"
    proc = _run_cli("run", "--output", str(out))
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert out.exists()
    content = out.read_text()
    assert content.startswith("<!DOCTYPE html>")
    assert "</html>" in content


def test_cli_redteam_run_markdown_output(tmp_path: Path):
    """``howdex redteam run --output report.md`` infers Markdown format."""
    out = tmp_path / "report.md"
    proc = _run_cli("run", "--output", str(out))
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert out.exists()
    content = out.read_text()
    assert content.startswith("# Howdex Red-Team Report")


def test_cli_redteam_run_only_filter():
    """``--only id1,id2`` restricts the run to those vectors."""
    target_ids = [ATTACK_LIBRARY[0].id, ATTACK_LIBRARY[1].id]
    proc = _run_cli("run", "--only", ",".join(target_ids), "--format", "text")
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    # Only the two filtered vectors appear.
    for tid in target_ids:
        assert tid in proc.stdout
    # Other vectors do not appear.
    for v in ATTACK_LIBRARY:
        if v.id in target_ids:
            continue
        assert v.id not in proc.stdout, f"unexpected vector in output: {v.id}"


def test_cli_redteam_run_exits_nonzero_when_vulnerable():
    """If a defense is broken, the CLI exits 2 (CI-gating signal).

    We can't easily make a defense break for this test, so we verify the
    exit-code contract by checking that a passing run exits 0. The
    contract itself (non-zero on vulnerable) is asserted in
    ``cmd_redteam`` via ``return 0 if report.all_passed else 2``.
    """
    proc = _run_cli("run", "--format", "text")
    # All defenses currently hold → exit 0.
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
