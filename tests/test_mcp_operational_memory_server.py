from __future__ import annotations

import importlib
import json
from pathlib import Path

from howdex.mcp.server import TOOLS, MCPServer

REQUIRED_TOOLS = {
    "howdex_remember_trace",
    "howdex_learn",
    "howdex_guidance",
    "howdex_codex_search",
    "howdex_codex_publish",
    "howdex_attach_receipt",
}


def _content(result: dict) -> dict:
    assert result["isError"] is False
    return result["structuredContent"]


def _tool(server: MCPServer, name: str, arguments: dict) -> dict:
    return _content(server.call_tool(name, arguments))


def _seed_procedure(server: MCPServer, task: str = "recover docker health") -> str:
    _tool(
        server,
        "howdex_remember_trace",
        {
            "task": task,
            "steps": [
                {
                    "tool": "bash",
                    "args": {"cmd": "cat docker-compose.yml"},
                    "observation": "services: app",
                },
                {
                    "tool": "bash",
                    "args": {"cmd": "cat runtime.env"},
                    "observation": "HEALTH_MODE=degraded",
                },
                {
                    "tool": "fs.write",
                    "args": {"path": "runtime.env", "content": "HEALTH_MODE=ready"},
                    "observation": "wrote runtime.env",
                },
                {
                    "tool": "bash",
                    "args": {"cmd": "docker compose up -d --build --force-recreate"},
                    "observation": "container recreated",
                },
                {
                    "tool": "bash",
                    "args": {"cmd": "curl -sS -i http://127.0.0.1:52617/health"},
                    "observation": "SUCCESS: HTTP 200 body=healthy",
                },
            ],
            "outcome": "success",
            "metadata": {"source": "unit-test"},
        },
    )
    learned = _tool(server, "howdex_learn", {"min_samples": 1})
    assert learned["learned_procedures"]
    return learned["learned_procedures"][0]["procedure_id"]


def _codex_entry(
    ident: str,
    *,
    status: str,
    title: str = "Docker Compose health recovery",
    facts: list[str] | None = None,
    source_artifacts: list[dict] | None = None,
) -> dict:
    entry = {
        "avoid": ["Do not claim success before the HTTP verifier passes."],
        "category": "docker/config/health",
        "id": ident,
        "learned_facts": facts
        or [
            "Inspect docker-compose.yml and runtime.env.",
            "Align HEALTH_MODE with the required health policy.",
            "Verify /health returns HTTP 200.",
        ],
        "policy": {
            "allowed": ["Use as local operational guidance."],
            "forbidden": ["Do not run unapproved host commands."],
            "requires_human_review": False,
            "source_artifacts": "excluded_by_default",
        },
        "provenance": {
            "evidence": ["unit fixture"],
            "learned_from": ["test"],
            "limitations": ["unit-only fixture"],
        },
        "risk_level": "medium",
        "source": {
            "kind": "unit-test",
            "name": "unit",
            "reference": "tests/test_mcp_operational_memory_server.py",
        },
        "status": status,
        "tags": ["docker", "health"],
        "title": title,
        "verification": {
            "expected_signal": "HTTP 200 body=healthy",
            "status": "verified" if status == "verified" else "required",
            "verifier_command": "curl /health",
            "verifier_type": "http",
        },
        "version": "1.0.0",
    }
    if source_artifacts:
        entry["source_artifacts"] = source_artifacts
    return entry


def _write_codex(root: Path, *entries: dict) -> Path:
    entries_dir = root / "entries"
    entries_dir.mkdir(parents=True)
    for entry in entries:
        (entries_dir / f"{entry['id']}.json").write_text(
            json.dumps(entry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return root


def test_mcp_server_module_imports_without_openai_installed():
    module = importlib.import_module("howdex.mcp.server")
    source = Path(module.__file__).read_text(encoding="utf-8").casefold()

    assert hasattr(module, "MCPServer")
    assert "import openai" not in source
    assert "from openai" not in source


def test_required_tool_definitions_exist():
    names = {tool["name"] for tool in TOOLS}

    assert REQUIRED_TOOLS <= names


def test_howdex_guidance_returns_markdown(tmp_path):
    server = MCPServer(path=str(tmp_path / "howdex.db"), embedder="hashing")
    _seed_procedure(server)

    result = _tool(
        server,
        "howdex_guidance",
        {
            "objective": "Recover Docker Compose health endpoint",
            "max_chars": 2000,
        },
    )

    assert result["guidance"].startswith("# HOWDEX OPERATIONAL MEMORY")
    assert result["selected_procedure_ids"]
    assert "Docker" in result["guidance"] or "docker" in result["guidance"]


def test_howdex_guidance_respects_max_chars(tmp_path):
    server = MCPServer(path=str(tmp_path / "howdex.db"), embedder="hashing")
    _seed_procedure(server)

    result = _tool(
        server,
        "howdex_guidance",
        {
            "objective": "Recover Docker Compose health endpoint",
            "max_chars": 600,
        },
    )

    assert len(result["guidance"]) <= 600
    assert result["context_budget_used"] <= 600


def test_howdex_codex_search_respects_verified_only(tmp_path):
    codex = _write_codex(
        tmp_path / "codex",
        _codex_entry("candidate-docker", status="candidate"),
        _codex_entry("verified-docker", status="verified"),
    )
    server = MCPServer(
        path=str(tmp_path / "howdex.db"),
        embedder="hashing",
        codex_path=str(codex),
    )

    result = _tool(
        server,
        "howdex_codex_search",
        {
            "query": "Docker health recovery",
            "verified_only": True,
            "max_results": 5,
        },
    )

    assert [match["id"] for match in result["matches"]] == ["verified-docker"]
    assert all(match["status"] == "verified" for match in result["matches"])


def test_howdex_codex_publish_emits_candidate_for_unverified(tmp_path):
    server = MCPServer(path=str(tmp_path / "howdex.db"), embedder="hashing")
    procedure_id = _seed_procedure(server)

    result = _tool(
        server,
        "howdex_codex_publish",
        {
            "procedure_id": procedure_id,
            "registry_path": str(tmp_path / "registry"),
        },
    )

    entry = json.loads(Path(result["codex_entry_path"]).read_text(encoding="utf-8"))
    assert result["status"] == "candidate"
    assert entry["status"] == "candidate"
    assert result["receipt_requirement"]


def test_howdex_attach_receipt_marks_verified_only_with_evidence(tmp_path):
    server = MCPServer(path=str(tmp_path / "howdex.db"), embedder="hashing")
    procedure_id = _seed_procedure(server)

    failed = _tool(
        server,
        "howdex_attach_receipt",
        {
            "procedure_id": procedure_id,
            "verifier_command": "curl /health",
            "expected_signal": "HTTP 200 body=healthy",
            "observed_signal": "HTTP 503 body=unhealthy",
            "exit_code": 0,
            "environment": {"docker": "local"},
        },
    )
    assert failed["verification_status"] == "failed_verification"

    server = MCPServer(path=str(tmp_path / "verified.db"), embedder="hashing")
    verified_procedure_id = _seed_procedure(server, "recover verified docker health")
    verified = _tool(
        server,
        "howdex_attach_receipt",
        {
            "procedure_id": verified_procedure_id,
            "verifier_command": "curl /health",
            "expected_signal": "HTTP 200 body=healthy",
            "observed_signal": "SUCCESS: HTTP 200 body=healthy",
            "exit_code": 0,
            "environment": {"docker": "local"},
        },
    )
    assert verified["receipt_id"]
    assert verified["verification_status"] == "verified"
    assert verified["procedure_status"] == "verified"


def test_source_artifacts_are_excluded_by_default(tmp_path):
    codex = _write_codex(
        tmp_path / "codex",
        _codex_entry(
            "source-docker",
            status="candidate",
            source_artifacts=[
                {
                    "file_path": "app.py",
                    "content": "import hashlib\nprint('source should not leak')",
                }
            ],
        ),
    )
    server = MCPServer(
        path=str(tmp_path / "howdex.db"),
        embedder="hashing",
        codex_path=str(codex),
    )

    result = _tool(
        server,
        "howdex_guidance",
        {
            "objective": "Docker health recovery",
            "max_chars": 2000,
        },
    )

    assert "Source artifacts excluded" in result["guidance"]
    assert "import hashlib" not in result["guidance"]
    assert "source should not leak" not in result["guidance"]


def test_readonly_rejects_mutating_tools(tmp_path):
    server = MCPServer(
        path=str(tmp_path / "howdex.db"),
        embedder="hashing",
        readonly=True,
    )

    result = server.call_tool(
        "howdex_remember_trace",
        {
            "task": "should not store",
            "steps": ["inspect file"],
            "outcome": "success",
        },
    )

    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "readonly"
