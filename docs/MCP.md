# Howdex MCP Server

Howdex is the open verification layer for agent know-how. It turns execution
traces into portable, receipt-backed procedures that any agent can reuse and
any enterprise can audit.

Howdex ships a local MCP server so Claude Desktop, Cursor, Windsurf,
Codex-style workflows, and other MCP-compatible agents can use operational
memory without a cloud service or mandatory LLM dependency.

The server runs on your machine, uses local SQLite by default, and exposes
Howdex procedural memory plus optional local Codex guidance as MCP tools.

MCP is the local adapter surface for verified agent procedures. It does not
make candidate procedures verified, does not require a hosted Howdex service,
and does not turn guidance into executable authority.

## Installation

Install Howdex in your environment:

```bash
python -m pip install -e ".[dev]"
```

Start the local MCP server over stdio:

```bash
howdex mcp
```

Use an explicit database:

```bash
howdex mcp --db ~/.howdex/howdex.db
```

Expose a local Codex catalogue:

```bash
howdex mcp --codex ./codex
```

Run read-only:

```bash
howdex mcp --readonly
```

## Local DB path

By default Howdex uses:

```text
~/.howdex/howdex.db
```

You can override this with either the normal Howdex global `--path` option or
the MCP-specific `--db` option:

```bash
howdex --path /path/to/howdex.db mcp
howdex mcp --db /path/to/howdex.db
```

## Claude Desktop config example

Use an absolute database path in app config files because shell expansion of
`~` is not guaranteed:

```json
{
  "mcpServers": {
    "howdex": {
      "command": "howdex",
      "args": [
        "mcp",
        "--db",
        "/Users/you/.howdex/howdex.db",
        "--codex",
        "/Users/you/path/to/Howdex/codex"
      ]
    }
  }
}
```

For read-only guidance/search access:

```json
{
  "mcpServers": {
    "howdex-readonly": {
      "command": "howdex",
      "args": [
        "mcp",
        "--db",
        "/Users/you/.howdex/howdex.db",
        "--codex",
        "/Users/you/path/to/Howdex/codex",
        "--readonly"
      ]
    }
  }
}
```

## Cursor/Windsurf-style config example

Most MCP-compatible editors use the same shape:

```json
{
  "mcpServers": {
    "howdex": {
      "command": "howdex",
      "args": [
        "mcp",
        "--db",
        "/absolute/path/to/howdex.db",
        "--codex",
        "/absolute/path/to/codex"
      ]
    }
  }
}
```

## Tools

The server exposes:

- `howdex_remember_trace` — store a structured execution trace as episodic
  memory.
- `howdex_learn` — consolidate episodes into reusable procedures.
- `howdex_guidance` — retrieve relevant procedures/Codex entries and render
  bounded Markdown guidance.
- `howdex_codex_search` — search a local Codex catalogue with status, policy,
  and staleness metadata.
- `howdex_codex_publish` — publish one local procedure as a candidate or
  verified Codex entry.
- `howdex_attach_receipt` — attach inspectable verification evidence to a
  procedure.

Compatibility helpers for generic remember/search/stats are also available.

## Security model

Howdex MCP is operational memory, not executable authority.

- It does not require OpenAI, hosted services, or network access.
- It stores data in local SQLite.
- It never includes source artifacts in guidance unless `include_source=true`
  is explicitly requested.
- It never marks candidate procedures as verified without inspectable receipts.
- It respects guidance budgets, relevance filtering, Codex policy warnings, and
  staleness/incompatibility metadata where available.
- `--readonly` disables mutating tools such as trace recording, learning,
  publishing, receipt attachment, and deletion.

Agents must still obey your sandbox, approval, and tool-execution policy. A
procedure is guidance until a current verifier succeeds.

## Example workflow

### 1. Remember a trace

Call `howdex_remember_trace`:

```json
{
  "task": "recover Docker Compose health endpoint",
  "steps": [
    {
      "tool": "bash",
      "args": {"cmd": "cat runtime.env"},
      "observation": "HEALTH_MODE=degraded"
    },
    {
      "tool": "fs.write",
      "args": {"path": "runtime.env", "content": "HEALTH_MODE=ready"},
      "observation": "wrote runtime.env"
    },
    {
      "tool": "bash",
      "args": {"cmd": "docker compose up -d --build --force-recreate"},
      "observation": "container recreated"
    },
    {
      "tool": "bash",
      "args": {"cmd": "curl -sS -i http://127.0.0.1:52617/health"},
      "observation": "SUCCESS: HTTP 200 body=healthy"
    }
  ],
  "outcome": "success",
  "metadata": {"source": "agent-run"}
}
```

### 2. Learn

Call `howdex_learn`:

```json
{
  "min_samples": 1
}
```

### 3. Request guidance

Call `howdex_guidance`:

```json
{
  "objective": "Recover a broken Docker Compose /health endpoint",
  "constraints": ["Use only local Docker Compose commands"],
  "environment": {"tool": "docker compose", "version": "2.27.0"},
  "max_chars": 4000,
  "verified_only": false
}
```

The response includes Markdown guidance, selected procedure IDs, omitted count,
context budget used, and warnings.

### 4. Publish a candidate Codex entry

Call `howdex_codex_publish`:

```json
{
  "procedure_id": "procedure-id-from-learn",
  "registry_path": "./.howdex/codex"
}
```

Unverified procedures publish as `candidate` and include a receipt requirement.
Only procedures with inspectable verified receipts publish as `verified`.
