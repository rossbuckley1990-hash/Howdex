"""Safety and skip-path tests for the real Docker recovery benchmark."""

from __future__ import annotations

import importlib
import shutil
import sys

import pytest


@pytest.fixture
def benchmark_module():
    sys.modules.pop("real_docker_recovery_ab_test", None)
    return importlib.import_module("real_docker_recovery_ab_test")


@pytest.mark.parametrize(
    "command",
    [
        "cat docker-compose.yml",
        "cat runtime.env",
        "cat health-policy.conf",
        "docker compose build",
        "docker compose up -d --build",
        "docker compose up -d --build --force-recreate",
        "docker compose ps",
        "docker compose logs --tail 100 app",
        "docker compose down -v",
        "curl -sS -i http://127.0.0.1:43123/health",
    ],
)
def test_command_safety_gate_allows_only_expected_recovery_commands(
    benchmark_module,
    command,
):
    decision = benchmark_module.validate_bash_command(command, 43123)
    assert decision.allowed is True
    assert decision.argv


@pytest.mark.parametrize(
    "command",
    [
        "sudo docker compose up -d",
        "docker pull python:latest",
        "docker run --rm alpine",
        "docker compose exec app sh",
        "docker compose down; rm -rf /",
        "cat ../runtime.env",
        "cat /etc/passwd",
        "curl -sS -i https://example.com/health",
        "curl -sS -i http://127.0.0.1:9999/health",
        "python -c 'print(1)'",
        "sed -i 's/x/y/' runtime.env",
        "rm -rf .",
        "docker compose logs | tee output.txt",
    ],
)
def test_command_safety_gate_rejects_host_and_network_escape(
    benchmark_module,
    command,
):
    decision = benchmark_module.validate_bash_command(command, 43123)
    assert decision.allowed is False
    assert decision.reason


@pytest.mark.parametrize(
    "source",
    [
        "```sh\ndocker compose up -d\n```",
        "#!/bin/sh\ndocker compose up -d",
        "import os",
        "from http.server import HTTPServer",
        "def required_mode():",
        "class Handler(BaseHTTPRequestHandler):",
        "HTTPServer(('0.0.0.0', 8000), Handler)",
        "server.serve_forever()",
        "set -e\ndocker compose up -d",
        "services:\n  app:\n    build: .",
        "FROM python:3.12-alpine",
    ],
)
def test_source_pasted_detection_is_strict(
    benchmark_module,
    source,
):
    assert benchmark_module.source_pasted_in_guidance(source) is True


def test_operational_commands_are_not_mistaken_for_source(
    benchmark_module,
):
    guidance = "\n".join(
        [
            "# HOWDEX OPERATIONAL MEMORY",
            "- Inspect runtime.env.",
            "- Run `docker compose up -d --build`.",
            "- Verify with curl on the local /health endpoint.",
        ]
    )
    assert benchmark_module.source_pasted_in_guidance(guidance) is False


def test_docker_unavailable_path_prints_skip_and_returns_success(
    benchmark_module,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        benchmark_module,
        "check_docker_available",
        lambda: benchmark_module.DockerAvailability(
            False,
            "daemon unavailable in test",
        ),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert benchmark_module.main() == 0
    output = capsys.readouterr().out
    assert "SKIP" in output
    assert "daemon unavailable in test" in output


def test_treatment_uses_native_guidance_without_source(
    benchmark_module,
    monkeypatch,
):
    calls = {}
    suggestion = type(
        "Suggestion",
        (),
        {
            "task_signature": "recover compose service",
            "confidence": 0.9,
            "support_count": 1,
            "steps": [],
        },
    )()

    class Memory:
        def suggest_procedure(self, query, **kwargs):
            calls["query"] = query
            calls["suggest"] = kwargs
            return [suggestion]

    import howdex.core.guidance

    monkeypatch.setattr(
        howdex.core.guidance,
        "render_procedure_guidance",
        lambda suggestions, **kwargs: "# PAST LEARNED PROCEDURE\n- docker compose up -d --build",
    )

    guidance, memory_used, source_pasted = benchmark_module.native_recovery_guidance(
        Memory(), 43123
    )

    assert "# HOWDEX PROCEDURAL MEMORY" in guidance
    assert "# PAST LEARNED PROCEDURE" in guidance
    assert calls["suggest"] == {"top_k": 3, "min_confidence": 0.0}
    assert memory_used is True
    assert source_pasted is False


def test_runtime_env_write_is_sandboxed_and_validated(
    benchmark_module,
):
    sandbox = benchmark_module.create_docker_sandbox("howdex_docker_unit_")
    try:
        result = benchmark_module.execute_fs_write(
            sandbox,
            "runtime.env",
            "APP_PORT=8000\nHEALTH_MODE=ready\n",
        )
        assert result == "wrote runtime.env"
        assert (sandbox.path / "runtime.env").read_text() == ("APP_PORT=8000\nHEALTH_MODE=ready\n")
        assert benchmark_module.execute_fs_write(
            sandbox,
            "../runtime.env",
            "APP_PORT=8000\nHEALTH_MODE=ready\n",
        ).startswith("FATAL:")
        assert benchmark_module.execute_fs_write(
            sandbox,
            "runtime.env",
            "APP_PORT=8000\nHEALTH_MODE=$(curl example.com)\n",
        ).startswith("FATAL:")
    finally:
        shutil.rmtree(sandbox.path, ignore_errors=True)


def test_compose_sandbox_has_no_host_mounts_or_external_urls(
    benchmark_module,
):
    sandbox = benchmark_module.create_docker_sandbox("howdex_docker_manifest_")
    try:
        compose = (sandbox.path / "docker-compose.yml").read_text()
        dockerfile = (sandbox.path / "Dockerfile").read_text()
        assert "volumes:" not in compose
        assert "http://" not in compose
        assert "https://" not in compose
        assert f"FROM {benchmark_module.BASE_IMAGE}" in dockerfile
        assert "curl " not in dockerfile
        assert "wget " not in dockerfile
    finally:
        shutil.rmtree(sandbox.path, ignore_errors=True)
