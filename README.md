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
howdex --path /tmp/howdex.db init
howdex --path /tmp/howdex.db remember "user loves python"
howdex --path /tmp/howdex.db search "python preference"
```

This should print a match (the hash embedder matches on shared tokens —
`python` appears in both the stored memory and the query). If you see
`(no memories matched)`, make sure you ran `init` first.

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

> **Note on embedders**: Howdex tries `sentence-transformers`
> (all-MiniLM-L6-v2) first for production-quality semantic matching. If
> `sentence-transformers` is not installed, it falls back to the `hash`
> embedder (keyword-overlap only — matches on shared tokens, not
> semantics). All examples in this README work with either embedder.
> To install the neural backend: `pip install sentence-transformers`
> (or `pip install -e ".[st]"` for development). For CI/offline runs,
> set `HOWDEX_EMBEDDER=hash`.

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

## Compliance and governance (the enterprise wedge)

Howdex is the **audit and verification layer for AI agents**. Every
procedure's success is backed by a cryptographically-signed receipt from
a deterministic, non-LLM verifier. This is the artifact compliance teams
need for SOC 2, EU AI Act, NIST AI RMF, and ISO 42001.

Generate an audit-ready compliance report:

```bash
# SOC 2 (AICPA Trust Services Criteria)
howdex --path ~/.howdex/howdex.db compliance --framework soc2 --output ./reports/soc2_q3.md

# EU AI Act (Articles 9, 12, 15)
howdex --path ~/.howdex/howdex.db compliance --framework eu-ai-act

# NIST AI RMF (GOVERN, MAP, MEASURE, MANAGE)
howdex --path ~/.howdex/howdex.db compliance --framework nist-ai-rmf
```

Each report maps Howdex receipts to the framework's control objectives,
includes a deterministic `report_hash` for audit reproducibility, and
documents that verification requires a non-LLM checker (the BootProof gate).

See the standalone **[Howdex Verification Receipt Specification](docs/RECEIPT_SPEC.md)**
for the framework-agnostic receipt format. This spec is designed to be
cited by auditors and referenced in AI governance policies.

## Public procedure registry (the network effect)

Howdex ships with a public registry of verified procedures — the "npm
for agent procedures" primitive. The valuable, shareable artifact is the
*verification* (the receipt), not the procedure itself.

```bash
# Pull the public registry locally
howdex public-registry pull --to ~/.howdex/registry

# List available verified procedures
howdex public-registry list --from-dir ~/.howdex/registry

# Search for a procedure
howdex public-registry search "fix missing node module" --from-dir ~/.howdex/registry

# Contribute your verified procedures
howdex public-registry push ./my-codex/procedures/ --to ./howdex-public-registry/
```

Only `status=verified` procedures are accepted into the registry — the
network effect is built on proven procedures, not vibes. Set
`$HOWDEX_REGISTRY_URL` to point to a self-hosted registry for enterprise
air-gapped deployments.

## Production hardening (architectural review fixes)

Howdex ships with five hardening features that address the friction points
a senior engineer will scrutinize when evaluating Howdex for core
infrastructure. All are opt-in; defaults preserve existing behavior.

### 1. Telemetry validation (Observer Effect mitigation)

`log_tool_call()` now validates its inputs and records integrity warnings
(visible via `memory.integrity_warnings()`) when:

- `arguments` is not a dict (sloppy orchestrators that pass a string or
  list will not crash Howdex, but the warning surfaces the problem).
- `name` is empty or non-string.
- `observation` contains a failure marker (`error`, `failed`,
  `traceback`, `no module named`, ...) — this is not itself a problem,
  but `end_session` cross-references these warnings to catch
  hallucinated successes (see #4 below).

```python
mem.start_session("fix_bug")
mem.log_tool_call("execute_command", "ls -la", "ok")  # malformed args
warnings = mem.integrity_warnings()
# [{"code": "malformed_arguments", "message": "log_tool_call('execute_command')..."}]
```

### 2. Context window management

`guidance()` now supports `max_procedures`, `min_relevance_score`, and
`verified_only` parameters for precise budget control. When `max_chars`
is small (≤ 2000), Howdex automatically tightens filtering to avoid
context collapse on smaller models (e.g. gpt-4o-mini):

```python
# Tight budget for a small model
guidance = mem.guidance(
    "Fix the bug",
    max_chars=1500,
    max_procedures=2,
    min_relevance_score=0.15,
    verified_only=True,
)

# Inspect the budget allocation before injecting
report = mem.guidance_budget_report("Fix the bug", max_chars=1500)
print(report["context_pressure"])  # "low" | "medium" | "high"
print(report["omitted"])  # which procedures were dropped and why
```

### 3. Canonicalization drift detection

When an agent changes how it formats JSON arguments between runs, the
canonicalizer may produce steps with low `canonical_confidence`. Use
`detect_canonicalization_drift()` to surface at-risk procedures, then
call `propose_abstraction()` to bridge the format gap with an auditable
LLM-assisted proposal:

```python
at_risk = mem.detect_canonicalization_drift(min_confidence=0.5)
for entry in at_risk:
    print(f"{entry['task_signature']}: {entry['at_risk_steps']}/{entry['total_steps']} steps at risk")
    print(f"  {entry['suggestion']}")
