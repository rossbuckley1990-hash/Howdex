"""Local MCP (Model Context Protocol) server for Howdex operational memory.

The server is intentionally local-first: it uses SQLite through ``Howdex``,
requires no OpenAI dependency, and performs no network calls except for the
optional local HTTP transport.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

import howdex.telemetry as telemetry
from howdex import Howdex, __version__
from howdex.core.codex_staleness import (
    evaluate_codex_staleness,
    has_compatibility_metadata,
    staleness_guidance_text,
)
from howdex.core.guidance import (
    GuidanceBudget,
    render_agent_guidance,
    select_guidance_procedures,
)
from howdex.core.types import MemoryLayer, MemoryType, Procedure
from howdex.portable import codex_entry_document, init_codex


PROTOCOL_VERSION = "2024-11-05"
MUTATING_TOOLS = {
    "howdex_remember",
    "howdex_remember_trace",
    "howdex_learn",
    "howdex_forget",
    "howdex_codex_publish",
    "howdex_attach_receipt",
}


def _schema_object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


TOOLS = [
    {
        "name": "howdex_remember_trace",
        "description": (
            "Store one structured execution trace as an episodic Howdex session. "
            "Use this after an agent run to preserve what was tried, what failed, "
            "and what worked."
        ),
        "inputSchema": _schema_object(
            {
                "task": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "object"},
                        ]
                    },
                },
                "outcome": {"type": "string", "default": "success"},
                "metadata": {"type": "object", "default": {}},
            },
            ["task", "steps"],
        ),
    },
    {
        "name": "howdex_learn",
        "description": (
            "Consolidate successful episodic traces into reusable procedures."
        ),
        "inputSchema": _schema_object(
            {
                "min_samples": {"type": "integer", "default": 1, "minimum": 1},
                "task_signature": {"type": "string"},
            },
            [],
        ),
    },
    {
        "name": "howdex_guidance",
        "description": (
            "Retrieve relevant local procedures and Codex entries, then render "
            "bounded operational guidance for the current objective."
        ),
        "inputSchema": _schema_object(
            {
                "objective": {"type": "string"},
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "environment": {
                    "oneOf": [{"type": "object"}, {"type": "string"}],
                },
                "max_chars": {"type": "integer", "default": 6000, "minimum": 256},
                "verified_only": {"type": "boolean", "default": False},
                "max_procedures": {"type": "integer", "default": 3, "minimum": 1},
                "min_relevance_score": {"type": "number", "default": 0.05},
                "include_source": {"type": "boolean", "default": False},
                "debug": {"type": "boolean", "default": False},
            },
            ["objective"],
        ),
    },
    {
        "name": "howdex_codex_search",
        "description": (
            "Search a local Howdex Codex catalogue with relevance, policy, and "
            "staleness controls."
        ),
        "inputSchema": _schema_object(
            {
                "query": {"type": "string"},
                "environment": {
                    "oneOf": [{"type": "object"}, {"type": "string"}],
                },
                "verified_only": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 5, "minimum": 1},
                "min_relevance_score": {"type": "number", "default": 0.05},
            },
            ["query"],
        ),
    },
    {
        "name": "howdex_codex_publish",
        "description": (
            "Publish one local learned procedure as a Codex entry. Unverified "
            "procedures publish as candidate entries."
        ),
        "inputSchema": _schema_object(
            {
                "procedure_id": {"type": "string"},
                "registry_path": {"type": "string"},
            },
            ["procedure_id", "registry_path"],
        ),
    },
    {
        "name": "howdex_attach_receipt",
        "description": (
            "Attach inspectable verification evidence to a procedure. A receipt "
            "is verified only when exit_code is zero and observed_signal contains "
            "expected_signal."
        ),
        "inputSchema": _schema_object(
            {
                "procedure_id": {"type": "string"},
                "verifier_command": {"type": "string"},
                "expected_signal": {"type": "string"},
                "observed_signal": {"type": "string"},
                "exit_code": {"type": "integer"},
                "environment": {"type": "object", "default": {}},
            },
            [
                "procedure_id",
                "verifier_command",
                "expected_signal",
                "observed_signal",
                "exit_code",
            ],
        ),
    },
    # Backward-compatible generic memory helpers.
    {
        "name": "howdex_remember",
        "description": "Store a generic Howdex memory.",
        "inputSchema": _schema_object(
            {
                "content": {"type": "string"},
                "layer": {
                    "type": "string",
                    "enum": ["working", "semantic", "episodic", "procedural"],
                    "default": "semantic",
                },
                "type": {"type": "string", "enum": [item.value for item in MemoryType]},
                "importance": {"type": "number", "default": 0.5},
                "ttl": {"type": "number"},
            },
            ["content"],
        ),
    },
    {
        "name": "howdex_search",
        "description": "Search generic Howdex memories.",
        "inputSchema": _schema_object(
            {
                "query": {"type": "string"},
                "layer": {
                    "type": "string",
                    "enum": ["working", "semantic", "episodic", "procedural"],
                },
                "top_k": {"type": "integer", "default": 5},
                "min_score": {"type": "number", "default": 0.1},
            },
            ["query"],
        ),
    },
    {
        "name": "howdex_forget",
        "description": "Delete a generic memory by id.",
        "inputSchema": _schema_object({"memory_id": {"type": "string"}}, ["memory_id"]),
    },
    {
        "name": "howdex_stats",
        "description": "Return local Howdex database stats.",
        "inputSchema": _schema_object({}),
    },
]


class MCPServer:
    """MCP server core. Transport-agnostic; call ``handle`` per request."""

    def __init__(
        self,
        *,
        path: Optional[str] = None,
        embedder: Optional[str] = None,
        codex_path: Optional[str] = None,
        readonly: bool = False,
    ):
        self.howdex = Howdex(path=path, embedder=embedder)
        self.codex_path = Path(codex_path).expanduser() if codex_path else None
        self.readonly = bool(readonly)
        self._lock = threading.RLock()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                return _ok(
                    req_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "howdex", "version": __version__},
                    },
                )
            if method == "tools/list":
                return _ok(req_id, {"tools": TOOLS})
            if method == "tools/call":
                return self._handle_tool_call(req_id, params)
            if method == "notifications/initialized":
                return {}
            return _err(req_id, -32601, f"method not found: {method}")
        except Exception as exc:  # noqa: BLE001
            return _err(req_id, -32603, f"internal error: {exc}")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one tool directly. Useful for tests and embedded local clients."""
        response = self._handle_tool_call(
            None,
            {"name": name, "arguments": arguments or {}},
        )
        result = response.get("result", response)
        return result

    def _handle_tool_call(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments", {}) or {}

        with telemetry.span(
            "howdex.mcp.tool_call",
            {
                "howdex.adapter": "mcp",
                "howdex.mcp_tool_name": str(name or ""),
            },
        ) as tool_span:
            if self.readonly and name in MUTATING_TOOLS:
                telemetry.set_attribute(
                    tool_span,
                    "howdex.policy_status",
                    "readonly_rejected",
                )
                return _ok(
                    req_id,
                    _tool_error(
                        {
                            "error": "readonly",
                            "message": f"{name} is disabled because the MCP server is read-only.",
                        }
                    ),
                )

            with self._lock:
                telemetry.set_attribute(tool_span, "howdex.policy_status", "allowed")
                if name == "howdex_remember_trace":
                    return _ok(req_id, _tool_json(self._remember_trace(args)))
                if name == "howdex_learn":
                    return _ok(req_id, _tool_json(self._learn(args)))
                if name == "howdex_guidance":
                    return _ok(req_id, _tool_json(self._guidance(args)))
                if name == "howdex_codex_search":
                    return _ok(req_id, _tool_json(self._codex_search(args)))
                if name == "howdex_codex_publish":
                    return _ok(req_id, _tool_json(self._codex_publish(args)))
                if name == "howdex_attach_receipt":
                    return _ok(req_id, _tool_json(self._attach_receipt(args)))
                if name == "howdex_remember":
                    return _ok(req_id, _tool_json(self._remember(args)))
                if name == "howdex_search":
                    return _ok(req_id, _tool_json(self._search(args)))
                if name == "howdex_forget":
                    self.howdex.forget(str(args["memory_id"]))
                    return _ok(req_id, _tool_json({"forgot": str(args["memory_id"])}))
                if name == "howdex_stats":
                    return _ok(req_id, _tool_json(self.howdex.stats()))
                telemetry.set_attribute(
                    tool_span,
                    "howdex.policy_status",
                    "unknown_tool",
                )
                return _err(req_id, -32601, f"unknown tool: {name}")

    def _remember_trace(self, args: dict[str, Any]) -> dict[str, Any]:
        task = str(args["task"]).strip()
        steps = list(args.get("steps") or [])
        metadata = _mapping(args.get("metadata"))
        outcome = str(args.get("outcome") or "success").strip() or "success"
        self.howdex.start_session(
            task,
            source="mcp",
            provenance={"mcp_metadata": metadata},
        )
        for step in steps:
            self._log_trace_step(step)
        error = None if outcome == "success" else metadata.get("error")
        episode = self.howdex.end_session(outcome=outcome, error=error)
        return {
            "episode_id": episode.session_id,
            "stored_step_count": len(episode.steps),
        }

    def _log_trace_step(self, step: Any) -> None:
        if isinstance(step, str):
            self.howdex.log_step(step, "")
            return
        if not isinstance(step, Mapping):
            self.howdex.log_step(str(step), "")
            return

        tool_name = (
            step.get("tool_name")
            or step.get("tool")
            or step.get("name")
            or step.get("function")
        )
        observation = _first_text(
            step,
            "observation",
            "output",
            "stdout",
            "stderr",
            "result",
            "error",
        )
        metadata = _mapping(step.get("tool_metadata") or step.get("metadata"))
        extra = {
            key: step[key]
            for key in (
                "outcome",
                "error",
                "started_at",
                "ended_at",
                "duration_s",
                "parent_step_ids",
                "span_id",
                "parallel_group_id",
                "ordering_index",
            )
            if key in step
        }
        if tool_name:
            arguments = (
                step.get("tool_args")
                or step.get("arguments")
                or step.get("args")
                or _command_arguments(step)
            )
            self.howdex.log_tool_call(
                str(tool_name),
                arguments=_mapping(arguments),
                observation=observation,
                metadata=metadata,
                **extra,
            )
            return

        action = str(step.get("action") or step.get("cmd") or step)
        self.howdex.log_step(action, observation, **extra)

    def _learn(self, args: dict[str, Any]) -> dict[str, Any]:
        min_samples = max(1, int(args.get("min_samples", 1)))
        task_signature = str(args.get("task_signature") or "").strip().casefold()
        procedures = self.howdex.learn(min_samples=min_samples)
        if task_signature:
            procedures = [
                procedure
                for procedure in procedures
                if task_signature in procedure.task_signature.casefold()
            ]
        return {
            "learned_procedures": [
                {
                    "procedure_id": procedure.id,
                    "task_signature": procedure.task_signature,
                    "support_count": procedure.support_count,
                    "success_count": procedure.success_count,
                    "confidence": procedure.confidence,
                    "verification_status": self.howdex.procedure_verification_status(procedure.id),
                }
                for procedure in procedures
            ]
        }

    def _guidance(self, args: dict[str, Any]) -> dict[str, Any]:
        objective = str(args["objective"]).strip()
        max_chars = int(args.get("max_chars") or 6000)
        environment = args.get("environment")
        verified_only = bool(args.get("verified_only", False))
        include_source = bool(args.get("include_source", False))
        max_procedures = int(args.get("max_procedures") or 3)
        min_relevance = float(args.get("min_relevance_score", 0.05))
        constraints = _string_list(args.get("constraints"))
        with telemetry.span(
            "howdex.guidance.retrieve",
            {
                "howdex.adapter": "mcp",
                "howdex.include_source": include_source,
                "howdex.verified_only": verified_only,
            },
        ) as retrieve_span:
            candidates = self._guidance_candidates()
            budget = GuidanceBudget(
                max_procedures=max_procedures,
                max_guidance_chars=max_chars,
                min_relevance_score=min_relevance,
                include_verified_only=verified_only,
                include_candidates=not verified_only,
                suppress_stale_or_incompatible=True,
                current_environment=environment,
            )
            selection = select_guidance_procedures(objective, candidates, budget)
            telemetry.set_attribute(
                retrieve_span,
                "howdex.selected_count",
                len(selection.selected),
            )
            telemetry.set_attribute(
                retrieve_span,
                "howdex.omitted_count",
                selection.omitted_count,
            )
        guidance = render_agent_guidance(
            selection.selected,
            objective=objective,
            constraints=constraints,
            target_environment=environment if isinstance(environment, str) else None,
            current_environment=environment,
            include_source=include_source,
            include_failed_attempts=True,
            include_verification=True,
            max_chars=max_chars,
        )
        warnings = self._warnings_for(selection.selected, environment)
        return {
            "guidance": guidance,
            "selected_procedure_ids": [
                _candidate_id(procedure, index)
                for index, procedure in enumerate(selection.selected, start=1)
            ],
            "selected_count": len(selection.selected),
            "omitted_count": selection.omitted_count,
            "context_budget_used": min(len(guidance), max_chars),
            "max_guidance_chars": max_chars,
            "warnings": warnings,
            "debug_omissions": [
                {
                    "procedure_id": decision.procedure_id,
                    "reason": decision.reason,
                    "score": decision.relevance_score,
                    "status": decision.status,
                    "staleness_status": decision.staleness_status,
                }
                for decision in selection.excluded
                if bool(args.get("debug", False))
            ],
        }

    def _guidance_candidates(self) -> list[Any]:
        candidates: list[Any] = self.howdex.list_procedures(
            min_confidence=0.0,
            limit=None,
        )
        candidates.extend(self._load_codex_entries())
        return candidates

    def _codex_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args["query"]).strip()
        environment = args.get("environment")
        max_results = int(args.get("max_results") or 5)
        verified_only = bool(args.get("verified_only", False))
        with telemetry.span(
            "howdex.codex.search",
            {
                "howdex.adapter": "mcp",
                "howdex.verified_only": verified_only,
            },
        ) as search_span:
            budget = GuidanceBudget(
                max_procedures=max_results,
                max_guidance_chars=20_000,
                min_relevance_score=float(args.get("min_relevance_score", 0.05)),
                include_verified_only=verified_only,
                include_candidates=not verified_only,
                suppress_stale_or_incompatible=True,
                current_environment=environment,
            )
            selection = select_guidance_procedures(
                query,
                self._load_codex_entries(),
                budget,
            )
            telemetry.set_attribute(
                search_span,
                "howdex.selected_count",
                len(selection.selected),
            )
            telemetry.set_attribute(
                search_span,
                "howdex.omitted_count",
                selection.omitted_count,
            )
        return {
            "matches": [
                self._codex_match(entry, environment)
                for entry in selection.selected
            ],
            "omitted_count": selection.omitted_count,
            "warnings": self._warnings_for(selection.selected, environment),
        }

    def _codex_match(self, entry: dict[str, Any], environment: Any) -> dict[str, Any]:
        policy_warnings = _policy_warnings(entry)
        staleness_warning = _staleness_warning(entry, environment)
        return {
            "id": str(entry.get("id") or ""),
            "title": str(entry.get("title") or ""),
            "category": str(entry.get("category") or ""),
            "status": str(entry.get("status") or "candidate"),
            "risk_level": str(entry.get("risk_level") or "unknown"),
            "tags": _string_list(entry.get("tags")),
            "policy_warnings": policy_warnings,
            "staleness_warnings": [staleness_warning] if staleness_warning else [],
        }

    def _codex_publish(self, args: dict[str, Any]) -> dict[str, Any]:
        procedure_id = str(args["procedure_id"]).strip()
        registry_path = Path(str(args["registry_path"])).expanduser()
        with telemetry.span(
            "howdex.codex.publish",
            {
                "howdex.adapter": "mcp",
                "howdex.procedure_id": procedure_id,
            },
        ) as publish_span:
            procedure = self.howdex._procedure_by_id(procedure_id)
            registry = init_codex(registry_path)
            document = codex_entry_document(procedure, store=self.howdex.store)
            destination = Path(registry["procedures"]) / f"{document['id']}.json"
            _write_json(destination, document)
            telemetry.set_attribute(
                publish_span,
                "howdex.codex_entry_id",
                document["id"],
            )
            telemetry.set_attribute(
                publish_span,
                "howdex.procedure_status",
                document["status"],
            )
        return {
            "codex_entry_path": str(destination),
            "status": document["status"],
            "receipt_requirement": (
                None
                if document["status"] == "verified"
                else "attach an inspectable verification receipt before marking verified"
            ),
        }

    def _attach_receipt(self, args: dict[str, Any]) -> dict[str, Any]:
        procedure_id = str(args["procedure_id"])
        with telemetry.span(
            "howdex.receipt.attach",
            {
                "howdex.adapter": "mcp",
                "howdex.procedure_id": procedure_id,
            },
        ) as receipt_span:
            receipt = self.howdex.verify_procedure(
                procedure_id,
                verifier_type="custom",
                verifier_command=str(args["verifier_command"]),
                expected_signal=str(args["expected_signal"]),
                observed_signal=str(args["observed_signal"]),
                exit_code=int(args["exit_code"]),
                environment_fingerprint=_mapping(args.get("environment")),
            )
            telemetry.set_attribute(
                receipt_span,
                "howdex.receipt_status",
                receipt.status,
            )
        return {
            "receipt_id": receipt.receipt_id,
            "receipt_status": receipt.status,
            "procedure_status": self.howdex.procedure_status(procedure_id),
            "verification_status": self.howdex.procedure_verification_status(
                procedure_id
            ),
        }

    def _remember(self, args: dict[str, Any]) -> dict[str, Any]:
        layer = MemoryLayer(args.get("layer", "semantic"))
        memory_type = (
            MemoryType(args["type"])
            if args.get("type")
            else _default_type(layer)
        )
        memory = self.howdex.remember(
            content=str(args["content"]),
            layer=layer,
            type=memory_type,
            importance=float(args.get("importance", 0.5)),
            ttl=args.get("ttl"),
            source="mcp",
        )
        return {
            "memory_id": memory.id,
            "layer": memory.layer.value,
            "type": memory.type.value,
        }

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        results = self.howdex.search(
            str(args["query"]),
            layer=args.get("layer"),
            top_k=int(args.get("top_k", 5)),
            min_score=float(args.get("min_score", 0.1)),
        )
        return {
            "matches": [
                {
                    "memory_id": result.memory.id,
                    "score": result.score,
                    "matched_by": result.matched_by,
                    "content": result.memory.content,
                    "layer": result.memory.layer.value,
                    "type": result.memory.type.value,
                }
                for result in results
            ]
        }

    def _load_codex_entries(self) -> list[dict[str, Any]]:
        if self.codex_path is None:
            return []
        root = self.codex_path
        paths: list[Path]
        if root.is_file():
            paths = [root]
        else:
            paths = []
            for directory in (root / "entries", root / "procedures", root):
                if directory.is_dir():
                    paths.extend(sorted(directory.glob("*.json")))
        entries: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if _is_codex_entry(payload):
                entries.append(payload)
        entries.sort(key=lambda item: str(item.get("id") or item.get("title") or ""))
        return entries

    def _warnings_for(self, candidates: list[Any], environment: Any) -> list[str]:
        warnings: list[str] = []
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                warnings.extend(_policy_warnings(candidate))
                staleness_warning = _staleness_warning(candidate, environment)
                if staleness_warning:
                    warnings.append(staleness_warning)
                status = str(candidate.get("status") or "").casefold()
                if status in {"candidate", "experimental"}:
                    warnings.append(
                        f"{candidate.get('id') or candidate.get('title')}: {status} entry requires current verification"
                    )
            elif isinstance(candidate, Procedure):
                status = self.howdex.procedure_status(candidate.id)
                if status != "verified":
                    warnings.append(
                        f"{candidate.id}: {status} procedure requires current verification"
                    )
        return _unique(warnings)

    # ------------------------------------------------------------------ #
    # sync endpoints (HTTP mode)
    # ------------------------------------------------------------------ #
    def handle_sync_push(self, ops: list[dict]) -> dict:
        applied = 0
        for op in ops:
            try:
                self.howdex.store.apply_remote_op(op)
                applied += 1
            except Exception:  # noqa: BLE001
                pass
        return {"applied": applied}

    def handle_sync_pull(self) -> dict:
        return {"ops": self.howdex.store.pending_sync_ops()}


