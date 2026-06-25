from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "howdex-codex-check" / "action.yml"
EXAMPLE = ROOT / "examples" / "github-actions" / "codex-check.yml"
DOCS = ROOT / "docs" / "CI.md"

EXPECTED_INPUTS = {
    "codex_path",
    "verified_only",
    "require_receipts",
    "require_signed_receipts",
    "fail_on_stale",
    "fail_on_high_risk",
    "banned_commands_file",
}


def test_action_yml_exists():
    assert ACTION.is_file()


def test_action_yml_has_expected_inputs():
    text = ACTION.read_text(encoding="utf-8")

    for input_name in EXPECTED_INPUTS:
        assert re.search(rf"^  {re.escape(input_name)}:", text, re.MULTILINE), input_name


def test_example_workflow_exists():
    text = EXAMPLE.read_text(encoding="utf-8")

    assert EXAMPLE.is_file()
    assert "uses: ./.github/actions/howdex-codex-check" in text
    assert "codex_path: codex" in text


def test_docs_mention_howdex_codex_lint():
    text = DOCS.read_text(encoding="utf-8")

    assert "howdex codex lint <codex_path>" in text
    assert "howdex codex policy-check <codex_path>" in text
    assert "howdex codex verify <codex_path>" in text


def test_ci_command_examples_are_valid_strings():
    docs = DOCS.read_text(encoding="utf-8")
    example = EXAMPLE.read_text(encoding="utf-8")
    action = ACTION.read_text(encoding="utf-8")
    commands = [
        line.strip()[2:].strip()
        for line in docs.splitlines()
        if line.strip().startswith("- howdex codex ")
    ]
    commands.extend(
        line.strip()
        for line in action.splitlines()
        if line.strip().startswith("howdex codex ")
    )

    assert commands
    for command in commands:
        assert isinstance(command, str)
        assert command
        assert command.startswith("howdex codex ")
        assert "\x00" not in command

    assert "python -m pip install -e \".[dev]\"" in example


def test_action_exposes_summary_and_counts_outputs():
    text = ACTION.read_text(encoding="utf-8")

    for output_name in (
        "summary_markdown",
        "entries_count",
        "candidate_count",
        "verified_count",
        "stale_count",
        "blocked_count",
        "failed_rules",
    ):
        assert re.search(rf"^  {re.escape(output_name)}:", text, re.MULTILINE), output_name


def test_action_does_not_require_docker_or_hosted_howdex():
    text = ACTION.read_text(encoding="utf-8").casefold()

    assert "docker " not in text
    assert "curl " not in text
    assert "howdex.com" not in text
