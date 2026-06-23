"""Optional OpenAI dependency hygiene for live benchmark modules."""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest


LIVE_BENCHMARK_MODULES = (
    "real_macgyver_ab_test",
    "polyglot_macgyver_test",
    "polyglot_macgyver_nosynth_test",
    "real_docker_recovery_ab_test",
)


def test_importing_live_benchmark_modules_does_not_require_openai():
    for module_name in LIVE_BENCHMARK_MODULES:
        sys.modules.pop(module_name, None)
        importlib.import_module(module_name)


def test_lazy_openai_client_reports_clear_runtime_error_without_dependency(
    monkeypatch: pytest.MonkeyPatch,
):
    from benchmark_openai import get_openai_client

    real_import = builtins.__import__

    def import_without_openai(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "openai":
            raise ModuleNotFoundError("No module named 'openai'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_openai)

    with pytest.raises(RuntimeError, match="optional dependency is required"):
        get_openai_client()


def test_benchmark_files_do_not_hard_import_openai_client():
    root = Path(__file__).resolve().parents[1]
    for path in root.glob("*_test.py"):
        text = path.read_text(encoding="utf-8")
        assert "from openai import OpenAI" not in text, path
        assert "client = OpenAI()" not in text, path
