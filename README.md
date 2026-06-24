# Howdex

## The open verification layer for agent know-how

Howdex turns execution traces into portable, receipt-backed procedures that
agents can reuse and enterprises can audit.

Howdex is built around verified agent procedures: reusable know-how learned
from real runs, governed by policy/staleness metadata, and promoted from
candidate to verified only when inspectable receipts prove a task-relevant
verifier passed.

Agents should not start every run cold. Howdex records what agents tried, what
failed, what worked, and what verified the result. It turns that evidence into
operational guidance that can move across models, frameworks, and clouds.

Howdex is local-first, vendor-neutral, and audit-friendly. Procedures are
guidance, not executable authority. Candidate procedures are not verified.

## 60-second explanation

Most agent memory systems remember facts or conversation context. Howdex
focuses on procedural know-how: how work was actually done.

A trace like this:

```text
node app.js
→ Cannot find module 'express'

npm install express

node app.js
→ App running
```

can become a reusable procedure:

```text
Step 1: run node <FILE_PATH_1>
Step 2: install missing package <PKG_1>
Step 3: rerun node <FILE_PATH_1>
Step 4: verify the app starts
```

Howdex stores the supporting evidence, failed attempts, parameter bindings,
policy context, staleness metadata, and verification receipts so future agents
can use the procedure without treating it as blind authority.

Why not just memory? Memory stores experience. Howdex procedures carry proof,
provenance, policy, portability, receipts, staleness metadata, and a verifier
contract.

Why not a cloud agent platform? Howdex is local-first and portable. The
customer owns the learning loop instead of trapping procedural capital inside
one model stack, framework, or cloud.

## Quickstart

Install:

```bash
python -m pip install howdex-ai
```

For local development:

```bash
git clone https://github.com/rossbuckley1990-hash/Howdex.git
cd Howdex
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

Minimal Python use:

```python
from howdex import Howdex

memory = Howdex(path=".howdex.db", embedder="hashing")

memory.start_session("fix_missing_dependency")
memory.log_tool_call(
    "execute_bash",
    {"cmd": "node app.js"},
    "Error: Cannot find module 'express'",
)
memory.log_tool_call(
    "execute_bash",
    {"cmd": "npm install express"},
    "added packages",
)
memory.log_tool_call(
    "execute_bash",
    {"cmd": "node app.js"},
    "App running",
)
memory.end_session("success")

procedures = memory.learn(min_samples=1)
guidance = memory.guidance(
    "Fix a Node app that cannot find module cors",
    max_chars=4000,
)
print(guidance)
```

CLI smoke test:

```bash
HOWDEX_EMBEDDER=hash howdex --path /tmp/howdex.db init
HOWDEX_EMBEDDER=hash howdex --path /tmp/howdex.db remember "user loves python"
HOWDEX_EMBEDDER=hash howdex --path /tmp/howdex.db search "python preference"
```

### First-time developer? Run the full loop in one command

If you're evaluating Howdex for the first time, run:

```bash
python examples/first_time_dev.py
```

This walks through the entire value proposition end-to-end with visible
output: record a trace → learn a procedure → attach a real receipt → pull
guidance for a fresh related task → publish to a local Codex → lint it.
Leaves you with a real, inspectable verified Codex entry in
`./first_time_dev_codex/`.

> **Note on embedders**: The `hash` embedder (default for the CLI smoke
> test) is keyword-overlap only — it matches on shared tokens, not
> semantics. That's why the search query above uses `"python preference"`
> (shares `python` with the stored memory) rather than `"programming
> preference"` (no shared tokens). For semantic matching (e.g. "user
> loves python" ↔ "programming preference"), install the optional
> sentence-transformers backend and use `HOWDEX_EMBEDDER=st`:
>
> ```bash
> python -m pip install -e ".[st]"
> HOWDEX_EMBEDDER=st howdex --path /tmp/howdex.db init
> HOWDEX_EMBEDDER=st howdex --path /tmp/howdex.db remember "user loves python"
> HOWDEX_EMBEDDER=st howdex --path /tmp/howdex.db search "programming preference"
> ```

## MCP quickstart

Run Howdex as a local MCP server:

```bash
howdex mcp --db ~/.howdex/howdex.db --codex ./codex
```

Use this from Claude Desktop, Cursor, Windsurf, Codex-style workflows, or any
MCP-compatible agent. The server exposes tools to remember traces, learn
procedures, request guidance, search Codex entries, publish Codex entries, and
attach receipts.

Howdex MCP requires no OpenAI dependency, no hosted service, and no cloud
database. Source artifacts are excluded by default.

### Wire it into your agent

Ready-to-use config snippets are in [`examples/pilot/`](examples/pilot/):

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "howdex": {
      "command": "howdex",
      "args": ["mcp", "--db", "~/.howdex/howdex.db", "--codex", "/path/to/your/codex"],
      "env": { "HOWDEX_EMBEDDER": "hash" }
    }
  }
}
```

**Cursor** — add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "howdex": {
      "command": "howdex",
      "args": ["mcp", "--db", "~/.howdex/howdex.db", "--codex", "/path/to/your/codex"],
      "env": { "HOWDEX_EMBEDDER": "hash" }
    }
  }
}
```

After adding the config and restarting your agent, you should see `howdex_*`
tools available (e.g. `howdex_remember_trace`, `howdex_learn`,
`howdex_guidance`, `howdex_codex_search`). Try asking your agent: *"remember
this trace as a Howdex session, then learn a procedure from it"*.

