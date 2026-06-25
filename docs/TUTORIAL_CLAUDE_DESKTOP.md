# Howdex MCP Server with Claude Desktop — Tutorial

This tutorial shows you how to connect Howdex's MCP server to Claude Desktop so your agent can record traces, learn verified procedures, and get guidance — all from the Claude Desktop chat interface.

## Prerequisites

- [Claude Desktop](https://claude.ai/download) installed
- Python 3.9+
- Howdex installed: `pip install howdex-ai`

## Step 1: Install Howdex

```bash
pip install howdex-ai
```

Verify:
```bash
howdex --version
# should print: howdex 0.4.0
```

## Step 2: Initialize a Howdex database

```bash
howdex init
# creates ~/.howdex/howdex.db
```

## Step 3: Configure Claude Desktop

Open your Claude Desktop config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add the Howdex MCP server:

```json
{
  "mcpServers": {
    "howdex": {
      "command": "howdex",
      "args": ["mcp", "--db", "~/.howdex/howdex.db", "--codex", "~/.howdex/codex"],
      "env": {
        "HOWDEX_EMBEDDER": "st"
      }
    }
  }
}
```

Save the file and restart Claude Desktop.

## Step 4: Verify the connection

Open a new chat in Claude Desktop. You should see a tools icon (hammer) in the input area. Click it — you should see 10 Howdex tools:

- `howdex_remember_trace` — store an execution trace
- `howdex_learn` — consolidate traces into procedures
- `howdex_guidance` — get guidance for a new task
- `howdex_codex_search` — search the Codex
- `howdex_codex_publish` — publish a procedure
- `howdex_attach_receipt` — attach a verification receipt
- `howdex_remember` — store a fact
- `howdex_search` — search memories
- `howdex_forget` — delete a memory
- `howdex_stats` — show database stats

## Step 5: Record your first trace

Type this into Claude Desktop:

> I just fixed a bug where a Node.js app couldn't find the 'express' module. I ran `node app.js`, got "Cannot find module 'express'", ran `npm install express`, then ran `node app.js` again and it worked. Remember this as a Howdex trace.

Claude will call `howdex_remember_trace` to store the trace.

## Step 6: Learn a procedure

> Learn a procedure from the trace you just recorded.

Claude will call `howdex_learn` to consolidate the trace into a reusable procedure.

## Step 7: Get guidance for a new task

> I have a different Node.js app that can't find the 'cors' module. What should I do?

Claude will call `howdex_guidance` with your objective. The guidance will include the learned procedure ("install the missing module") even though the original was for 'express', not 'cors'.

## Step 8: Attach a verification receipt

> I ran `npm install cors` and the app started successfully. Attach a verification receipt.

Claude will call `howdex_attach_receipt` with the verifier command and exit code. The procedure is now `verified` — not just "observed".

## Step 9: Publish to a local Codex

> Publish the verified procedure to a local Codex.

Claude will call `howdex_codex_publish`. The procedure is now a governed, auditable artifact with a receipt.

## Step 10: Generate a compliance report

From your terminal:

```bash
howdex compliance --framework soc2
```

This generates an audit-ready report mapping your verification receipt to SOC 2 controls (CC7.1, CC8.1, etc.) with a deterministic hash for reproducibility.

## Troubleshooting

### "howdex: command not found" in Claude Desktop

The MCP server uses the `howdex` command from your PATH. If Claude Desktop can't find it, use the full path:

```json
"command": "/usr/local/bin/howdex"
```

Or if you installed in a venv:

```json
"command": "/path/to/your/venv/bin/howdex"
```

### "sentence-transformers not found"

Either install it (`pip install howdex-ai[st]`) or change the env to `"HOWDEX_EMBEDDER": "hash"` (keyword-only matching).

### Tools don't appear in Claude Desktop

1. Check the JSON is valid: `python -c "import json; json.load(open('path/to/config.json'))"`
2. Restart Claude Desktop completely (quit, not just close window)
3. Check the MCP server logs in Claude Desktop's developer tools

## Next steps

- Pull the public registry: `howdex public-registry pull --to ~/.howdex/registry`
- Search for verified procedures: `howdex public-registry search "docker" --from-dir ~/.howdex/registry`
- Contribute your verified procedures: `howdex public-registry push ./codex/procedures/ --to ./my-registry/`
- Read the [Receipt Spec](https://github.com/rossbuckley1990-hash/Howdex/blob/main/docs/RECEIPT_SPEC.md)
- Read the [Compliance docs](https://github.com/rossbuckley1990-hash/Howdex#compliance-and-governance-the-enterprise-wedge)
