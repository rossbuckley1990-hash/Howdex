# Howdex

## Own your AI learning loop.

**Howdex is procedural memory for AI agents.**

Howdex helps teams own their AI learning loop. It turns execution traces into
verified reusable procedures that remain inside the customer's perimeter and
work across models, agents, frameworks, and clouds.

Execution traces are the raw material. Howdex turns them into procedural
capital: verified guidance, failed-attempt memory, policy context, and Codex
entries.

> One expensive discovery. Many cheap executions.

If your learning loop only works inside one model stack or cloud, you do not
fully own it.

Howdex is not chat history. It is not prompt stuffing. It is not a vector database full of notes. It is a memory system for **how work was actually done**.

---

## Verified agent procedures

Howdex is the open verification layer for agent know-how: it turns execution
traces into portable, receipt-backed procedures that any agent can reuse and
any enterprise can audit.

A Howdex procedure is learned from execution traces, rendered as operational
guidance, governed by policy and staleness metadata, and promoted from
candidate to verified only when inspectable receipts prove a task-relevant
verifier succeeded.

This makes Howdex more than an agent memory library. It is infrastructure for
verified agent procedures: reusable know-how that can travel across models,
frameworks, and clouds while keeping proof, provenance, and policy visible.

Procedures are guidance, not executable authority. They help agents avoid
starting cold, but they do not bypass sandboxing, approvals, current
environment checks, or verification.

See [docs/STANDARD.md](docs/STANDARD.md) and
[docs/PROTOCOL.md](docs/PROTOCOL.md).

---

## Why Howdex Exists

Modern AI agents can reason, call tools, write files, run commands, and interact with systems. But most still behave as if every task is the first time they have ever seen the world.

They repeatedly:

- rediscover the same setup steps,
- rerun known-bad commands,
- forget which recovery path actually worked,
- collapse local and production workflows into one unsafe procedure,
- fail to transfer a hard-won operational fix into a related task,
- spend expensive model calls solving problems that were already solved once.

Howdex gives agents durable procedural memory.

It watches episodes, records tool calls, separates failures from successful paths, extracts reusable structure, masks environment-specific values, preserves evidence, and renders the learned procedure back as agent-usable guidance.

---

## The Core Idea

A messy trace like this:

```text
node app.js
→ Cannot find module 'express'

npm install express

node app.js
→ App running!
```

becomes a reusable procedure:

```text
Step 1: node <FILE_PATH_1>
Step 2: npm install <PKG_1>
Step 3: node <FILE_PATH_1>
```

With bindings such as:

```text
<FILE_PATH_1> = app.js
<PKG_1> = express
```

Later, when a different task mentions `server.js` and `cors`, Howdex can render guidance such as:

```text
Fast path for this task:
- The current objective names `cors` as the missing package.
- You may skip the known-bad reproduction step if the evidence is already present.
- Run `npm install cors`.
- Verify with `node server.js`.
```

That is the difference between remembering text and remembering procedure.

---

## What Howdex Learns

Howdex can learn from:

- shell commands,
- structured tool calls,
- file writes,
- observations,
- failure messages,
- successful recoveries,
- repeated workflows,
- parallel spans,
- verification receipts,
- context facts such as `env_type=PROD`.

It extracts:

- canonical actions,
- parameterized arguments,
- ordered procedure steps,
- preconditions,
- success evidence,
- failed attempts to avoid,
- source episode IDs,
- support and confidence counts,
- context-conditioned variants.

Procedure evidence remains inspectable:

```python
receipt = memory.verify_procedure(
    procedure.id,
    verifier_type="test",
    verifier_command="python -m pytest -q",
    expected_signal="passed",
    observed_signal="all tests passed",
    exit_code=0,
    environment_fingerprint={"python": "3.12", "platform": "linux"},
    artifact_hashes={"wheel": "sha256:..."},
)

memory.procedure_status(procedure.id)
# verified
```

Without independent evidence, a learned procedure is either `unverified` or
`observed_episode_support`. Failed and stale receipts remain visible as
`failed_verification` and `stale`; guidance never silently promotes an observed
episode into independent proof.

---

## Why this is different from renting model intelligence

Model calls can solve individual tasks, but the learning from those runs often
stays trapped in a transcript, prompt, vendor-specific feature, or one agent
stack. Howdex stores the operational learning itself: what was tried, what
failed, what worked, what verifier proved it, and which policy/environment
context mattered.