# Then: proposal = propose_abstraction([proc1, proc2], llm_provider=...)
```

CLI: `howdex drift --min-confidence 0.5`

### 4. Verifier requirement (strict mode)

Howdex is only as good as the verifier you provide. If your agent
hallucinates a fix and calls `end_session("success")` without an
objective check, Howdex would normally memorize the hallucination.
Strict mode prevents this:

```python
# Per-session strict mode
mem.start_session("fix_bug")
mem.log_tool_call("execute_command", {"cmd": "make build"}, "Error: build failed")
ep = mem.end_session("success", require_receipt=True)
# ep.outcome == "unverified" (downgraded from "success")
# learn() will NOT consolidate this into a procedure

# Global strict mode via constructor
mem = Howdex(path="...", embedder="hashing", require_receipt_for_success=True)
```

Even without strict mode, an `unverified_success` integrity warning is
recorded whenever `end_session("success")` is called after a
failure-marker observation and no verified receipt is attached.

CLI: `howdex --require-receipt learn` (applies to all operations in this
CLI invocation).

### 5. System prompt snippet (prompt engineering)

Howdex provides the Markdown guidance, but your LLM will ignore it
unless the system prompt instructs it to pay attention. Use
`render_system_prompt_snippet()` to generate a ready-to-paste snippet:

```python
from howdex import render_system_prompt_snippet

system_prompt = base_prompt + "\n\n" + render_system_prompt_snippet(strict=True)
# Then inject Howdex guidance into the user message
```

CLI: `howdex system-prompt --strict` (prints the snippet to stdout).

The snippet tells the LLM to: look for the `# HOWDEX OPERATIONAL MEMORY`
section, treat it as prior operational memory (not source code), avoid
repeating failed attempts, prefer verified procedures, and run a real
verifier before claiming success.

## Day-2 operational hardening

Three features that address the brutal Day-2 operational risks a production
deployment will face. All are opt-in.

### BootProof — deterministic verifier gate (GIGO mitigation)

The #1 Day-2 risk: "If your LLM hallucinates a success and you blindly
pass that to Howdex, Howdex will mathematically crystallize a
hallucination into a permanent procedure." BootProof blocks this:

```python
from howdex import Howdex, BootProof

mem = Howdex(path="...", embedder="hashing")
gate = BootProof(mem)

# After the agent run, verify with a DETERMINISTIC verifier (not an LLM)
gate.verify_with_exit_code(
    procedure_id=proc.id,
    verifier_command="pytest tests/",
    exit_code=0,
)
gate.verify_with_http_status(
    procedure_id=proc.id,
    verifier_command="curl -sf http://localhost:8080/health",
    status_code=200,
)
gate.verify_with_test_runner(
    procedure_id=proc.id,
    verifier_command="pytest tests/",
    exit_code=0,
    observed_signal="651 passed",
)

# learn() through the gate REFUSES unverified sessions
procs = gate.learn(min_samples=1)
# Sessions without a deterministic receipt are blocked, not consolidated.
# gate.rejected_sessions lists what was blocked and why.
```

BootProof only accepts receipts from recognized deterministic verifier
types (`exit_code`, `http_status`, `test_runner`, `bash`, `build`,
`healthcheck`, `file_exists`, `sql_query`). An LLM "I think it worked"
verdict is NOT in this set and will be rejected.

### Trust calibration + needle-in-haystack risk (context window sizing)

The #2 Day-2 risk: "If HNSW retrieves 10 overlapping procedures, injecting
all of them will cause context collapse for smaller models like Llama-3."

```python
# Inspect the trust distribution across all procedures
curve = mem.trust_calibration_curve()
print(curve["verified_ratio"])           # 0.0–1.0
print(curve["recommended_top_k"])        # 1 if ratio<0.3, 2 if<0.6, else 3
print(curve["recommended_verified_only"]) # True if ratio<0.3

# Assess context-collapse risk for a specific objective
risk = mem.needle_in_haystack_risk("fix the bug", max_chars=6000)
print(risk["risk_level"])     # "low" | "medium" | "high"
print(risk["overlapping_count"]) # how many procedures share >50% of steps
print(risk["recommendation"]) # human-readable mitigation
```

Use these together: if `verified_ratio < 0.3`, set `verified_only=True`
and `top_k=1` in `guidance()` to avoid injecting unproven noise. If
`needle_in_haystack_risk` returns "high", lower `top_k` and raise
`min_relevance_score`.

### Zero-boilerplate instrumentation (integration tax mitigation)

The #3 Day-2 risk: "Howdex requires you to structure your agent as a
rigorous CI/CD pipeline with explicit telemetry. Developers migrating
from LangChain will complain about the boilerplate."

Three zero-boilerplate helpers eliminate this:

```python
from howdex import Howdex, instrument, session_scope

mem = Howdex(path="...", embedder="hashing")

# 1. @instrument decorator — auto-logs any function as a tool call
@instrument(mem)
def search_code(query: str, glob: str = "*.py") -> str:
    return subprocess.run(["rg", query, "--glob", glob], ...).stdout

@instrument(mem, name="run_tests")
def pytest_runner(target: str) -> str:
    return subprocess.run(["pytest", target], ...).stdout

# 2. session_scope context manager — auto-starts/ends sessions
with session_scope(mem, "fix_bug") as m:
    result = search_code("def load_config")
    # ... do work ...
# session auto-ended: success on clean exit, failure on exception

# 3. auto_instrument_langchain — one-line LangChain adapter
from howdex.instrument import auto_instrument_langchain
auto_instrument_langchain(mem, [tool1, tool2, tool3])
# Now every tool.run() call is logged — no agent code changes needed
```

The decorator handles exceptions (logs them as failure observations and
re-raises), is safe outside a session (no-op), and uses the function
signature to build the arguments dict automatically.

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
howdex --path ~/.howdex/howdex.db codex publish ./.howdex/codex
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
