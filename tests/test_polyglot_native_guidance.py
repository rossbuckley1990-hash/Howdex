"""Polyglot benchmark guidance integration tests."""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest


@pytest.fixture
def benchmark_module(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sys.modules.pop("polyglot_macgyver_test", None)
    return importlib.import_module("polyglot_macgyver_test")


def test_treatment_guidance_uses_native_agent_renderer(
    benchmark_module,
    monkeypatch,
):
    captured: dict[str, Any] = {}

    class Memory:
        def suggest_procedure(self, *args, **kwargs):
            return [
                type(
                    "Suggestion",
                    (),
                    {
                        "task_signature": "polyglot teacher",
                        "confidence": 0.9,
                        "support_count": 1,
                    },
                )()
            ]

    monkeypatch.setattr(
        benchmark_module,
        "raw_examples_from_sqlite",
        lambda: [
            {
                "steps": [
                    {
                        "tool_args": {
                            "content": (
                                "seed.txt reverse hashlib.sha256 "
                                "openssl aes-256-cbc pbkdf2 -pass"
                            )
                        },
                        "observation": "SUCCESS: decrypted TARGET:EXAMPLE",
                    }
                ]
            }
        ],
    )

    def fake_renderer(procedures, **kwargs):
        captured["procedures"] = procedures
        captured["kwargs"] = kwargs
        return "# HOWDEX OPERATIONAL MEMORY\nnative renderer output"

    monkeypatch.setattr(
        benchmark_module,
        "render_agent_guidance",
        fake_renderer,
    )

    guidance, used_memory, source_pasted = (
        benchmark_module.build_polyglot_memory(Memory())
    )

    assert guidance == (
        "# HOWDEX OPERATIONAL MEMORY\nnative renderer output"
    )
    assert used_memory is True
    assert source_pasted is False
    assert captured["kwargs"]["include_source"] is False
    assert captured["kwargs"]["target_environment"] == (
        "Bash-only student sandbox"
    )
    payload = captured["procedures"][0]
    assert "learned_facts" in payload
    assert "failed_attempts" in payload
    assert any(
        "printf %s \"$(cat seed.txt | rev)\"" in fact
        for fact in payload["learned_facts"]
    )


@pytest.mark.parametrize(
    "source",
    [
        "```python\nprint('leak')\n```",
        "import hashlib",
        "from pathlib import Path",
        "def decrypt_vault():",
        "class Decoder:",
        "hashlib.sha256(value)",
        "subprocess.run(['openssl'])",
        "seed[::-1]",
        "#!/usr/bin/env python3",
    ],
)
def test_source_pasted_detection_remains_strict(
    benchmark_module,
    source,
):
    assert benchmark_module.source_pasted_in_guidance(source) is True


def test_operational_bash_guidance_is_not_source_paste(
    benchmark_module,
):
    guidance = (
        "# HOWDEX OPERATIONAL MEMORY\n"
        "- Use Bash tools only.\n"
        "- printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | "
        "awk '{print $1}'\n"
        "- openssl enc -d -aes-256-cbc -pbkdf2\n"
    )

    assert (
        benchmark_module.source_pasted_in_guidance(guidance)
        is False
    )


def test_real_native_treatment_guidance_preserves_bash_correction(
    benchmark_module,
    monkeypatch,
):
    class Memory:
        def suggest_procedure(self, *args, **kwargs):
            return [
                type(
                    "Suggestion",
                    (),
                    {
                        "task_signature": "polyglot teacher",
                        "confidence": 0.9,
                        "support_count": 1,
                    },
                )()
            ]

    monkeypatch.setattr(
        benchmark_module,
        "raw_examples_from_sqlite",
        lambda: [
            {
                "steps": [
                    {
                        "tool_args": {
                            "content": (
                                "seed.txt reversed then SHA256; decrypt with "
                                "openssl aes-256-cbc pbkdf2 -pass"
                            )
                        },
                        "observation": "SUCCESS: decrypted TARGET:EXAMPLE",
                    }
                ]
            }
        ],
    )

    guidance, used_memory, source_pasted = (
        benchmark_module.build_polyglot_memory(Memory())
    )

    assert guidance.startswith("# HOWDEX OPERATIONAL MEMORY")
    assert (
        "printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | "
        "awk '{print $1}'"
    ) in guidance
    assert "printf does not read from stdin" in guidance
    assert "Python is unavailable." in guidance
    assert "Source artifacts excluded" in guidance
    assert used_memory is True
    assert source_pasted is False
