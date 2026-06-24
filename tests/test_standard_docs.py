from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_standard_and_protocol_docs_exist():
    assert (ROOT / "docs" / "STANDARD.md").is_file()
    assert (ROOT / "docs" / "PROTOCOL.md").is_file()


def test_readme_mentions_verified_agent_procedures():
    readme = _read("README.md").casefold()
    normalized = " ".join(readme.split())

    assert "verified agent procedures" in readme
    assert "open verification layer for agent know-how" in readme
    assert (
        "howdex turns execution traces into portable, receipt-backed procedures "
        "that any agent can reuse and any enterprise can audit"
    ) in normalized
    assert "procedures are guidance, not executable authority" in readme


def test_readme_launch_positioning_does_not_overclaim():
    readme = _read("README.md").casefold()

    positive_autonomy_claims = [
        "provides production-safe autonomy",
        "offers production-safe autonomy",
        "enables production-safe autonomy",
        "guarantees production-safe autonomy",
        "is production-safe autonomous execution",
        "provides production-safe autonomous execution",
        "enables production-safe autonomous execution",
    ]
    for phrase in positive_autonomy_claims:
        assert phrase not in readme

    live_cross_model_results = list(ROOT.glob("**/*cross*model*live*result*"))
    if not live_cross_model_results:
        forbidden = [
            "live cross-model transfer is proven",
            "proved live cross-model transfer",
            "live cross-model proof",
            "verified across models in live runs",
        ]
        for phrase in forbidden:
            assert phrase not in readme

    tracking = _read("launch/PILOT_TRACKING.md").casefold()
    no_external_pilots = "external_pilot_users_confirmed: 0" in tracking
    if no_external_pilots:
        external_user_claims = [
            "external users exist",
            "we have external users",
            "customers are using howdex",
            "pilot users are using howdex",
            "external adoption is proven",
        ]
        for phrase in external_user_claims:
            assert phrase not in readme


def test_readme_dogfood_wording_is_internal_evidence_only():
    readme = _read("README.md")
    match = re.search(
        r"## Dogfooding Howdex(?P<section>.*?)(?:\n---|\Z)",
        readme,
        flags=re.DOTALL,
    )
    assert match is not None
    section = match.group("section").casefold()

    assert "internal evidence only" in section
    assert "not external users" in section
    assert "traction" in section
    assert "adoption" in section
    assert "market validation" in section

    forbidden = [
        "dogfood proves adoption",
        "dogfood proves traction",
        "dogfood proves users",
        "dogfood proves market validation",
        "external users from dogfood",
    ]
    for phrase in forbidden:
        assert phrase not in section


def test_codex_readme_mentions_candidate_and_verified_entries():
    codex = _read("codex/README.md").casefold()

    assert "candidate entries" in codex
    assert "verified entries" in codex


def test_standard_doc_contains_proof_line():
    standard = _read("docs/STANDARD.md")

    assert "No proof, no verified procedure" in standard


def test_protocol_doc_contains_required_operations():
    protocol = _read("docs/PROTOCOL.md")

    for operation in (
        "remember_trace",
        "learn",
        "guidance",
        "attach_receipt",
        "publish_codex",
        "pull_codex",
    ):
        assert operation in protocol
