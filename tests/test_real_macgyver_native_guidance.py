"""Real MacGyver A/B native-guidance integration tests."""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest


@pytest.fixture
def benchmark_module(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    module_name = "benchmarks.macgyver.real_macgyver_ab_test"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


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
                        "task_signature": "hard ZB2 teacher",
                        "confidence": 0.92,
                        "support_count": 1,
                    },
                )()
            ]

    monkeypatch.setattr(
        benchmark_module,
        "extract_raw_examples_from_sqlite",
        lambda: [
            {
                "steps": [
                    {
                        "tool_name": "execute_fs_write",
                        "tool_args": {
                            "file_path": "decoder.py",
                            "content": (
                                "ZB2! data[4] data[5] data[6] reverse "
                                "xor checksum % 251 TARGET:"
                            ),
                        },
                        "observation": "wrote decoder.py",
                    },
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {
                            "cmd": "python3 decoder.py challenge.zb2"
                        },
                        "observation": "SUCCESS: decoded TARGET 9001",
                    },
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
        benchmark_module.build_howdex_operational_memory(Memory())
    )

    assert guidance == (
        "# HOWDEX OPERATIONAL MEMORY\nnative renderer output"
    )
    assert used_memory is True
    assert source_pasted is False
    assert captured["kwargs"]["include_source"] is False
    assert captured["kwargs"]["target_environment"] == (
        "restricted Python filesystem tool sandbox"
    )
    payload = captured["procedures"][0]
    assert "learned_facts" in payload
    assert "failed_attempts" in payload
    assert "source_artifacts" not in payload


@pytest.mark.parametrize(
    "source",
    [
        "```python\nprint('leak')\n```",
        "import pathlib",
        "from pathlib import Path",
        "def decode(path):",
        "class Decoder:",
        "#!/usr/bin/env python3",
        "open('challenge.zb2', 'rb')",
        "Path('challenge.zb2').read_bytes()",
        "data = path.read_text()",
        "sys.argv[1]",
        "bytes((byte ^ key) for byte in payload)",
    ],
)
def test_source_pasted_detection_remains_strict(
    benchmark_module,
    source,
):
    assert benchmark_module.source_pasted_in_guidance(source) is True


def test_real_native_guidance_contains_facts_without_decoder_source(
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
                        "task_signature": "hard ZB2 teacher",
                        "confidence": 0.92,
                        "support_count": 1,
                    },
                )()
            ]

    monkeypatch.setattr(
        benchmark_module,
        "extract_raw_examples_from_sqlite",
        lambda: [
            {
                "steps": [
                    {
                        "tool_name": "execute_fs_write",
                        "tool_args": {
                            "file_path": "decoder.py",
                            "content": (
                                "ZB2! data[4] data[5] data[6] reverse "
                                "xor checksum % 251 TARGET:"
                            ),
                        },
                    },
                    {
                        "tool_name": "execute_bash",
                        "tool_args": {
                            "cmd": "python3 decoder.py challenge.zb2"
                        },
                        "observation": "SUCCESS: decoded TARGET 9001",
                    },
                ]
            }
        ],
    )

    guidance, used_memory, source_pasted = (
        benchmark_module.build_howdex_operational_memory(Memory())
    )

    assert guidance.startswith("# HOWDEX OPERATIONAL MEMORY")
    assert "byte 4 is the XOR key" in guidance
    assert "byte 5 is the payload offset" in guidance
    assert "byte 6 is the encoded payload length" in guidance
    assert "Run exactly: python3 decoder.py challenge.zb2." in guidance
    assert "Source artifacts excluded" in guidance
    assert "Do not copy or paste a previous decoder implementation." in guidance
    assert used_memory is True
    assert source_pasted is False
