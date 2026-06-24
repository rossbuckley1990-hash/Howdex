"""Docker compounding-curve benchmark tests."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture
def benchmark_module():
    module_name = "benchmarks.docker_recovery.docker_compounding_curve_test"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_support_levels_parse_correctly(benchmark_module):
    assert benchmark_module.parse_support_levels("1,5,20") == [1, 5, 20]
    assert benchmark_module.parse_support_levels(" 2, 4 ,,8 ") == [2, 4, 8]
    assert benchmark_module.parse_support_levels(None) == [1, 5, 20]
    with pytest.raises(ValueError):
        benchmark_module.parse_support_levels("1,zero")
    with pytest.raises(ValueError):
        benchmark_module.parse_support_levels("0,1")


def test_support_20_guidance_stays_within_max_chars(benchmark_module):
    memory = benchmark_module.build_verified_teacher_memory(20)
    try:
        guidance, suggestions = benchmark_module.render_compounding_guidance(
            memory,
            max_chars=1_200,
        )
        assert suggestions
        assert len(guidance) <= 1_200
    finally:
        memory.close()


def test_irrelevant_facts_are_filtered_from_docker_guidance(benchmark_module):
    memory = benchmark_module.build_verified_teacher_memory(20)
    try:
        guidance, _ = benchmark_module.render_compounding_guidance(memory)
        assert benchmark_module.irrelevant_fact_count(guidance) == 0
        assert "SHA256" not in guidance
        assert "OpenSSL" not in guidance
        assert "TARGET string" not in guidance
        assert "docker compose" in guidance
        assert "/health" in guidance
    finally:
        memory.close()


def test_source_pasted_remains_false_for_dry_guidance(benchmark_module):
    memory = benchmark_module.build_verified_teacher_memory(5)
    try:
        guidance, _ = benchmark_module.render_compounding_guidance(memory)
        assert benchmark_module.docker_ab.source_pasted_in_guidance(guidance) is False
    finally:
        memory.close()


def test_output_table_schema_includes_required_fields(benchmark_module):
    rows = benchmark_module.run_dry_curve([1], max_chars=2_000)
    table = benchmark_module.format_results_table(rows)

    assert (
        "support_count | trials | successes | success_rate | avg_attempts | "
        "memory_used | source_pasted | retrieval_relevance | guidance_chars | verdict"
    ) in table
    assert "1 | 0 | n/a | n/a | n/a | n/a | 0 |" in table
    assert "DRY-RUN PASS" in table


def test_dry_run_mode_requires_no_docker_or_openai(
    benchmark_module,
    monkeypatch,
    capsys,
):
    def fail_if_called():
        raise AssertionError("Docker should not be checked in dry-run mode")

    monkeypatch.setattr(benchmark_module.docker_ab, "check_docker_available", fail_if_called)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("HOWDEX_COMPOUNDING_MODE", "dry-run")
    monkeypatch.setenv("HOWDEX_COMPOUNDING_SUPPORT_LEVELS", "1")

    assert benchmark_module.main() == 0
    output = capsys.readouterr().out
    assert "mode=dry-run" in output
    assert "DRY RUN PASS" in output


def test_dry_run_memory_support_count_matches_condition(benchmark_module):
    memory = benchmark_module.build_verified_teacher_memory(5)
    try:
        assert benchmark_module._learned_support_count(memory) >= 5
    finally:
        memory.close()