That makes the learning loop portable. A team can change models, swap agent
frameworks, move clouds, or run local-first without throwing away the procedural
capital accumulated from prior execution.

---

## Own your loop, not your cloud lock-in

Howdex is designed for perimeter-owned memory:

- traces can be recorded locally;
- procedures can be rendered without mandatory LLM calls;
- receipts and provenance remain inspectable;
- Codex entries can move between agents and environments;
- policy context travels with the procedure instead of living in one prompt.

If your learning loop only works inside one model stack or cloud, you do not
fully own it.

---

## What the benchmark proves

The committed Docker A/B n20 log at
`benchmark_results/docker_hard_ab_n20_20260623_172737.txt` records:

| Metric | Control | Treatment |
|---|---:|---:|
| n per arm | 20 | 20 |
| successes | 7 | 18 |
| success rate | 0.35 | 0.90 |
| avg_attempts | 13.00 | 8.75 |
| memory_used | 0/20 | 20/20 |
| source_pasted | 0/20 | 0/20 |

The logged lift was `+0.55` success rate with `+4.25` fewer attempts on
average. The verdict was `PASS`: “Howdex transferred a verified local Docker
recovery procedure without pasting source.”

The benchmark framing is: identical base prompt; only learned memory differs.

This demonstrates one verified procedure transferring to fresh agents. It does
not yet prove compounding over many accumulated traces.

---

## What it does not prove yet

The Docker n20 result is intentionally narrow. It does not claim:

- production-safe autonomous execution;
- universal memory across every task family;
- that every Codex entry is verified;
- that no-synthesis transfer is solved;
- that compounding has been proven across many accumulated traces.

It proves a specific operational transfer: one verified Docker recovery
procedure helped fresh agents recover a fresh broken local runtime under the
logged benchmark conditions.

---

## Trust calibration: measuring whether procedure confidence predicts reality

Howdex includes a procedure trust calibration harness:

```bash
HOWDEX_CALIBRATION_DRY_RUN=1 python procedure_trust_calibration_test.py
```

The harness measures whether confidence bins and verification states line up
with observed success. Dry-run mode validates the metric machinery only. Dogfood
mode can read existing `dogfood-results/` summaries as internal evidence, but it
must report `INSUFFICIENT DATA` until enough real held-out dogfood samples
exist. Dogfood calibration is not external adoption, traction, users, or market
validation.

See [docs/TRUST_CALIBRATION.md](docs/TRUST_CALIBRATION.md).

---

## Reproduce the result

Run the headline Docker A/B benchmark with:

```bash
make bench-docker-n20
```

Equivalent command:

```bash
HOWDEX_DOCKER_TRIALS=20 HOWDEX_DOCKER_MAX_TURNS=15 python3 real_docker_recovery_ab_test.py
```

Prerequisites:

- Docker running;
- `python:3.12-alpine` already present locally;
- `OPENAI_API_KEY` set for the live model calls;
- no automatic image pulls.

---

## Key Capabilities

### Parameterized Procedural Memory

Howdex does not simply remember one concrete command.

It learns reusable structure:

```text
npm install <PKG_1>
python3 <SCRIPT_PATH_1> <INPUT_FILE_1>
openssl enc -d ... -pass pass:<DERIVED_SECRET_1>
```

Supported masking includes:

- file paths,
- package names,
- working directories,
- command arguments,
- generated artifacts,
- repeated variable bindings,
- context-specific procedure variants.

---

### Agent-Ready Guidance Rendering

Raw memories are too dense for agents to use reliably.

Howdex renders learned procedures into concise operational guidance:

```text
# PAST LEARNED PROCEDURE

When fixing a missing Node dependency:

Step 1: Run `node <FILE_PATH_1>` to reproduce the missing dependency error.
Step 2: If the error says `Cannot find module '<PKG_1>'`, run `npm install <PKG_1>`.
Step 3: Run `node <FILE_PATH_1>` again to verify the fix.

When applying this template:
- Bind `<FILE_PATH_1>` to the current target file.
- Bind `<PKG_1>` to the missing module named in the error.
```

This makes memory usable by future agents without forcing them to parse raw traces.

For large team Codexes, Howdex can also budget retrieval before rendering so a
generic procedure catalogue does not flood the prompt with irrelevant memory:

```python
from howdex.core.guidance import GuidanceBudget, select_guidance_procedures

selection = select_guidance_procedures(
    "recover Docker Compose health endpoint",
    codex_entries,
    GuidanceBudget(
        max_procedures=3,
        max_guidance_chars=6000,
        min_relevance_score=0.05,
        suppress_stale_or_incompatible=True,
        include_verified_only=False,
    ),
)
```