See [docs/MCP.md](docs/MCP.md) and [`examples/pilot/`](examples/pilot/) for
full config examples and adapter code for LangChain, LangGraph, and generic
agent loops.

## Codex and receipt quickstart

The Howdex Codex is a machine-readable catalogue of operational memory. It is
not a prompt library and not executable authority.

Lint the bundled Codex:

```bash
howdex codex lint codex
howdex codex policy-check codex
howdex codex verify codex
```

Publish learned procedures to a local Codex folder:

```bash
HOWDEX_EMBEDDER=hash howdex --path ~/.howdex/howdex.db codex publish ./.howdex/codex
```

Unverified procedures publish as `candidate`. A procedure should be marked
`verified` only when it has inspectable receipt evidence. Signed attestations
are supported for stronger tamper resistance, but they are optional.

See [codex/README.md](codex/README.md), [docs/CODEX_GOVERNANCE.md](docs/CODEX_GOVERNANCE.md),
[docs/CI.md](docs/CI.md), and [docs/ATTESTATIONS.md](docs/ATTESTATIONS.md).

## What a verified procedure is

A verified procedure is operational memory plus evidence:

- learned from one or more execution traces;
- normalized into reusable, parameterized steps;
- linked to source episodes and provenance;
- governed by policy and staleness metadata;
- backed by an inspectable verifier such as a test, build, health check, or
  domain-specific verifier;
- supported by a receipt recording expected signal, observed signal, exit
  code, timestamp, environment fingerprint, and artifact hashes where safe.

Candidate procedures are useful memory, but they are not verified. LLM-assisted
abstraction proposals are also not verified. They can propose equivalence, but
they cannot mark procedures verified, attach receipts, or publish verified
Codex entries without inspectable proof.

Auditable abstraction: optional LLM proposals, deterministic trust.

See [docs/STANDARD.md](docs/STANDARD.md),
[docs/PROTOCOL.md](docs/PROTOCOL.md), and
[docs/AUDITABLE_ABSTRACTION.md](docs/AUDITABLE_ABSTRACTION.md).

## Evidence summary

The committed Docker A/B n20 log at
`evidence/docker_n20/docker_hard_ab_n20_20260623_172737.txt` records one verified
Docker recovery procedure transferring to fresh agents under identical A/B
framing.

| Metric | Control | Treatment |
|---|---:|---:|
| n per arm | 20 | 20 |
| successes | 7 | 18 |
| success rate | 0.35 | 0.90 |
| avg attempts | 13.00 | 8.75 |
| memory used | 0/20 | 20/20 |
| source pasted | 0/20 | 0/20 |

Reproduce:

```bash
make bench-docker-n20
```

This result demonstrates one verified procedure transferring to fresh agents.
It does not prove broad compounding over many accumulated traces.

More benchmark details, including MacGyver, polyglot, trust calibration, and
AWM-style harness notes, live in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## What is not proven yet

Howdex does not claim:

- production-safe autonomous execution;
- universal memory across every task family;
- that every Codex entry is verified;
- that candidate procedures are verified;
- that LLM abstraction proposals are verified;
- live cross-model transfer;
- that dry-run AWM-style harness results are live performance;
- that Howdex has beaten the AWM paper or public WebArena/Mind2Web baselines;
- that compounding over many independent traces or teams has been proven;
- external users, adoption, traction, or market validation unless tracked in
  the pilot evidence files.

Procedures are guidance, not executable authority. Current policy, sandboxing,
approval, environment checks, and verification still govern execution.

## Pilot instructions

If you want to try Howdex with a real agent:

1. Install Howdex.
2. Start the MCP server or use a framework adapter.
3. Run an agent task and record the trace.
4. Learn a procedure.
5. Ask for guidance on a fresh related task.
6. Attach a receipt if a real verifier passed.
7. Publish a candidate or verified Codex entry.
8. Share feedback or a procedure submission using the GitHub issue templates.

Do not share secrets, proprietary source, customer data, private logs, or
production credentials. External pilot users should not be claimed unless they
are recorded in the tracking file.

See [docs/PILOT.md](docs/PILOT.md) and [docs/TUTORIAL.md](docs/TUTORIAL.md).

## Dogfooding Howdex

Howdex development work can be run through the dogfood loop, which records
traces, command logs, receipts, learned procedures, candidate Codex entries,
and sanitized internal summaries.

Dogfood metrics are internal evidence only. They are not external users, adoption, traction, market validation, or proof of broad generalization.

See [docs/DOGFOODING.md](docs/DOGFOODING.md).

## Detailed docs

- [Procedure standard](docs/STANDARD.md)
- [Protocol](docs/PROTOCOL.md)
- [MCP server](docs/MCP.md)
- [Adapters](docs/ADAPTERS.md)
- [Codex governance](docs/CODEX_GOVERNANCE.md)
- [CI](docs/CI.md)
- [Observability](docs/OBSERVABILITY.md)
- [Benchmarks](docs/BENCHMARKS.md)
- [Trust calibration](docs/TRUST_CALIBRATION.md)
- [Dogfooding](docs/DOGFOODING.md)
- [Pilot guide](docs/PILOT.md)
- [Repository structure](docs/REPO_STRUCTURE.md)

## License

See [LICENSE](LICENSE).
