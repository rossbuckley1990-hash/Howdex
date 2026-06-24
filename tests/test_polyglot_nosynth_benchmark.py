"""No-synthesis polyglot benchmark integrity tests."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def benchmark_module(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    module_name = "benchmarks.polyglot.polyglot_macgyver_nosynth_test"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_native_guidance_receives_retrieved_procedures_only(
    benchmark_module,
    monkeypatch,
):
    suggestion = object()
    captured: dict[str, Any] = {}

    class Memory:
        def suggest_procedure(self, task, **kwargs):
            captured["query"] = task
            captured["retrieval"] = kwargs
            return [suggestion]

    def fake_renderer(procedures, **kwargs):
        captured["procedures"] = procedures
        captured["rendering"] = kwargs
        return "# HOWDEX OPERATIONAL MEMORY\nnative only"

    monkeypatch.setattr(
        benchmark_module,
        "render_agent_guidance",
        fake_renderer,
    )

    guidance, memory_used, source_pasted = (
        benchmark_module.native_procedure_guidance(Memory())
    )

    assert guidance == "# HOWDEX OPERATIONAL MEMORY\nnative only"
    assert captured["procedures"] == [suggestion]
    assert captured["retrieval"] == {
        "top_k": 3,
        "min_confidence": 0.0,
    }
    assert captured["rendering"]["include_source"] is False
    assert captured["rendering"]["include_failed_attempts"] is True
    assert captured["rendering"]["include_verification"] is True
    assert memory_used is True
    assert source_pasted is False


def test_real_native_guidance_excludes_source(benchmark_module):
    class Memory:
        def suggest_procedure(self, *args, **kwargs):
            return [
                {
                    "task_signature": "teacher procedure",
                    "confidence": 0.9,
                    "support_count": 1,
                    "source_artifacts": [
                        {
                            "file_path": "decrypt.py",
                            "content": "import hashlib\nprint('source leak')",
                        }
                    ],
                }
            ]

    guidance, memory_used, source_pasted = (
        benchmark_module.native_procedure_guidance(Memory())
    )

    assert guidance.startswith("# HOWDEX OPERATIONAL MEMORY")
    assert "decrypt.py" not in guidance
    assert "import hashlib" not in guidance
    assert "source leak" not in guidance
    assert "Source artifacts excluded" in guidance
    assert memory_used is True
    assert source_pasted is False


def test_new_benchmark_contains_no_fact_synthesis_or_source_extraction():
    source_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "polyglot"
        / "polyglot_macgyver_nosynth_test.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assigned_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "learned_facts" not in assigned_names
    assert "sqlite3" not in imported_modules
    assert not any(
        "raw_example" in name
        or "extract_fact" in name
        or "build_fact" in name
        for name in function_names
    )
    assert "hashlib.sha256" not in source
    assert "pbkdf2" not in source.casefold()
    assert "seed[::-1]" not in source


@pytest.mark.parametrize(
    "source",
    [
        "```python\nprint('leak')\n```",
        "import hashlib",
        "from pathlib import Path",
        "def decrypt():",
        "class Decoder:",
        "hashlib.sha256(seed)",
        "subprocess.run(['openssl'])",
        "seed[::-1]",
        "#!/usr/bin/env python3",
    ],
)
def test_source_paste_detection_is_strict(
    benchmark_module,
    source,
):
    assert benchmark_module.source_pasted_in_guidance(source) is True


def test_verdict_thresholds_are_honest():
    source_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "polyglot"
        / "polyglot_macgyver_nosynth_test.py"
    )
    source = source_path.read_text(encoding="utf-8")

    assert 'treatment["success_rate"] >= 0.40' in source
    assert 'treatment["success_rate"] >= 0.80' in source
    assert 'treatment["success_rate"] > control["success_rate"]' in source
    assert 'treatment["source_pasted"] == 0' in source
    assert (
        'treatment["memory_used"] == treatment["trials"]'
        in source
    )
    assert "shared.MAX_TURNS = MAX_TURNS" in source
