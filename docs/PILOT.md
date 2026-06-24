# Howdex developer pilot

This pilot pack helps external developers try Howdex with real agents and
report what happens. It does not claim that external pilot users already exist.

Howdex is procedural memory for agents that do work. It records execution
traces, learns reusable procedures, renders guidance for related tasks, and can
attach verifier receipts before publishing Codex entries.

Procedures are guidance, not executable authority. Do not use this pilot to
claim production-safe autonomous execution.

## 15-minute local setup

1. Create a Python environment.

   ```bash
   python -m venv .venv
   PATH="$PWD/.venv/bin:$PATH" python -m pip install -U pip
   ```

2. Install Howdex.

   ```bash
   PATH="$PWD/.venv/bin:$PATH" python -m pip install howdex-ai
   ```

   For local repository development:

   ```bash
   PATH="$PWD/.venv/bin:$PATH" python -m pip install -e ".[dev]"
   ```

3. Initialize a local database.

   ```bash
   HOWDEX_EMBEDDER=hash howdex --path ~/.howdex/howdex.db init
   ```

4. Start the local MCP server.

   ```bash
   HOWDEX_EMBEDDER=hash howdex mcp --db ~/.howdex/howdex.db --codex ./codex
   ```

No Howdex cloud is required. The only cloud involved is whatever model or agent
provider you choose to use.

## Local SQLite path

The default local database is:

```text
~/.howdex/howdex.db
```

For pilots, use a dedicated DB if you want clean results:

```bash
HOWDEX_EMBEDDER=hash howdex mcp --db ./howdex-pilot.db --codex ./codex
```

## MCP config

Example configs are provided in:

- `examples/pilot/claude_desktop_config.example.json`
- `examples/pilot/cursor_mcp_config.example.json`

Copy the shape into your client configuration and adjust paths for your
machine. Do not commit your real private paths or credentials.

## Pilot flow

1. Install Howdex.
2. Start the MCP server.
3. Connect from Claude Desktop, Cursor, Windsurf, or another MCP-compatible
   client.
4. Run an agent task.
5. Use `howdex_remember_trace` or an adapter to record the trace.
6. Run `howdex_learn` or `memory.learn()`.
7. Ask for guidance on a fresh related task.
8. Attach a receipt if a real verifier passed.
9. Publish a candidate or verified Codex entry.
10. Submit feedback or a procedure submission issue.

## Adapter examples

The examples in `examples/pilot/` are import-safe and avoid optional framework
dependencies at import time:

- `langgraph_example.py`
- `langchain_example.py`
- `generic_agent_loop.py`
- `codex_publish_example.py`
- `receipt_attach_example.py`

Use these as wiring examples, not as production policy.

## Inspect local DB and stats

Check local health:

```bash
HOWDEX_EMBEDDER=hash howdex --path ~/.howdex/howdex.db health
```

Inspect counts:

```bash
HOWDEX_EMBEDDER=hash howdex --path ~/.howdex/howdex.db stats
```

List learned procedures:

```bash
HOWDEX_EMBEDDER=hash howdex --path ~/.howdex/howdex.db procedures
```

## Export a Codex entry

Publish local procedures to a local Codex folder:

```bash
HOWDEX_EMBEDDER=hash howdex --path ~/.howdex/howdex.db codex publish ./.howdex/codex
```

Unverified learned procedures publish as `candidate`. A procedure should be
treated as verified only when it has inspectable receipt evidence.

## What data not to share

Do not share:

- secrets, API keys, tokens, passwords, private keys, or credentials;
- customer data;
- proprietary source code;
- private repository names if they are sensitive;
- raw logs that contain secrets or confidential output;
- production hostnames or internal network details;
- real user data.

Prefer sharing sanitized traces, summarized steps, verifier command shape,
receipt status, and Codex entries with source artifacts excluded.

## How to file feedback

Use the pilot feedback issue template:

```text
.github/ISSUE_TEMPLATE/pilot_feedback.yml
```

Include:

- environment;
- agent/model;
- integration path;
- task attempted;
- whether guidance was used;
- whether a procedure was learned;
- whether a receipt was attached;
- what failed or confused you.

## How to submit a verified procedure

Use the procedure submission issue template:

```text
.github/ISSUE_TEMPLATE/procedure_submission.yml
```

Include the procedure title, task family, environment, risk level, policy
constraints, and verification evidence. Confirm that no secrets are included.

## Security warnings

- Howdex guidance is not permission to execute a command.
- Verify commands in your current environment.
- Keep source artifacts excluded unless you intentionally review and share
  them.
- Do not attach receipts that expose secrets.
- Do not mark candidate procedures as verified without receipt evidence.
- Do not run side-effecting or destructive actions without your own approval
  controls.

## No production autonomy claim

This pilot evaluates whether Howdex helps real developers reuse procedural
memory. It does not claim production-safe autonomous execution, broad
compounding, external adoption, or universal agent memory.