Selection is deterministic. It ranks by task relevance, prefers verified and
fresh procedures, suppresses stale or incompatible entries by default, avoids
near-duplicate procedure spam, and records why each omitted entry was excluded.
`render_agent_guidance(..., retrieval_budget=budget, debug=True)` includes the
selected count, omitted count, context budget used, and optional omission
reasons.

---

### Use Howdex from any MCP-compatible agent

Howdex includes a local MCP server for Claude Desktop, Cursor, Windsurf,
Codex-style workflows, and other MCP-compatible agents:

```bash
howdex mcp --db ~/.howdex/howdex.db --codex ./codex
```

The server exposes tools to remember traces, learn procedures, request bounded
guidance, search local Codex entries, publish candidate/verified Codex entries,
and attach verification receipts. It requires no OpenAI dependency, no hosted
service, and no cloud database. Source artifacts are excluded from guidance by
default.

See [docs/MCP.md](docs/MCP.md) for configuration examples and the security
model.

---

### Govern procedures like code

Howdex includes local Codex governance commands so teams can lint, diff, merge,
deprecate, trust, verify, and policy-check operational memory before it becomes
shared agent guidance.

```bash
howdex codex lint codex
howdex codex diff left.json right.json
howdex codex policy-check codex
```

Verified procedures require inspectable receipt metadata, and signed-verified
procedures require valid signed attestations. See
[docs/CODEX_GOVERNANCE.md](docs/CODEX_GOVERNANCE.md).

---

### Trace why memory was selected

Howdex can emit optional OpenTelemetry spans for procedural-memory decisions:
retrieval, selection, rendering, procedure injection, Codex search/publish,
receipt attachment, policy checks, and staleness evaluation.

```bash
python -m pip install "howdex-ai[otel]"
```

Without OpenTelemetry installed, tracing is a no-op and Howdex imports normally.
Telemetry uses IDs, statuses, counts, and scores; it does not emit raw source
artifacts by default. See [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md).

---

### Failed-Attempt Separation

Howdex does not just store the final answer.

It can preserve the difference between:

```text
python custom_parser.py data.zdat     # failed
python3 custom_parser.py data.zdat    # succeeded
```

and render the failed path separately:

```text
Avoid these failed attempts from the original trace:
- run `python custom_parser.py data.zdat`
```

That matters because good operational memory is not only “what worked”; it is also “what not to waste time on again.”

---

### Context-Conditioned Variants

The same task can require different procedures depending on environment.

For example:

```text
db_migration [env_type=LOCAL]
db_migration [env_type=PROD]
```

Local migration may safely reset and recreate a database. Production migration may require backup, migration, verification, and rollback evidence.

Howdex keeps those variants separate so agents do not apply local shortcuts to production systems.

---

### Cross-Task Semantic Retrieval

Howdex can retrieve a procedure learned from one task and apply the reusable part to a different but related task.

Example:

```text
S3 upload failed with AccessDenied
→ aws sso login --profile staging
→ retry succeeded
```

Later, a Lambda deploy in the same staging environment can retrieve the authentication recovery before wasting tool calls on the same failure.

This is procedural transfer, not same-task replay.

---

### Artifact-Aware Tool Memory

Agents sometimes invent tools: scripts, parsers, probes, repair commands, generated config, or local utilities.

Howdex can preserve those generated artifacts as part of procedural memory.

In the real MacGyver filesystem benchmark, a teacher agent created a parser tool on disk, verified it, and Howdex later helped a student agent recreate and run that tool in a fresh sandbox.

---

### Language-Agnostic Operational Transfer

Howdex can also carry the algorithmic idea of a procedure across execution environments.

In the polyglot crypto transfer benchmark, a Python-enabled teacher discovered a decryption procedure. A Bash-only student could not run or write Python and received no pasted Python source. Howdex supplied operational memory, and the student translated the learned procedure into Bash/OpenSSL execution.

---

## Real Benchmarks

Howdex now includes real local execution benchmarks, not just mocked behavioural demos.

### 1. Real MacGyver Filesystem Artifact Replay

File:

```text
real_macgyver_test.py
```

What it tests:

- real temporary filesystem,
- real generated `custom_parser.py`,
- real data files,
- real subprocess execution,
- deletion of the teacher’s parser before the student run,
- student re-creation from Howdex memory.

What it proves:

```text
Howdex can preserve and re-surface a teacher-created source-code artifact, and a student can recreate and execute it on a fresh real filesystem task.
```

Honest scope:

```text
Artifact replay regression test. Not yet a no-memory capability-lift test.
```

Run:

```bash
python3 real_macgyver_test.py
```

---

### 2. Real MacGyver A/B Hard-Tool Benchmark

File:

```text
real_macgyver_ab_test.py
```

What it tests:

- hard local binary-ish file format,
- real temporary filesystem,
- real subprocess verification,
- teacher discovery run,
- no-memory control arm,
- Howdex-memory treatment arm,
- no pasted source code,
- repeated stochastic student trials.

Representative result:

```text
Control:
  trials: 5
  successes: 2
  success_rate: 0.40
  avg_attempts: 7.20

Treatment:
  trials: 5
  successes: 5
  success_rate: 1.00
  avg_attempts: 2.60
  howdex_memory_used: 5/5
  source_pasted: 0/5

Delta:
  success_rate_lift: +0.60
  attempt_reduction: +4.60
```

What it proves:

```text
Howdex improved student success from 40% to 100% on a hard real-filesystem tool-reuse benchmark while reducing average attempts, without pasting source code.
```

Run:

```bash
HOWDEX_AB_TRIALS=5 HOWDEX_AB_MAX_TURNS=20 python3 real_macgyver_ab_test.py
```

---

### 3. Polyglot MacGyver Crypto Transfer Benchmark

File:

```text
polyglot_macgyver_test.py
```

What it tests:

- real OpenSSL encryption and decryption,
- real `seed.txt` and `vault.enc`,
- Python-enabled teacher discovery,
- Bash-only student environment,
- Python file writes and Python execution banned for students,
- no-memory control arm,
- Howdex-memory treatment arm,
- no pasted Python source,
- repeated trials.

Representative result:

```text
Teacher:
  success: True
  attempts: 1

Control:
  trials: 5
  successes: 0
  success_rate: 0.00
  avg_attempts: 11.00

Treatment:
  trials: 5
  successes: 5
  success_rate: 1.00
  avg_attempts: 3.60
  howdex_memory_used: 5/5
  source_pasted: 0/5

Delta:
  success_rate_lift: +1.00
  attempt_reduction: +7.40
```

What it proves:

```text
Howdex transferred Python-discovered operational knowledge into Bash-only execution without pasting source code.
```

The treatment receives operational facts, not source code:

```text
- read seed.txt
- reverse the seed string before hashing
- hash the reversed seed bytes with no trailing newline
- use the SHA256 hex digest as the OpenSSL password
- decrypt vault.enc with AES-256-CBC and PBKDF2
```

Then the Bash-only student must translate that into real shell/OpenSSL execution.

Run:

```bash
HOWDEX_POLY_TRIALS=5 HOWDEX_POLY_MAX_TURNS=12 python3 polyglot_macgyver_test.py
```

Honest scope:

```text
This proves language-agnostic operational transfer using synthesized Howdex memory facts. It does not yet prove fully automatic no-synthesis abstraction from arbitrary traces.
```

---

## Current Evidence Summary

| Benchmark | Control | Treatment | Source Pasted? | Real Execution? | Result |
|---|---:|---:|---:|---:|---|
| Real MacGyver Filesystem | n/a | pass | artifact replay | yes | pass |
| Real MacGyver A/B Hard Tool | 40% | 100% | no | yes | pass |
| Polyglot Crypto Transfer | 0% | 100% | no | yes | pass |

The defensible headline:

```text
Howdex turns successful agent execution traces into reusable operational memory that improves future agent success on real local execution tasks.
```

The intentionally avoided overclaim:

```text
Howdex does not claim production-safe autonomous execution, arbitrary tool generation safety, or fully automatic AGI-scale abstraction.
```

---

## Installation

```bash
pip install howdex
```

For local development:

```bash
git clone https://github.com/rossbuckley1990-hash/Howdex.git
cd Howdex
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m pytest
```

Some real benchmarks require:

```text
OPENAI_API_KEY
openssl
python3
bash
Docker running
python:3.12-alpine present locally
```

The Docker benchmark never auto-pulls images. If `python:3.12-alpine` is not
already available locally, pull it yourself before running the benchmark:

```bash
docker pull python:3.12-alpine
```

Benchmark logs from the Makefile targets are written under
`benchmark-results/` and are intentionally ignored by git unless you decide to
publish a specific result.

---

## Quick Start

```python
from howdex import Howdex

memory = Howdex(path=".howdex.db")

memory.start_session("fix_missing_dependency")

memory.log_tool_call(
    "execute_bash",
    {"cmd": "node app.js"},
    "Error: Cannot find module 'express'",
)

memory.log_tool_call(
    "execute_bash",
    {"cmd": "npm install express"},
    "added 62 packages",
)

memory.log_tool_call(
    "execute_bash",
    {"cmd": "node app.js"},
    "App running on port 3000",
)

memory.end_session("success")

procedures = memory.learn(min_samples=1)

suggestions = memory.suggest_procedure(
    "Fix a Node app that cannot find module cors",
    top_k=3,
)

for suggestion in suggestions:
    print(suggestion)
```

---

## Typical API

```python
from howdex import Howdex

memory = Howdex(path=".howdex.db", embedder="hashing")

memory.start_session("task_signature")
memory.log_tool_call("tool_name", {"arg": "value"}, "observation")
memory.end_session("success")

procedures = memory.learn(min_samples=1)
suggestions = memory.suggest_procedure("new task description", top_k=5)
```

The exact internal schema continues to evolve, but the product boundary is stable:

```text
trace → learn → retrieve → render guidance → future agent acts with memory
```

---

## Design Principles

### 1. Evidence Before Guidance

Howdex should not render a procedure as guidance unless it has evidence that the procedure worked.

---

### 2. Failures Are First-Class

A failed command is not noise. It is operational information.

Knowing which path failed prevents future agents from wasting attempts.

---

### 3. Parameterize the World

Do not memorize `express` when the reusable concept is `<PKG_1>`.

Do not memorize `data_1.zdat` when the reusable concept is `<INPUT_FILE_1>`.

---

### 4. Context Matters

A procedure that is safe locally may be dangerous in production.

Howdex should preserve context and render warnings when context changes.

---

### 5. Real Verifiers Beat Self-Report

A benchmark only counts when an external state change, process result, receipt, or verifier confirms the outcome.

The model saying “DONE” is not enough.

---

## What Howdex Is Not

Howdex is not:

- an autonomous agent framework,
- a browser automation tool,
- a hosted orchestration system,
- a vector database wrapper,
- a replacement for sandboxing or policy enforcement,
- proof that arbitrary generated code is safe to reuse.

Howdex is the memory layer underneath agents that need to remember operational know-how.

---

## Roadmap

Near-term:

- stronger real benchmark suite,
- no-synthesis abstraction experiments,
- richer renderer for procedure guidance,
- safer artifact handling,
- procedure provenance and receipts,
- improved hydration of raw examples from storage,
- benchmark folders for staged vs real tests.

Future:

- policy-aware memory rendering,
- sandbox-aware generated tool replay,
- multi-agent memory merge with receipts,
- production connectors,
- hosted registry of verified operational procedures.

---

## Development

Run tests:

```bash
python -m pytest
```

Run the real benchmark suite manually:

```bash
python3 real_macgyver_test.py
HOWDEX_AB_TRIALS=5 HOWDEX_AB_MAX_TURNS=20 python3 real_macgyver_ab_test.py
HOWDEX_POLY_TRIALS=5 HOWDEX_POLY_MAX_TURNS=12 python3 polyglot_macgyver_test.py
```

The real benchmarks use live model calls and may incur API cost.

### Headline Docker A/B benchmark

The headline Docker recovery benchmark is reproducible through Make:

```bash
make bench-docker-n20
```

This runs:

```bash
HOWDEX_DOCKER_TRIALS=20 HOWDEX_DOCKER_MAX_TURNS=15 python3 real_docker_recovery_ab_test.py
```

Prerequisites:

- Docker must be running.
- `python:3.12-alpine` must already be present locally.
- `OPENAI_API_KEY` must be set for the live model calls.
- The benchmark does not auto-pull Docker images or use external services beyond
  the configured live model API.

For a smaller smoke run:

```bash
make bench-docker
```

---

## Positioning

The short version:

```text
Howdex is procedural memory for agents.
```

The sharper version:

```text
Howdex turns one expensive agent discovery into reusable operational intelligence.
```

The benchmark-backed version:

```text
Howdex improved success from 0% to 100% in a real Python-to-Bash crypto transfer benchmark without pasting source code.
```

---

## License

See `LICENSE`.
