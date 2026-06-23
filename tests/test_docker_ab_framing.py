"""A/B framing controls for the real Docker recovery benchmark."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture
def benchmark_module():
    sys.modules.pop("real_docker_recovery_ab_test", None)
    return importlib.import_module("real_docker_recovery_ab_test")


def test_build_base_docker_task_prompt_is_deterministic(benchmark_module):
    kwargs = {
        "objective": benchmark_module.docker_objective(43123),
        "sandbox_rules": benchmark_module.docker_sandbox_rules(),
        "allowed_commands": benchmark_module.allowed_execute_bash_commands(43123),
        "verifier": benchmark_module.docker_verifier_requirement(),
    }

    first = benchmark_module.build_base_docker_task_prompt(**kwargs)
    second = benchmark_module.build_base_docker_task_prompt(**kwargs)

    assert first == second
    assert benchmark_module.prompt_sha256(first) == benchmark_module.prompt_sha256(second)


def test_control_and_treatment_base_framing_are_byte_identical(
    benchmark_module,
):
    treatment_memory = benchmark_module.howdex_memory_section(
        "# PAST LEARNED PROCEDURE\n\nFollow this learned procedure:\n\nStep 1: inspect runtime.env"
    )
    control = benchmark_module.build_control_docker_prompt(43123)
    treatment = benchmark_module.build_treatment_docker_prompt(
        43123,
        treatment_memory,
    )

    assert control.base_prompt == treatment.base_prompt
    assert control.full_prompt != treatment.full_prompt
    assert control.memory_section != treatment.memory_section


def test_treatment_contains_learned_memory_section(benchmark_module):
    treatment = benchmark_module.build_treatment_docker_prompt(
        43123,
        benchmark_module.howdex_memory_section(
            "# PAST LEARNED PROCEDURE\n\n"
            "Follow this learned procedure:\n\n"
            "Step 1: docker compose logs --tail 100 app"
        ),
    )

    assert "# HOWDEX PROCEDURAL MEMORY" in treatment.full_prompt
    assert "# PAST LEARNED PROCEDURE" in treatment.full_prompt
    assert "Step 1: docker compose logs --tail 100 app" in treatment.full_prompt


def test_control_has_no_learned_facts_steps_or_provenance(benchmark_module):
    control = benchmark_module.build_control_docker_prompt(43123)

    assert "No prior Howdex procedural memory is available" in control.full_prompt
    assert "# PAST LEARNED PROCEDURE" not in control.full_prompt
    assert "Follow this learned procedure" not in control.full_prompt
    assert "Step 1:" not in control.full_prompt
    assert "Provenance:" not in control.full_prompt
    assert "confidence=" not in control.full_prompt


def test_both_arms_include_same_non_memory_framing(benchmark_module):
    memory = benchmark_module.howdex_memory_section(
        "# PAST LEARNED PROCEDURE\n\nStep 1: inspect runtime.env"
    )
    control = benchmark_module.build_control_docker_prompt(43123)
    treatment = benchmark_module.build_treatment_docker_prompt(43123, memory)

    objective = benchmark_module.docker_objective(43123)
    verifier = benchmark_module.docker_verifier_requirement()
    assert objective in control.base_prompt
    assert objective in treatment.base_prompt
    assert verifier in control.base_prompt
    assert verifier in treatment.base_prompt
    for command in benchmark_module.allowed_execute_bash_commands(43123):
        assert f"- {command}" in control.base_prompt
        assert f"- {command}" in treatment.base_prompt
    for rule in benchmark_module.docker_sandbox_rules():
        assert f"- {rule}" in control.base_prompt
        assert f"- {rule}" in treatment.base_prompt
    assert control.base_prompt == treatment.base_prompt


def test_docker_prompt_hashes_assert_identical_base(benchmark_module):
    hashes = benchmark_module.docker_ab_prompt_hashes(
        43123,
        benchmark_module.howdex_memory_section(
            "# PAST LEARNED PROCEDURE\n\nStep 1: inspect runtime.env"
        ),
    )

    assert set(hashes) == {
        "base_prompt_sha256",
        "control_prompt_sha256",
        "treatment_prompt_sha256",
        "memory_section_sha256",
    }
    assert hashes["control_prompt_sha256"] != hashes["treatment_prompt_sha256"]
    for digest in hashes.values():
        assert len(digest) == 64
        int(digest, 16)


@pytest.mark.parametrize(
    "source",
    [
        "```sh\ndocker compose up -d\n```",
        "#!/bin/sh\ndocker compose up -d",
        "from http.server import HTTPServer",
        "def required_mode():",
        "class Handler:",
        "services:\n  app:\n    build: .",
        "FROM python:3.12-alpine",
    ],
)
def test_source_pasted_detection_remains_strict(benchmark_module, source):
    assert benchmark_module.source_pasted_in_guidance(source) is True
