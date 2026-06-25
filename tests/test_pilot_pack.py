from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT_DOCS = [
    ROOT / "docs" / "PILOT.md",
    ROOT / "docs" / "TUTORIAL.md",
]
CONFIG_FILES = [
    ROOT / "examples" / "pilot" / "claude_desktop_config.example.json",
    ROOT / "examples" / "pilot" / "cursor_mcp_config.example.json",
]
EXAMPLE_FILES = [
    ROOT / "examples" / "pilot" / "langgraph_example.py",
    ROOT / "examples" / "pilot" / "langchain_example.py",
    ROOT / "examples" / "pilot" / "generic_agent_loop.py",
    ROOT / "examples" / "pilot" / "codex_publish_example.py",
    ROOT / "examples" / "pilot" / "receipt_attach_example.py",
]
ISSUE_TEMPLATES = [
    ROOT / ".github" / "ISSUE_TEMPLATE" / "pilot_feedback.yml",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "procedure_submission.yml",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _all_pilot_text() -> str:
    paths = PILOT_DOCS + CONFIG_FILES + EXAMPLE_FILES + ISSUE_TEMPLATES
    return "\n".join(_read(path) for path in paths)


def test_pilot_doc_exists():
    assert (ROOT / "docs" / "PILOT.md").is_file()


def test_tutorial_doc_exists():
    assert (ROOT / "docs" / "TUTORIAL.md").is_file()


def test_example_config_files_exist_and_are_valid_json():
    for path in CONFIG_FILES:
        assert path.is_file(), path
        payload = json.loads(_read(path))
        assert "mcpServers" in payload
        assert "howdex" in payload["mcpServers"]


def test_issue_templates_exist_and_contain_required_fields():
    for path in ISSUE_TEMPLATES:
        assert path.is_file(), path
    feedback = _read(ISSUE_TEMPLATES[0])
    for field in (
        "environment",
        "agent_model",
        "integration_path",
        "task_attempted",
        "guidance_used",
        "procedure_learned",
        "receipt_attached",
        "failed_or_confused",
        "quote_permission",
    ):
        assert f"id: {field}" in feedback

    submission = _read(ISSUE_TEMPLATES[1])
    for field in (
        "procedure_title",
        "task_family",
        "environment",
        "verification_evidence",
        "receipt_attestation",
        "risk_level",
        "policy_constraints",
        "source_artifacts",
        "no_secrets",
    ):
        assert f"id: {field}" in submission


def test_examples_import_without_optional_framework_dependencies():
    for path in EXAMPLE_FILES:
        module_name = f"pilot_example_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def test_no_example_hardcodes_private_paths_except_placeholders():
    forbidden_patterns = [
        r"/Users/[A-Za-z0-9_.-]+",
        r"/home/[A-Za-z0-9_.-]+",
        r"C:\\Users\\[A-Za-z0-9_.-]+",
    ]
    for path in CONFIG_FILES + EXAMPLE_FILES:
        text = _read(path)
        for pattern in forbidden_patterns:
            assert not re.search(pattern, text), f"{path} contains private path"


def test_no_example_includes_secret_values():
    text = _all_pilot_text()
    forbidden_patterns = [
        r"sk-[A-Za-z0-9_-]{8,}",
        r"ghp_[A-Za-z0-9_]{8,}",
        r"password\s*=\s*['\"][^'\"]+['\"]",
        r"api[_-]?key\s*=\s*['\"][^'\"]+['\"]",
        r"token\s*=\s*['\"][^'\"]+['\"]",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, text, flags=re.IGNORECASE)


def test_docs_avoid_claiming_external_users_already_exist():
    text = "\n".join(_read(path).lower() for path in PILOT_DOCS)
    forbidden = [
        "external pilot users confirmed",
        "external users already exist",
        "external users exist",
        "we have pilot users",
        "customers are using howdex",
        "provides production-safe autonomous execution",
        "enables production-safe autonomous execution",
        "guarantees production-safe autonomous execution",
    ]
    for phrase in forbidden:
        assert phrase not in text
    assert "does not claim that external pilot users already exist" in text
    assert "does not claim production-safe autonomous execution" in text
