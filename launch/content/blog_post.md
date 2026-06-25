# Howdex: The Verification Layer for AI Agents

**Or: Why "the LLM said it worked" is not proof, and what to do about it.**

## The problem

You deployed an AI agent. It ran a task, said "DONE", and you moved on. Later you discovered the fix was wrong — the agent hallucinated success. Worse, if you're using a memory system, that hallucinated "success" is now permanently stored as a procedure. Future agents will follow the same hallucinated steps and fail the same way.

This is the **hallucinated success problem**, and it's the #1 blocker for agent adoption in production. Every agent-memory system I looked at — mem0, Letta, Zep — has this gap. They record what was said and what facts were learned, but none of them verify that the work actually succeeded before crystallizing it into permanent memory.

## The insight

An LLM's claim of success is an **observation**, not a **verification**. "I fixed it" is what the model thinks happened. A verification is an objective, deterministic check: did the test suite pass? Did the HTTP endpoint return 200? Did the build exit 0?

Howdex is built around this distinction. It records agent execution traces, learns reusable procedures from successful runs, and — critically — requires a **deterministic, non-LLM verifier** to confirm success before a procedure can be consolidated. The LLM cannot self-certify.

## How it works

### 1. Record traces

Every agent tool call is logged as a structured step:

```python
from howdex import Howdex, instrument, session_scope

mem = Howdex(path="agent.db", embedder="hashing")

@instrument(mem)
def search_code(query: str) -> str:
    return subprocess.run(["rg", query]).stdout

@instrument(mem)
def edit_file(path: str, old: str, new: str) -> str:
    # ... fix the bug ...
    return "fixed"

with session_scope(mem, "fix_missing_dependency"):
    search_code("def load_config")
    edit_file("config.py", "old_path", "new_path")
    # session_scope auto-ends: success on clean exit, failure on exception
```

The `@instrument` decorator and `session_scope` context manager handle all the telemetry — zero boilerplate.

### 2. Learn procedures

After a successful run, `learn()` consolidates the trace into a parameterized procedure:

```python
procs = mem.learn(min_samples=1)
# Returns a Procedure with canonical steps, confidence score, and source episode IDs
```

The canonicalizer recognizes 50+ tool verbs (execute, edit, search, read, write, transform, validate, repair, etc.) and parameterizes them (e.g., `node app.js` → `execute_file` with `<FILE_PATH_1>`).

### 3. Verify with BootProof

The **BootProof gate** blocks `learn()` from consolidating a session unless a deterministic verifier confirmed the result:

```python
from howdex import BootProof

gate = BootProof(mem)

# Verify with a real exit code
gate.verify_with_exit_code(
    procedure_id=procs[0].id,
    verifier_command="pytest tests/",
    exit_code=0,
)

# Or HTTP status
gate.verify_with_http_status(
    procedure_id=procs[0].id,
    verifier_command="curl -sf http://localhost:8080/health",
    status_code=200,
)

# learn() through the gate REFUSES unverified sessions
verified_procs = gate.learn(min_samples=1)
```

An LLM "I think it worked" is explicitly NOT in the accepted verifier types. The valid types are: `exit_code`, `http_status`, `test_runner`, `bash`, `build`, `healthcheck`, `file_exists`, `sql_query`.

### 4. Generate compliance reports

Once you have verified receipts, generate an audit-ready compliance report:

```bash
howdex compliance --framework soc2 --output ./reports/soc2_q3.md
howdex compliance --framework eu-ai-act
howdex compliance --framework nist-ai-rmf
```

Each report maps receipts to the framework's control objectives (SOC 2 CC7.1/CC8.1, EU AI Act Articles 9/12/15, NIST AI RMF GOVERN-1/MEASURE-1/MANAGE-1) and includes a deterministic SHA-256 hash for audit reproducibility.

### 5. Consult the public registry

Agents with no local memory can consult the public registry:

```bash
# Pull the public registry (4 verified procedures, live on GitHub)
howdex public-registry pull --to ~/.howdex/registry

# Search for a matching procedure
howdex public-registry search "docker compose health recovery" --from-dir ~/.howdex/registry
```

Or programmatically:

```python
guidance = mem.guidance(
    "Fix a Docker Compose service that won't start",
    max_chars=4000,
    registry_dir="~/.howdex/registry",  # auto-searches the registry
)
```

Matching verified procedures are merged into the guidance automatically.

### 6. Contribute back

```bash
# Push your verified procedures to a registry
howdex public-registry push ./my-codex/procedures/ --to ./my-registry/
```

Only `status=verified` procedures are accepted — the network effect is built on proof, not vibes.

## The receipt primitive

The core abstraction is the **Howdex Verification Receipt** — a JSON object recording:

- What verifier was run (`verifier_command`)
- What it observed (`observed_signal`)
- What it concluded (`status: verified | failed`)
- When it ran (`verified_at`)
- A content hash for tamper detection (`receipt_id`)
- An optional HMAC signature (`signature`)

The receipt spec is published as a standalone, framework-agnostic document (docs/RECEIPT_SPEC.md) designed to be cited by auditors and referenced in AI governance policies.

## Why this matters

Enterprises deploying agents in 2026 face a compliance wall: the EU AI Act (Articles 9, 12, 15), NIST AI RMF, ISO 42001, and SOC 2's AI criteria all require proof that AI systems were tested and verified. The Howdex receipt primitive is the standardized artifact that satisfies this need.

The market for AI governance tooling is projected at $50-100B by 2030. Existing players (Holistic AI, Credo AI) have raised $50-150M each at $100-500M valuations — and they don't have anything like Howdex's receipt primitive. They track policies and risk assessments; Howdex tracks verified agent actions with cryptographic proof.

## Try it

```bash
pip install git+https://github.com/rossbuckley1990-hash/Howdex.git
python examples/first_time_dev.py
```

The `first_time_dev.py` script walks through the full loop in 60 seconds: record a trace → learn a procedure → attach a real receipt → pull guidance for a fresh task → publish to a local Codex → lint it.

**Repo:** https://github.com/rossbuckley1990-hash/Howdex
**Public registry:** https://github.com/rossbuckley1990-hash/howdex-public-registry
**Receipt spec:** https://github.com/rossbuckley1990-hash/Howdex/blob/main/docs/RECEIPT_SPEC.md
**701 tests passing. Zero required dependencies. Local-first. MCP-compatible.**
