"""MCP (Model Context Protocol) server for Howdex.

Exposes Howdex as an MCP tool server so any MCP-compatible agent
(Claude Desktop, Cursor, etc.) can call ``remember``, ``search``, and ``learn``.

Two transport modes:

  * **stdio** — for local agent integrations (Claude Desktop, etc.)
  * **HTTP**  — for remote agents

The protocol is JSON-RPC 2.0 over the chosen transport. We implement
the MCP ``tools/list`` and ``tools/call`` methods.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Optional

from howdex import Howdex
from howdex.core.types import MemoryLayer, MemoryType


# ---------------------------------------------------------------------- #
# Tool definitions
# ---------------------------------------------------------------------- #
TOOLS = [
    {
        "name": "howdex_remember",
        "description": (
            "Store a memory in the agent's long-term memory. Use this when the user "
            "shares a preference, fact, or when the agent learns something worth "
            "remembering for future interactions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The memory content"},
                "layer": {
                    "type": "string", "enum": ["working", "semantic", "episodic", "procedural"],
                    "default": "semantic",
                    "description": "Memory layer",
                },
                "type": {
                    "type": "string",
                    "enum": [t.value for t in MemoryType],
                    "description": "Fine-grained memory type (optional)",
                },
                "importance": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "ttl": {"type": "number", "description": "TTL in seconds (optional)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "howdex_search",
        "description": (
            "Retrieve relevant memories for a query. Use this at the start of a "
            "conversation or before making decisions to ground the agent in past "
            "context, user preferences, and learned procedures."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "layer": {
                    "type": "string",
                    "enum": ["working", "semantic", "episodic", "procedural"],
                },
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
                "min_score": {"type": "number", "default": 0.1},
            },
            "required": ["query"],
        },
    },
    {
        "name": "howdex_learn",
        "description": (
            "Trigger consolidation: analyze past episodic memories and extract "
            "reusable procedures. Call this periodically (e.g. end of session) "
            "to convert experience into procedural knowledge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_samples": {"type": "integer", "default": 3, "minimum": 2},
            },
        },
    },
    {
        "name": "howdex_forget",
        "description": "Delete a memory by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "howdex_stats",
        "description": "Return database stats (memory counts, layer distribution, etc.)",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class MCPServer:
    """MCP server core. Transport-agnostic — call ``handle()`` per request."""

    def __init__(self, *, path: Optional[str] = None, embedder: Optional[str] = None):
        self.howdex = Howdex(path=path, embedder=embedder)
        self._lock = threading.RLock()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                return _ok(req_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "howdex", "version": "0.1.0"},
                })
            if method == "tools/list":
                return _ok(req_id, {"tools": TOOLS})
            if method == "tools/call":
                return self._handle_tool_call(req_id, params)
            if method == "notifications/initialized":
                return {}  # notification, no response
            return _err(req_id, -32601, f"method not found: {method}")
        except Exception as e:  # noqa: BLE001
            return _err(req_id, -32603, f"internal error: {e}")

    def _handle_tool_call(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments", {}) or {}

        with self._lock:
            if name == "howdex_remember":
                m = self.howdex.remember(
                    content=args["content"],
                    layer=args.get("layer", "semantic"),
                    type=args.get("type", "fact"),
                    importance=args.get("importance", 0.5),
                    ttl=args.get("ttl"),
                )
                return _ok(req_id, _tool_text(
                    f"✓ remembered [{m.layer.value}/{m.type.value}] (id={m.id[:8]})\n{m.content}"
                ))

            if name == "howdex_search":
                results = self.howdex.search(
                    args["query"],
                    layer=args.get("layer"),
                    top_k=args.get("top_k", 5),
                    min_score=args.get("min_score", 0.1),
                )
                if not results:
                    return _ok(req_id, _tool_text("(no relevant memories found)"))
                lines = [f"Found {len(results)} relevant memories:\n"]
                for r in results:
                    lines.append(
                        f"[{r.score:.2f} {r.matched_by}] {r.memory.content[:200]}\n"
                        f"  layer={r.memory.layer.value} type={r.memory.type.value} "
                        f"id={r.memory.id[:8]}\n"
                    )
                return _ok(req_id, _tool_text("\n".join(lines)))

            if name == "howdex_learn":
                procs = self.howdex.learn(min_samples=args.get("min_samples", 3))
                if not procs:
                    return _ok(req_id, _tool_text("(no new procedures learned)"))
                lines = [f"Learned {len(procs)} procedure(s):\n"]
                for p in procs:
                    lines.append(
                        f"• {p.task_signature}\n"
                        f"  success_rate={p.success_rate:.2f} samples={p.sample_count} "
                        f"steps={len(p.steps)}"
                    )
                return _ok(req_id, _tool_text("\n".join(lines)))

            if name == "howdex_forget":
                self.howdex.forget(args["memory_id"])
                return _ok(req_id, _tool_text(f"✓ forgot {args['memory_id'][:8]}"))

            if name == "howdex_stats":
                return _ok(req_id, _tool_text(json.dumps(self.howdex.stats(), indent=2)))

            return _err(req_id, -32601, f"unknown tool: {name}")

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


def _tool_text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


# ---------------------------------------------------------------------- #
# stdio transport
# ---------------------------------------------------------------------- #
def run_stdio(*, path: Optional[str] = None, embedder: Optional[str] = None) -> None:
    """Run the MCP server reading JSON-RPC messages from stdin, writing to stdout.

    Each message is a single JSON object on its own line (newline-delimited JSON).
    """
    server = MCPServer(path=path, embedder=embedder)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"howdex-mcp: invalid JSON: {e}\n")
            continue
        response = server.handle(request)
        if response:  # notifications return {}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


# ---------------------------------------------------------------------- #
# HTTP transport (also serves sync endpoints)
# ---------------------------------------------------------------------- #
def run_http(host: str = "127.0.0.1", port: int = 7331, *,
             path: Optional[str] = None, embedder: Optional[str] = None) -> None:
    server = MCPServer(path=path, embedder=embedder)

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
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
                resp = server.handle(payload)
                self._json(200, resp)
            elif self.path == "/sync/push":
                resp = server.handle_sync_push(payload.get("ops", []))
                self._json(200, resp)
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
    sys.stderr.write(f"  POST /mcp        — MCP JSON-RPC\n")
    sys.stderr.write(f"  POST /sync/push  — receive ops\n")
    sys.stderr.write(f"  GET  /sync/pull  — get pending ops\n")
    sys.stderr.write(f"  GET  /health     — health check\n")
    httpd.serve_forever()