def _ok(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_json(payload: dict[str, Any]) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, indent=2, sort_keys=True, default=str),
            }
        ],
        "structuredContent": payload,
        "isError": False,
    }


def _tool_error(payload: dict[str, Any]) -> dict:
    result = _tool_json(payload)
    result["isError"] = True
    return result


def run_stdio(
    *,
    path: Optional[str] = None,
    embedder: Optional[str] = None,
    codex_path: Optional[str] = None,
    readonly: bool = False,
) -> None:
    """Run the local MCP server over newline-delimited JSON-RPC stdio."""
    server = MCPServer(
        path=path,
        embedder=embedder,
        codex_path=codex_path,
        readonly=readonly,
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"howdex-mcp: invalid JSON: {exc}\n")
            continue
        response = server.handle(request)
        if response:
            sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
            sys.stdout.flush()


def run_http(
    host: str = "127.0.0.1",
    port: int = 7331,
    *,
    path: Optional[str] = None,
    embedder: Optional[str] = None,
    codex_path: Optional[str] = None,
    readonly: bool = False,
) -> None:
    """Run the same local MCP server over HTTP for local clients."""
    server = MCPServer(
        path=path,
        embedder=embedder,
        codex_path=codex_path,
        readonly=readonly,
    )

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, body: dict) -> None:
            data = json.dumps(body, sort_keys=True).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(body or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON"})
                return

            if self.path == "/mcp":
                self._json(200, server.handle(payload))
            elif self.path == "/sync/push":
                if readonly:
                    self._json(403, {"error": "readonly"})
                else:
                    self._json(200, server.handle_sync_push(payload.get("ops", [])))
            else:
                self._json(404, {"error": "not found"})

        def do_GET(self):  # noqa: N802
            if self.path == "/sync/pull":
                self._json(200, server.handle_sync_pull())
            elif self.path == "/health":
                self._json(200, {"status": "ok", "time": time.time()})
            else:
                self._json(404, {"error": "not found"})

        def log_message(self, *args):  # noqa: D401
            sys.stderr.write(f"[howdex-mcp] {args[0] % args[1:]}\n")

    httpd = HTTPServer((host, port), Handler)
    sys.stderr.write(f"howdex-mcp listening on http://{host}:{port}\n")
    sys.stderr.write("  POST /mcp        — MCP JSON-RPC\n")
    sys.stderr.write("  POST /sync/push  — receive ops\n")
    sys.stderr.write("  GET  /sync/pull  — get pending ops\n")
    sys.stderr.write("  GET  /health     — health check\n")
    httpd.serve_forever()


def _default_type(layer: MemoryLayer) -> MemoryType:
    return {
        MemoryLayer.WORKING: MemoryType.CONTEXT,
        MemoryLayer.SEMANTIC: MemoryType.FACT,
        MemoryLayer.EPISODIC: MemoryType.SESSION,
        MemoryLayer.PROCEDURAL: MemoryType.WORKFLOW,
    }[layer]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _first_text(step: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = step.get(key)
        if value is not None:
            return str(value)
    return ""


def _command_arguments(step: Mapping[str, Any]) -> dict[str, Any]:
    if step.get("cmd") is not None:
        return {"cmd": step.get("cmd")}
    if step.get("command") is not None:
        return {"cmd": step.get("command")}
    return {}


def _candidate_id(candidate: Any, index: int) -> str:
    if isinstance(candidate, Mapping):
        return str(
            candidate.get("procedure_id")
            or candidate.get("id")
            or candidate.get("task_signature")
            or candidate.get("title")
            or f"procedure_{index}"
        )
    return str(
        getattr(candidate, "procedure_id", None)
        or getattr(candidate, "id", None)
        or getattr(candidate, "task_signature", None)
        or f"procedure_{index}"
    )


def _policy_warnings(entry: Mapping[str, Any]) -> list[str]:
    policy = entry.get("policy")
    if not isinstance(policy, Mapping):
        with telemetry.span(
            "howdex.policy.evaluate",
            {
                "howdex.codex_entry_id": entry.get("id") or "",
                "howdex.policy_status": "unknown",
            },
        ):
            pass
        return []
    warnings: list[str] = []
    if policy.get("requires_human_review"):
        warnings.append(f"{entry.get('id')}: policy requires human review")
    source_policy = policy.get("source_artifacts")
    if source_policy and source_policy != "included":
        warnings.append(f"{entry.get('id')}: source artifacts are {source_policy}")
    for forbidden in _string_list(policy.get("forbidden")):
        warnings.append(f"{entry.get('id')}: forbidden: {forbidden}")
    with telemetry.span(
        "howdex.policy.evaluate",
        {
            "howdex.codex_entry_id": entry.get("id") or "",
            "howdex.policy_status": "warning" if warnings else "ok",
        },
    ):
        pass
    return warnings


def _staleness_warning(entry: Mapping[str, Any], environment: Any) -> str | None:
    if not has_compatibility_metadata(entry):
        return None
    decision = evaluate_codex_staleness(entry, environment)
    if decision.status == "fresh":
        return None
    return f"{entry.get('id')}: {staleness_guidance_text(decision)}"


def _is_codex_entry(payload: Any) -> bool:
    return isinstance(payload, Mapping) and {
        "id",
        "title",
        "status",
        "learned_facts",
        "verification",
        "policy",
    } <= set(payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique
