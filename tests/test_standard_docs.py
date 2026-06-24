from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_standard_and_protocol_docs_exist():
    assert (ROOT / "docs" / "STANDARD.md").is_file()
    assert (ROOT / "docs" / "PROTOCOL.md").is_file()


def test_readme_mentions_verified_agent_procedures():
    readme = _read("README.md").casefold()

    assert "verified agent procedures" in readme
    assert "open verification layer for agent know-how" in readme


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
