from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest


class FakeSpan:
    def __init__(self, name: str, attributes: dict[str, Any] | None = None):
        self.name = name
        self.attributes = dict(attributes or {})
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append((name, dict(attributes or {})))


class FakeTracer:
    def __init__(self):
        self.spans: list[FakeSpan] = []

    def start_as_current_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> FakeSpan:
        span = FakeSpan(name, attributes)
        self.spans.append(span)
        return span


@pytest.fixture
def fake_tracer(monkeypatch: pytest.MonkeyPatch) -> FakeTracer:
    import howdex.telemetry as telemetry

    tracer = FakeTracer()
    monkeypatch.setattr(telemetry, "_TRACER_OVERRIDE", tracer)
    return tracer


def _memory_with_procedure(tmp_path: Path):
    from howdex import Howdex

    memory = Howdex(path=tmp_path / "howdex.db", embedder="hashing")
    memory.start_session("Recover Docker health endpoint", source="test")
    memory.log_tool_call(
        "bash",
        {"cmd": "cat runtime.env"},
        "HEALTH_MODE=degraded",
    )
    memory.log_tool_call(
        "fs.write",
        {"path": "runtime.env", "content": "HEALTH_MODE=ready"},
        "wrote runtime.env",
    )
    memory.log_tool_call(
        "bash",
        {"cmd": "curl -sS -i http://127.0.0.1:52617/health"},
        "SUCCESS: HTTP 200 body=healthy",
    )
    memory.end_session("success")
    procedures = memory.learn(min_samples=1)
    assert procedures
    return memory, procedures[0]


def test_importing_telemetry_works_without_opentelemetry_installed(
    monkeypatch: pytest.MonkeyPatch,
):
    import howdex.telemetry as telemetry

    real_import = builtins.__import__

    def import_without_otel(name, globals=None, locals=None, fromlist=(), level=0):
        if name.split(".", 1)[0] == "opentelemetry":
            raise ModuleNotFoundError("No module named 'opentelemetry'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(telemetry, "_TRACER_OVERRIDE", None)
    monkeypatch.setattr(builtins, "__import__", import_without_otel)

    assert telemetry.get_tracer() is not None
    assert telemetry.is_enabled() is False


def test_noop_tracer_does_not_fail(monkeypatch: pytest.MonkeyPatch):
    import howdex.telemetry as telemetry

    monkeypatch.setattr(telemetry, "_TRACER_OVERRIDE", None)
    with telemetry.span("howdex.test", {"howdex.include_source": False}):
        telemetry.emit_event("howdex.test.event", {"howdex.selected_count": 0})


def test_emit_event_without_opentelemetry_does_not_fail(monkeypatch: pytest.MonkeyPatch):
    import howdex.telemetry as telemetry

    monkeypatch.setattr(telemetry, "_TRACER_OVERRIDE", None)
    telemetry.emit_event("howdex.test.event", {"howdex.omitted_count": 0})


def test_span_redacts_source_like_attributes(fake_tracer: FakeTracer):
    import howdex.telemetry as telemetry

    with telemetry.span(
        "howdex.test.privacy",
        {
            "howdex.raw_source_code": "def leaked(): pass",
            "howdex.source_episode_count": 2,
        },
    ):
        pass

    span = _first_span(fake_tracer, "howdex.test.privacy")
    assert span.attributes["howdex.raw_source_code"] == "[redacted]"
    assert span.attributes["howdex.source_episode_count"] == 2


def test_guidance_selection_and_render_emit_expected_spans(fake_tracer: FakeTracer):
    from howdex.core.guidance import (
        GuidanceBudget,
        render_agent_guidance,
        select_guidance_procedures,
    )

    procedure = {
        "id": "docker.health",
        "title": "Docker health recovery",
        "category": "docker",
        "status": "verified",
        "confidence": 0.9,
        "learned_facts": [
            "Inspect runtime.env and docker-compose.yml.",
            "Align HEALTH_MODE with the required health policy.",
            "Verify /health returns HTTP 200.",
        ],
        "verification": {"status": "verified"},
        "policy": {"source_artifacts": "excluded_by_default"},
    }

    selection = select_guidance_procedures(
        "recover docker health",
        [procedure],
        GuidanceBudget(max_procedures=1, max_guidance_chars=2000),
    )
    guidance = render_agent_guidance(
        selection.selected,
        objective="recover docker health",
        max_chars=2000,
    )

    names = [span.name for span in fake_tracer.spans]
    assert "howdex.guidance.select" in names
    assert "howdex.guidance.render" in names
    assert "howdex.procedure.inject" in names
    assert guidance.startswith("# HOWDEX OPERATIONAL MEMORY")
    select_span = _first_span(fake_tracer, "howdex.guidance.select")
    assert select_span.attributes["howdex.selected_count"] == 1
    assert select_span.attributes["howdex.omitted_count"] == 0


def test_codex_publish_emits_publish_span(
    tmp_path: Path,
    fake_tracer: FakeTracer,
):
    memory, _procedure = _memory_with_procedure(tmp_path)

    result = memory.publish_codex(tmp_path / "codex")

    assert result["exported"] == 1
    publish_span = _first_span(fake_tracer, "howdex.codex.publish")
    assert publish_span.attributes["howdex.selected_count"] == 1


def test_receipt_attach_emits_receipt_span(
    tmp_path: Path,
    fake_tracer: FakeTracer,
):
    memory, procedure = _memory_with_procedure(tmp_path)

    receipt = memory.verify_procedure(
        procedure.id,
        verifier_type="test",
        verifier_command="curl /health",
        expected_signal="healthy",
        observed_signal="HTTP 200 healthy",
        exit_code=0,
    )

    span = _first_span(fake_tracer, "howdex.receipt.attach")
    assert receipt.status == "verified"
    assert span.attributes["howdex.procedure_id"] == procedure.id
    assert span.attributes["howdex.receipt_status"] == "verified"


def test_mcp_guidance_includes_adapter_attributes(
    tmp_path: Path,
    fake_tracer: FakeTracer,
):
    from howdex.mcp.server import MCPServer

    server = MCPServer(path=str(tmp_path / "mcp.db"), embedder="hashing")

    result = server.call_tool(
        "howdex_guidance",
        {
            "objective": "Recover Docker health endpoint",
            "max_chars": 1000,
            "verified_only": True,
            "include_source": False,
        },
    )

    assert result["structuredContent"]["guidance"].startswith(
        "# HOWDEX OPERATIONAL MEMORY"
    )
    tool_span = _first_span(fake_tracer, "howdex.mcp.tool_call")
    assert tool_span.attributes["howdex.adapter"] == "mcp"
    assert tool_span.attributes["howdex.mcp_tool_name"] == "howdex_guidance"
    assert tool_span.attributes["howdex.policy_status"] == "allowed"
    retrieve_spans = [
        span
        for span in fake_tracer.spans
        if span.name == "howdex.guidance.retrieve"
        and span.attributes.get("howdex.adapter") == "mcp"
    ]
    assert retrieve_spans
    assert retrieve_spans[0].attributes["howdex.verified_only"] is True
    assert retrieve_spans[0].attributes["howdex.include_source"] is False


def test_opentelemetry_is_optional_dependency_only():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    project_dependencies = text.split("dependencies = [", 1)[1].split("]", 1)[0]

    assert "opentelemetry" not in project_dependencies
    assert "otel = [" in text
    assert "opentelemetry-api>=1.25" in text
    assert "opentelemetry-sdk>=1.25" in text


def _first_span(tracer: FakeTracer, name: str) -> FakeSpan:
    for span in tracer.spans:
        if span.name == name:
            return span
    raise AssertionError(f"missing span: {name}")
