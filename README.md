<div align="center">

# 🧠 Howdex

### The know-how layer for autonomous agents

**Agents should not start every run cold.**

Portable agent know-how · Four-layer memory · Local-first · Framework-agnostic

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-83%20passing-brightgreen.svg)](#testing)
[![Stars](https://img.shields.io/badge/goal-500k%20⭐-yellow.svg)](#why-this-exists)

</div>

---

> **Howdex is the know-how layer for autonomous agents.** It records episodes,
> learns lessons from what failed and what worked, and turns repeated success
> into reusable procedures.

---

## 📖 Table of Contents

- [Why This Exists](#-why-this-exists)
- [The 30-Second Demo](#-the-30-second-demo)
- [Installation](#-installation)
- [Run Without Installing](#-run-without-installing)
- [Dev Install Guide](DEV_INSTALL.md)
- [Core Concepts](#-core-concepts)
- [Portable Know-How](#-portable-know-how)
- [Deterministic Procedural Extraction](#-procedural-extraction-is-deterministic-and-inspectable)
- [Quickstart](#-quickstart)
- [The Four Memory Layers](#-the-four-memory-layers)
- [API Reference](#-api-reference)
- [CLI Reference](#-cli-reference)
- [Framework Adapters](#-framework-adapters)
- [MCP Server](#-mcp-server)
- [Multi-Agent Sync (CRDT)](#-multi-agent-sync-crdt)
- [Architecture](#-architecture)
- [Configuration](#-configuration)
- [Examples](#-examples)
- [Benchmarks](#-benchmarks)
- [Comparison](#-comparison)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [FAQ](#-faq)
- [License](#-license)

---

## 🎯 Why This Exists

Agents should not start every run cold. Yet most agents lose the operational
lessons from prior runs: the context window clears, successful action sequences
disappear into logs, and the next attempt begins from scratch.

| What people do today | Why it sucks |
|---|---|
| Stuff everything in the system prompt | Hits token limits, costs $$ on every call, agent can't find anything |
| Use LangChain's `ConversationBufferMemory` | FIFO buffer, not memory. Loses old context, no learning. |
| Use a vector DB (Chroma, Qdrant) directly | You get similarity search. That's it. No episodic logs, no procedures, no consolidation. |
| Use Letta/MemGPT | Tied to one framework, 12K stars, not the standard. Cloud-first. |
| Use Zep | Proprietary, SaaS-only, you don't own your data. |
| Build it yourself | Every team rebuilds the same wheel. Badly. |

**Howdex is the missing know-how primitive.** It gives agents four connected
memory layers—working, semantic, episodic, and procedural. It records episodes,
learns lessons, and promotes repeated successful traces into portable procedures
that can guide future runs.

```
┌─────────────────────────────────────────────────────────┐
│                    YOUR AI AGENT                         │
│         (LangChain, CrewAI, AutoGen, custom)             │
└──────────────────────┬──────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │     Howdex      │  ← you are here
              │   Memory Layer  │
              └────────┬────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐   ┌──────────┐   ┌────────────┐
   │ SQLite  │   │  Vector  │   │ Knowledge  │
   │  Store  │   │  Index   │   │   Graph    │
   └─────────┘   └──────────┘   └────────────┘
```

**Why this gets 500K stars:**

1. **It's the only unsolved layer.** Inference→Ollama (130K⭐), Orchestration→LangChain (100K⭐), Tool-use→MCP (15K⭐ and growing), Observability→LangFuse (7K⭐). Memory? Nobody owns it.
2. **Zero-config by default.** `pip install howdex-ai` then `from howdex import Howdex`. It just works. No server, no API key, no Docker.
3. **Turns experience into know-how.** Successful traces become inspectable,
   reusable procedures instead of disappearing into logs.
4. **Works with everything.** LangChain, CrewAI, AutoGen, OpenAI Assistants, raw MCP — same API.
5. **Local-first, cloud-optional.** Your data never leaves your machine unless you want it to. Privacy by default.

---

## ⚡ The 30-Second Demo

```python
from howdex import Howdex

memory = Howdex()  # creates ~/.howdex/howdex.db — that's it, you're running

# Store things
memory.remember("User prefers dark mode", layer="semantic", importance=0.9)
memory.remember("Deploy failed: OOM at step 3", layer="episodic")

# Retrieve things
results = memory.search("UI preferences")
print(results[0].memory.content)  # → "User prefers dark mode"

# Learn from experience
memory.start_session("deploy to prod")
memory.log_step("run tests", "ok")
memory.log_step("build", "ok")
memory.end_session("success")

# After a few sessions, consolidate into a procedure:
memory.learn()  # → extracts a reusable "deploy to prod" workflow
```

The core API is **`remember`**, **`search`**, and **`learn`**. The
`recall()` method remains as a compatibility alias and generic retrieval verb.

---

## 📦 Installation

### From PyPI (when published)

```bash
# Basic install (uses hashing embedder by default — works offline)
pip install howdex-ai

# With HNSW for production-grade vector search
pip install howdex-ai[hnsw]

# With sentence-transformers for neural embeddings (recommended)
pip install howdex-ai[st]

# Everything
pip install howdex-ai[full]
```

### From the zip (no PyPI needed)

```bash
unzip howdex-0.3.0.zip
cd howdex

# Option A — install from the prebuilt wheel (zero build tooling required):
pip install dist/howdex_ai-0.3.0-py3-none-any.whl

# Option B — install from source:
pip install .

# Option C — try without installing at all:
python -m howdex init
python -m howdex remember "Hello, world"
python -m howdex search "hello"
```

> 💡 **No `setuptools >= 68` needed.** We require only `setuptools >= 61` (the PEP 621 minimum), and the prebuilt wheel needs no build backend at all. See [`DEV_INSTALL.md`](DEV_INSTALL.md) for full troubleshooting.

**Requirements:** Python 3.9+. That's it. No Docker. No server. No API key.

**Verify it works:**

```bash
howdex --version           # → howdex 0.3.0
howdex init                # creates ~/.howdex/howdex.db
howdex remember "Hello, world"
howdex search "hello" --min-score 0.0
# → [0.83 hybrid] Hello, world
```

---

## 🚀 Run Without Installing

Don't want to commit to an install? You can try Howdex straight from the unzipped source tree. The `howdex/__main__.py` entry point makes `python -m howdex` work without any install step:

```bash
unzip howdex-0.3.0.zip
cd howdex

# Zero install, zero config:
python -m howdex init
python -m howdex remember "User prefers dark mode" --importance 0.9
python -m howdex search "UI preferences" --min-score 0.0
python -m howdex stats

# Run the test suite (also zero install):
python -m pytest

# Run an example:
python examples/quickstart.py
```

This works because Python adds the current directory to `sys.path` when you run `-m`, so the `howdex` package is importable directly. It's the fastest path from "I just downloaded this" to "I have memories stored."

> 📌 For production use, you'll still want `pip install .` (or the wheel) so the `howdex` console script lands on your `PATH`. But for evaluation, demos, and CI smoke tests, the no-install flow is king.

---

## 🧩 Core Concepts

### The Three Primitives

| Primitive | What it does | Human analog |
|---|---|---|
| `remember(content, layer=…)` | Store a memory | Forming a memory |
| `search(query, layer=…)` | Retrieve relevant memories | "Thinking of…" |
| `learn()` | Consolidate episodes → procedures | "Learning from experience" |

`recall()` is retained as a compatibility alias for `search()`.

### The Four Layers

Human memory isn't one thing — it's four systems that evolved for different purposes. Howdex mirrors this:

| Layer | Purpose | TTL | Example |
|---|---|---|---|
| **Working** | Current task scratchpad | ~5 min | "User just asked about X" |
| **Semantic** | Facts, preferences, knowledge | Forever | "User is allergic to peanuts" |
| **Episodic** | What happened (logs, outcomes) | Forever | "Deploy failed at 3am, OOM" |
| **Procedural** | How to do things (learned) | Forever | "To deploy: tests → build → ship" |

The `learn()` command is where the magic happens: it analyzes your episodic memories, finds patterns across successful sessions, and writes **procedures** — your agent's "muscle memory."

---

## 📦 Portable Know-How

Howdex turns agent experience into a small, inspectable portability chain:

- **Episodes are raw runs:** what the agent tried, observed, and ultimately achieved.
- **Lessons are candidate procedures:** repeated patterns extracted from successful episodes.
- **Procedures are reusable know-how:** ordered steps, preconditions, and success evidence that can guide another run.
- **Codex is the local portable registry:** a manifest plus versioned procedure JSON files under `.howdex/codex/`.

Export and restore procedures directly:

```bash
# Writes one JSON file per learned procedure to .howdex/procedures/
howdex procedure export

# Export somewhere explicit
howdex procedure export ./shared-procedures

# Import one file or every JSON file in a directory
howdex procedure import ./shared-procedures
```

Publish and share through a local Codex:

```bash
# Creates .howdex/codex/manifest.json and .howdex/codex/procedures/
howdex codex init

# Promotes locally learned procedures into the local Codex
howdex codex publish

# Pull procedures from another checkout, machine, or mounted team folder
howdex codex pull /path/to/team-project/.howdex/codex
```

Imports are idempotent by canonical task signature, so repeating an import or
pull does not create duplicate procedures. Today Codex is deliberately
local-only. The same manifest-and-artifact model can later back a private
enterprise registry with authentication, policy, review, and distribution.

---

## 🔬 Procedural Extraction Is Deterministic and Inspectable

Howdex does not claim magic procedural extraction. Real agent traces are noisy:
equivalent actions use different words, internal memory calls leak into logs,
and unrelated successful runs can share a task label.

In v0.3, `learn()` uses a local deterministic pipeline. Structured tool calls
are the primary input: Howdex derives action identity from the tool/function
name, typed arguments, and optional metadata exposed by OpenAI, Anthropic,
LangChain, MCP, and similar frameworks.

1. Structured calls retain normalized names such as `github.create_pr`,
   `filesystem.write_file`, or any custom namespaced tool. The vocabulary
   emerges from the agent's tools instead of a hardcoded domain registry.
2. Typed arguments deterministically project a stable, secret-redacted target,
   while a small open ontology classifies intent and side effects.
3. Legacy prose/command traces remain supported through the SWE-oriented
   fallback adapter, which maps text into names such as
   `inspect_package_manifest`, `repair_test_command`, and `run_test_suite`.
4. Successful episodes are grouped using exact canonical sequence matching or
   deterministic subsequence/Jaccard similarity.
5. Internal memory calls, introspection, and unknown-action-dominated traces are
   excluded from executable procedures.
6. Every learned procedure stores confidence, support and success counts,
   source episode IDs, and raw supporting examples.
7. Procedural retrieval filters low-confidence results and returns at most
   three procedures.

Raw evidence remains available for inspection; canonicalisation never erases
the original trace. LLM-assisted consolidation may come later, but the core path
will remain local, deterministic, reproducible, and testable.

Semantic conflict detection is similarly conservative: obvious contradictory
assertions such as “User prefers Python” and “User prefers Rust” are marked
`semantic_conflict_detected` and `requires_review`. Howdex does not attempt
automatic reconciliation.

Record typed calls directly:

```python
with memory.session("publish release") as session:
    session.tool_call(
        "filesystem.read_file",
        {"path": "pyproject.toml"},
        observation="version read",
        metadata={"source": "mcp"},
        outcome="success",
        duration_s=0.08,
    )
    session.tool_call(
        "github.create_pr",
        {"repo": "acme/service", "title": "Release v0.3"},
        observation="pull request created",
        metadata={"source": "openai"},
    )
```

Each structured episode step stores the original `tool_name`, secret-redacted
`tool_args` and `tool_metadata`, plus its deterministic `canonical_action`,
`target`, `intent`, observation, outcome, error, and supplied timing fields.
Steps also carry additive DAG metadata: `step_id`, `parent_step_ids`,
`span_id`, `parallel_group_id`, `started_at`, `ended_at`, and an
`ordering_index` used only for deterministic display.
The original `session.step("plain action", "observation")` API remains
supported, and older prose-only episode rows continue through the legacy
canonicalisation adapter without a database rewrite.

This makes procedural memory domain-portable without an LLM dependency:
healthcare, payments, bioinformatics, infrastructure, and private enterprise
tools—and any agent framework that emits a tool name plus arguments—use the
same deterministic path. English command parsing is now a legacy compatibility
adapter, not the primary canonicalisation mechanism.

### Ingestion pipeline

Howdex treats agent observations and errors as untrusted infrastructure input.
Before episode storage, indexing, recall, or prompt rendering, step output
passes through a deterministic typed middleware pipeline:

```text
ANSI stripping
-> secret redaction
-> progress update compression
-> stack trace compression
-> repeated line compression
-> bounded UTF-8 truncation
```

Each input is represented as an `IngestionRecord` with source, content type,
timestamp, metadata, redaction status, and an ordered list of transformations
that actually changed the content. The default size limit is 65,536 bytes and
retains both the beginning and end with an explicit truncation marker.

```python
from howdex.ingest import IngestionRecord, default_ingestion_pipeline

record = default_ingestion_pipeline().transform(
    IngestionRecord(
        source="cli-agent",
        content=terminal_output,
        content_type="stderr",
    )
)

print(record.content)
print(record.transformations_applied)
```

`log_step()`, `log_tool_call()`, and session-level errors use this pipeline by
default. Stored step JSON includes `observation_ingestion` and, when relevant,
`error_ingestion` audit metadata. Existing databases need no migration because
step records are already extensible JSON.

Advanced callers may pass `sanitize=False` to `log_step()` or
`log_tool_call()` when byte-for-byte terminal formatting is necessary.
Compression and control-sequence stripping are then bypassed, but secret
redaction remains mandatory. A custom `IngestionPipeline` may be supplied to
`Howdex(ingestion_pipeline=...)`; Howdex still applies a final secret-redaction
guard before storage.

### Parameterized procedure templates

Howdex records three deliberately separate forms of every learned step:

| Form | Purpose |
|---|---|
| Raw action | Concrete episode evidence, retained with provenance and secret redaction |
| Canonical action | Stable operation identity such as `install_dependencies` or `filesystem.read_file` |
| Parameterized template | Reusable algorithm with volatile literals replaced by placeholders |

Parameterisation runs deterministically after canonicalisation and before
procedure consolidation. A shared placeholder registry is used for each trace:
the same literal reuses the same placeholder, new values of a type increment
predictably, and structured argument dictionaries are traversed in sorted-key
order.

```text
npm install cors                 -> npm install <PKG_1>
pytest tests/test_auth.py        -> pytest <FILE_PATH_1>
curl http://localhost:3000/health -> curl <URL_1>
{"path": "src/app.js"}           -> {"path": "<FILE_PATH_1>"}
{"repo": "acme/app"}             -> {"repo": "<REPO_1>"}
```

Variable masking is AST-style for structured calls: Howdex walks typed
arguments in sorted-key order and replaces volatile file paths, packages,
URLs, ports, IDs, hashes, emails, branches, environment values, and write
payloads with typed slots. Obvious secret keys and command-line credentials
become `<SECRET_REDACTED>` and are never added to example bindings.

Learned procedure steps retain their canonical action and add a `template`
containing parameterized action text, arguments, and target. Concrete,
secret-redacted examples remain inspectable in `raw_supporting_examples`;
`parameter_bindings` records per-episode examples such as
`{"<PKG_1>": "cors"}`.

For example, these two successful traces:

```text
fs.write path=app.js content=alpha    | fs.write path=server.js content=beta
npm install cors                      | npm install express
```

consolidate into one reusable template:

```text
fs.write path=<FILE_PATH_1> content=<CONTENT_1>
npm install <PKG_1>
```

The procedure API exposes `canonical_steps`, `parameterized_steps`, and
`example_bindings` as compatible derived views; existing `steps` and
`parameter_bindings` remain unchanged. New procedures identify their
deterministic extraction path as `extraction_method="parameterized_lcs"`.

This is the distinction between dumb macro memory and reusable procedural
memory: Howdex learns the stable operation sequence and its parameter slots,
not one hardcoded replay. No LLM is used, and secrets become
`<SECRET_REDACTED>` rather than visible placeholders or exported bindings.

### Canonical learning identity

`learn()` never uses a raw dictionary representation or raw JSON string as
procedure identity. Before LCS and DAG consolidation, every step becomes a
typed `NormalizedLearningStep` containing normalized tool fields, canonical
action metadata, and its parameterized template.

JSON strings are parsed when safe, nested mappings are recursively
key-sorted, and comparison uses canonical JSON:

```python
json.dumps(
    normalized_step,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

Consequently these calls have the same learning identity:

```json
{"tool":"bash","cmd":"npm install cors","cwd":"./"}
{"cwd":"./","cmd":"npm install cors","tool":"bash"}
```

Command whitespace and volatile package/path literals are normalized through
the parameterized command template before comparison. LCS compares canonical
operations, typed parameter slots, and normalized structured arguments—not
concrete literals or the surrounding English wording. Invalid JSON remains a
safe legacy prose step and cannot crash consolidation. The original episode
record remains available as evidence, but its raw formatting is never part of
procedure identity.

### Intent and side-effect classification

Every canonical action carries a deterministic `intent`,
`side_effect_class`, and the exact matched rules in its evidence. Explicit
metadata overrides take precedence for side effects; otherwise Howdex uses
normalized tool-name verbs, schema hints, and argument names. Unknown cases
stay `unknown` rather than being silently treated as safe.

| Intent | Meaning |
|---|---|
| `read` | Read or inspect one resource |
| `search` | Query or find matching resources |
| `list` | Enumerate resources |
| `create` | Create a new resource |
| `update` | Modify an existing resource |
| `write` | Persist or replace content |
| `delete` | Remove a resource |
| `execute` | Run a command, job, build, test, or deployment |
| `transfer` | Move funds or value |
| `notify` | Send or publish a message |
| `approve` | Approve or accept a request |
| `reject` | Reject or deny a request |
| `authenticate` | Establish or verify an identity |
| `unknown` | No deterministic intent rule matched |

| Side-effect class | Meaning |
|---|---|
| `read_only` | Observes state without changing it |
| `local_write` | Changes local files or local execution state |
| `external_write` | Changes or notifies an external system |
| `destructive` | Deletes, drops, purges, or destroys state |
| `financial` | Moves money or changes a financial resource |
| `security_sensitive` | Handles authentication, credentials, or permissions |
| `unknown` | Consequences cannot be classified deterministically |

This inspectable signal is useful for audit logs today and creates a stable
boundary for future Actenon-style approval and BootProof verification
integrations. Classification does not grant permission or claim verification;
it only describes the action deterministically so downstream policy can decide
what evidence or approval is required.

---

## 🚀 Quickstart

### 1. As a Library

```python
from howdex import Howdex

mem = Howdex()  # zero-config

# Semantic memory — facts about the world
mem.remember("Project Atlas deadline is March 15", 
             layer="semantic", type="fact", importance=0.9)

# Working memory — auto-expires in 5 minutes
mem.remember("User is currently on the billing page",
             layer="working", ttl=300)

# Episodic memory — record a full session
mem.start_session("debug auth bug")
mem.log_step("read logs", "found 500 errors at /login")
mem.log_step("check config", "JWT secret was rotated")
mem.log_step("rotate secret back", "fixed")
mem.end_session("success")

# Later, recall
for r in mem.recall("how did we fix the auth bug?", top_k=3):
    print(f"[{r.score:.2f}] {r.memory.content}")

# After many sessions, learn
procs = mem.learn()
# → Procedure(task_signature="debug auth bug", steps=[...], success_rate=0.85)
```

### 2. From the CLI

```bash
# Initialize (creates ~/.howdex/howdex.db)
howdex init

# Store memories
howdex remember "I prefer tabs over spaces" --layer semantic --importance 0.95
howdex remember "standup at 9am" --layer working --ttl 3600

# Search
howdex search "code formatting preference"

# After running your agent for a while, consolidate:
howdex learn
howdex procedures  # see what was learned

# Stats
howdex stats
```

### 3. With Your Existing Agent (LangChain example)

```python
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_openai import ChatOpenAI
from howdex import Howdex
from howdex.adapters import LangChainMemoryAdapter

llm = ChatOpenAI(model="gpt-4o")
memory = LangChainMemoryAdapter(recall=Howdex())

# seed some long-term memory
memory.howdex.remember("User is a senior backend engineer", 
                       importance=0.9)

agent_executor = AgentExecutor(
    agent=agent, tools=tools, memory=memory, verbose=True
)

# Now your agent remembers across sessions.
```

---

## 🧠 The Four Memory Layers

### Working Memory

Working memory is the agent's RAM-like context for the current session.
Items auto-expire after five minutes by default and remain isolated by
`session_id`. Prompt context is selected deterministically: expired items are
excluded, then a fixed score of 65% importance and 35% relative recency decides
which items survive the item and character/token budget. Stable timestamp and
memory-ID tie-breakers make repeated selection reproducible. No LLM
summarisation is involved.

```python
mem.start_session("process refund")
mem.remember(
    "User approved a refund up to $50",
    layer="working",
    importance=0.9,
    source="user",
)
mem.remember(
    "Payment intent is pi_123",
    layer="working",
    ttl=60,
    metadata={"provenance": {"tool": "stripe.lookup"}},
)

prompt_context = mem.get_working_context(
    max_items=8,
    token_budget=500,  # deterministic 4-char/token approximation
)
mem.end_session("success")
```

Closing the session records a bounded working-memory snapshot and its memory
IDs in the episodic memory metadata. The original working items retain their
normal TTL and are not destructively deleted by context-window eviction.

**Vacuum:** `howdex vacuum` cleans up expired working memories.

### Semantic Memory

Semantic memory is explicit, structured, provenance-rich knowledge. Howdex is
not trying to out-Mem0 or Zep at personalised prose extraction. By default,
semantic records come from facts/preferences deliberately written by the agent
or from a narrow deterministic projection of structured tool calls.

```python
mem.remember(
    "User's name is Alice",
    layer="semantic",
    type="fact",
    source="agent",
    confidence=1.0,
    provenance={"run_id": "onboarding-42"},
)
mem.remember(
    "Alice prefers email over Slack",
    layer="semantic",
    type="preference",
)

# Relations build a knowledge graph
mem.remember(
    "Alice works at Acme Corp",
    layer="semantic", type="relation",
    relations=[{"type": "works_at", "target": "acme_corp_id"}]
)
```

Typed tool calls derive only inspectable entities already present in the
canonical target. For example:

```python
session.tool_call(
    "github.create_pr",
    {"repo": "acme/service", "title": "Release v1"},
    outcome="success",
)
```

creates stable semantic records such as `system:github`,
`action:github.create_pr`, `repo:acme/service`, and the relation
`action:github.create_pr -> repo:acme/service`. Free-form titles and
observations are not promoted into facts. Obvious secret fields are redacted,
and repeated calls reuse deterministic semantic IDs. Applications can disable
this per call with `derive_semantics=False`.

Sentence-transformers remains the preferred local embedding backend when the
optional dependency and model are available. The deterministic hashing
embedder remains the dependency-free CI/offline fallback. Custom embedders
continue to implement `Embedder.embed(text)`.

The core also exposes a `SemanticExtractor` protocol for optional application
integrations. LLM-backed implementations must be treated as explicitly
non-deterministic and opt-in; Howdex does not invoke one automatically.

### Episodic Memory

Episodes are structured evidence: what task ran, when it started and ended,
which agent or framework produced it, every raw/canonical step, and the final
outcome or error. This evidence is the substrate that `learn()` turns into
procedures, so the original session is always retained.

Agent episodes are DAGs, not necessarily lists. When two tool calls have
overlapping `started_at`/`ended_at` intervals, Howdex assigns them a shared
`parallel_group_id`. Explicit `parent_step_ids`, span IDs, and caller-provided
parallel groups are preserved. Without timing or DAG metadata, Howdex falls
back to the original linear order.

```python
mem.start_session("onboard new customer")
mem.log_step(
    "create account",
    "success, user_id=42",
    step_id="account",
    started_at=0.0,
    ended_at=1.0,
)
mem.log_step(
    "send welcome email",
    "queued",
    step_id="email",
    started_at=1.0,
    ended_at=3.0,
)
mem.log_step(
    "provision resources",
    "ready",
    step_id="provision",
    started_at=1.2,
    ended_at=4.0,
)
mem.end_session("failure", error="quota exceeded")
```

The email and provisioning calls form one parallel node. Human guidance
renders this without inventing an order:

```text
Step 1: create account
Step 2a (parallel): provision resources
Step 2b (parallel): send welcome email
```

Procedure JSON remains a flat, backwards-compatible `steps` array, but every
step retains its DAG fields. Parallel members share `parallel_group_id` and
`ordering_index`; the following sequential node lists all parallel members in
`parent_step_ids`.

Long sessions are segmented deterministically into child episodes when Howdex
sees:

1. an explicit `task_boundary` on a step;
2. a conservative major target/domain change after at least two established
   steps;
3. an idle timestamp gap longer than 15 minutes; or
4. 50 steps in the current segment.

```python
mem.log_step("patch package.json", "fixed")
mem.log_step(
    "run pytest",
    "passed",
    task_boundary="verify repaired package",
)
```

The raw parent session is never removed. Child episodes have deterministic IDs,
retain raw structured steps and provenance, and reference
`parent_session_id`. Consolidation uses the child episodes when they exist and
does not count the raw parent a second time. Default thresholds can be adjusted
for one close with `end_session(..., max_segment_steps=50, idle_gap_s=900)`.

### Procedural Memory

Learned workflows. **You don't write these — `learn()` writes them for you** by analyzing many episodes of the same task.

Consolidation serializes a parallel group as one deterministic internal node
whose member action names are sorted. LCS and near-match grouping therefore
compare the true DAG shape without depending on whichever parallel tool
finished or was logged first. Learned procedure output then restores the
individual member steps with shared parallel metadata.

```python
procs = mem.learn(min_samples=3)
# [
#   Procedure(
#     task_signature="onboard new customer",
#     steps=[{"action": "create account", ...}, {"action": "send email", ...}],
#     preconditions=["quota_available"],
#     success_rate=0.87,
#     sample_count=15
#   )
# ]

# Use a learned procedure to guide a new attempt:
proc = mem.get_procedure("onboard new customer")
if proc and proc.success_rate > 0.7:
    print(f"Try this sequence: {[s['action'] for s in proc.steps]}")
```

### Using learned procedures before acting

`suggest_procedure()` closes the learning loop by ranking relevant procedures
against the current task and optional working/tool context before an agent
acts. Ranking is deterministic and inspectable: task-signature similarity,
canonical action overlap, target/domain hints, confidence, and success rate.
Procedure recency is not used because Howdex does not currently treat newer
procedures as inherently more applicable.

```python
suggestions = mem.suggest_procedure(
    "publish release",
    context={
        "tool_name": "github.create_pr",
        "tool_args": {"repo": "acme/service", "title": "Release v1"},
    },
    top_k=1,
    min_confidence=0.7,
)

guidance = mem.render_procedure_guidance(suggestions)
print(guidance)
```

Example:

```text
[Howdex procedure guidance]
WARNING: Guidance only. Review preconditions and evidence; do not execute automatically.
Suggestion 1: publish release
Procedure: publish-release | match=0.9360 | confidence=0.9300 | success_rate=1.0000 | support=4
Preconditions: tests_green
Steps:
1. github.create_pr (intent=create; target=repo=acme/service; side_effect_class=external_write)
Proof status: observed_episode_support_not_independently_verified
Source episodes: episode-a, episode-b
```

Suggestions include canonical steps, applicability/preconditions, source
episode IDs, proof status, and a component-level match explanation. The
rendered block is guidance only: Howdex never executes the procedure or treats
historical success as current authorization.

### Learning from procedure use

The feedback loop is explicit and auditable:

```text
learn -> suggest -> mark used -> observe episode outcome -> update stats
```

`suggest_procedure()` is read-only. Surfacing guidance does not count as using
it. Applications can record each state deliberately:

```python
suggestion = mem.suggest_procedure("deploy api", top_k=1)[0]
session = mem.start_session("deploy api")

mem.mark_procedure_suggested(suggestion.procedure_id, session.session_id)
mem.mark_procedure_used(suggestion.procedure_id, session.session_id)

# Run the agent...
mem.end_session("success")
```

Closing a matching session with `success` or `failure` automatically resolves
pending uses. `partial` sessions remain unverified. External evaluators can
instead call:

```python
mem.record_procedure_outcome(
    suggestion.procedure_id,
    episode_id="evaluation-run-42",
    outcome="failure",
)
```

Verified outcomes increment support and success/failure counts, update
`success_rate`, preserve the episode ID, and recompute confidence
deterministically. Confidence keeps 40% of the original extraction confidence,
uses 45% verified success rate, and 15% evidence volume (saturating at five
verified examples). Suggested-only events never change success statistics;
used-but-unresolved events are tracked as `unverified_use_count`.

### Verified procedural memory

Procedures can carry zero or more provider-neutral verification receipts.
Receipts record a verification type (`test`, `build`, `bootproof`, or a custom
type), pass/fail status, command or target, timestamp, digest, optional
signature/source, metadata, and a redacted raw payload. Attaching the same
receipt twice is idempotent.

```python
from howdex import VerificationReceipt

receipt = VerificationReceipt(
    receipt_type="test",
    command="pytest -q",
    status="pass",
    digest="sha256:...",
)
mem.attach_receipt(suggestion.procedure_id, receipt)

print(mem.procedure_verification_status(suggestion.procedure_id))
# verified
```

Receipt-backed status is deliberately conservative:

| Status | Meaning |
|---|---|
| `unverified` | No attached pass/fail receipt |
| `verified` | At least one passing receipt and no failing receipt |
| `failed_verification` | At least one failing receipt and no passing receipt |
| `mixed` | Both passing and failing receipts exist |

Procedure suggestions expose `verification_status`, `procedure_verified`, and
the attached receipt payloads separately from the existing episode-evidence
`proof_status`. Portable procedure exports include receipts without breaking
v1 or receipt-free v2 imports.

BootProof is optional. If a local attestation exists, Howdex can import its
JSON without importing or installing BootProof:

```python
mem.import_bootproof_attestation(
    suggestion.procedure_id,
    ".bootproof/attestation.json",
)
```

Missing files return `None`; malformed attestations are rejected rather than
silently treated as proof. Obvious secrets in metadata, commands, URIs, and
raw payloads are redacted before storage.

---

## 📘 API Reference

### `Howdex(path=None, embedder=None, agent_id=None, embed_dim=384)`

The main class. Zero-config: `Howdex()` creates `~/.howdex/howdex.db`.

| Param | Default | Description |
|---|---|---|
| `path` | `~/.howdex/howdex.db` | SQLite database path |
| `embedder` | auto | `"st"` / `"openai"` / `"hashing"` / `Embedder` instance |
| `agent_id` | `None` | Tags all memories with this agent ID |
| `embed_dim` | `384` | Embedding dimension (must match embedder) |

### `.remember(content, *, layer="semantic", type="fact", metadata={}, importance=0.5, ttl=None, relations=[], source="user", confidence=None, provenance=None)`

Store a memory. Returns the created `Memory` object.

### `.search(query, *, layer=None, top_k=5, min_score=0.1, hybrid=True, agent_id=None, session_id=None)`

Retrieve memories. Returns `list[HowdexResult]` where each result has `.memory`, `.score` (0-1), and `.matched_by` (`"vector"` / `"keyword"` / `"graph"` / `"hybrid"`).

`.recall(...)` accepts the same arguments and remains available as a compatibility alias.

### `.learn(*, min_samples=3, dry_run=False)`

Consolidate episodic memories into procedures. Returns `list[Procedure]`.

### `.get_working_context(session_id=None, *, max_items=20, max_chars=4000, token_budget=None, include_provenance=True)`

Build deterministic prompt-ready working context for one session. If
`session_id` is omitted, the active session is used. `token_budget` uses a
four-characters-per-token approximation and is capped by `max_chars` when both
are provided.

### `.suggest_procedure(task, context=None, top_k=3, min_confidence=0.0)`

Return up to three deterministic `ProcedureSuggestion` objects with canonical
steps, evidence, provenance, and inspectable match components.

### `.render_procedure_guidance(suggestions, *, max_chars=4000)`

Render suggestions into a compact prompt block that explicitly warns against
automatic execution.

### Procedure feedback

- `.mark_procedure_suggested(procedure_id, session_id)`
- `.mark_procedure_used(procedure_id, session_id)`
- `.record_procedure_outcome(procedure_id, episode_id, outcome)`

Feedback events are idempotent by procedure and session/episode reference.
Outcomes must be `"success"` or `"failure"`.

### `.forget(memory_id)`

Soft-delete a memory (tombstoned for CRDT correctness).

### Session methods

- `.start_session(task, agent_id=None, *, source="agent", provenance=None) -> Episode`
- `.log_step(action, observation, **extra)`
- `.end_session(outcome="success", error=None, *, max_segment_steps=50, idle_gap_s=900) -> Episode`

### Sync

- `.sync(peer=None)` — sync with HTTP peer or `.json` file
- `.vacuum()` — GC expired memories + old tombstones
- `.stats()` — return database stats dict

### Procedures

- `.get_procedure(task_signature) -> Procedure | None`
- `.list_procedures() -> list[Procedure]`

---

## 🖥️ CLI Reference

```bash
howdex init                                    # initialize ~/.howdex
howdex remember "content" [--layer L] [--type T] [--importance 0.9] [--ttl 60]
howdex search "query" [--top-k 5] [--min-score 0.1] [-v]
howdex recall "query"                         # compatibility alias
howdex learn [--min-samples 3] [--dry-run]
howdex sync <peer-url-or-json-file>
howdex stats
howdex procedures
howdex procedure export [output-directory]
howdex procedure import <file-or-directory>
howdex codex init [codex-directory]
howdex codex publish [codex-directory]
howdex codex pull <codex-directory>
howdex forget <memory-id>
howdex vacuum
howdex export <output.json>
howdex mcp                                     # start MCP server (stdio)
```

Global flags (before the subcommand):

```bash
howdex --path ./my.db --embedder st --agent-id bot-1 <command>
```

Set defaults via environment variables:

```bash
export HOWDEX_HOME=/data/myagent
export HOWDEX_SYNC_PEER=http://sync.example.com:7331
```

---

## 🔌 Framework Adapters

Howdex works with **any** agent framework. Built-in adapters:

### LangChain

```python
from howdex.adapters import LangChainMemoryAdapter

memory = LangChainMemoryAdapter()
# drop into AgentExecutor(memory=memory)
```

### CrewAI

```python
from howdex.adapters import CrewAIMemoryAdapter

memory = CrewAIMemoryAdapter()
crew._memory = memory
```

### AutoGen

```python
from howdex.adapters import AutoGenMemoryAdapter

adapter = AutoGenMemoryAdapter()
# use adapter.retrieve(query) as your custom retrieve fn
```

### OpenAI Assistants (function calling)

```python
from howdex.adapters import OpenAIAssistantToolsAdapter

adapter = OpenAIAssistantToolsAdapter()
tools = adapter.tool_schemas()
# pass to openai.chat.completions.create(tools=tools)
# dispatch tool calls to adapter.dispatch(name, args)
```

### MCP (Claude Desktop, Cursor, etc.)

```json
// Claude Desktop config
{
  "mcpServers": {
    "howdex": {
      "command": "howdex",
      "args": ["mcp"]
    }
  }
}
```

### Generic / No Framework

```python
from howdex.adapters import GenericAdapter

mem = GenericAdapter()
mem.add("some fact")
results = mem.search("query")
```

---

## 🌐 MCP Server

Howdex ships with a built-in [Model Context Protocol](https://modelcontextprotocol.io) server. Any MCP-compatible client (Claude Desktop, Cursor, Continue, etc.) can use Howdex's memory tools.

**Stdio mode** (for local clients):

```bash
howdex mcp
```

**HTTP mode** (for remote clients + sync):

```bash
python -m howdex.mcp.server --host 0.0.0.0 --port 7331
```

**Exposed tools:**

| Tool | Description |
|---|---|
| `howdex_remember` | Store a memory |
| `howdex_search` | Retrieve relevant memories |
| `howdex_learn` | Trigger consolidation |
| `howdex_forget` | Delete a memory |
| `howdex_stats` | Get database stats |

---

## 🔄 Multi-Agent Sync (CRDT)

Howdex uses **Conflict-free Replicated Data Types** for sync. This means:

- **No merge conflicts.** Ever. Two agents can write to the same memory simultaneously and both will converge.
- **Offline-first.** Agents can work disconnected and sync later.
- **No central server required.** Peer-to-peer sync works. (But you can use Howdex Cloud for convenience.)

**How it works:**

1. Every memory carries a `(vector_clock, node_id)` tuple.
2. Deletes are tombstones, not physical deletes.
3. Conflict resolution is last-writer-wins on `vector_clock`, ties broken by `node_id`. Deterministic.

**File-based sync (sneakernet / air-gapped):**

```python
# Agent A
mem.sync(peer="/usb/sync.json")  # writes pending ops to file

# Agent B (later, elsewhere)
mem.sync(peer="/usb/sync.json")  # reads + applies
```

**HTTP peer sync:**

```python
# Agent A
mem.sync(peer="http://agent-b:7331")

# Or run a dedicated sync node:
howdex --path ./shared.db mcp &
mem.sync(peer="http://sync-host:7331")
```

---

## 🏗️ Architecture

```
howdex/
├── core/
│   ├── engine.py          # The Howdex class — the main entry point
│   ├── types.py           # Memory, MemoryLayer, MemoryType, Episode, Procedure
│   ├── consolidation.py   # The learn() algorithm
│   ├── retrieval.py       # Hybrid search (vector + keyword + graph)
│   └── errors.py
├── storage/
│   └── sqlite_store.py    # Embedded SQLite backend with WAL mode
├── vectors/
│   ├── index.py           # HNSW (preferred) or NumPy fallback
│   └── embedder.py        # Hashing / sentence-transformers / OpenAI
├── sync/
│   └── crdt.py            # CRDT sync (file + HTTP)
├── adapters/              # LangChain, CrewAI, AutoGen, OpenAI, Generic
├── mcp/
│   └── server.py          # MCP server (stdio + HTTP)
└── cli/                   # The `howdex` command
```

### Data Flow

```
remember(content)
    │
    ├─→ embedder.embed(content)  →  vector
    │
    └─→ store.put(memory + vector)
              │
              └─→ index.add(id, vector)  [in-memory]
              └─→ sync_log.append(op)    [for CRDT]

recall(query)
    │
    ├─→ embedder.embed(query)  →  q_vec
    ├─→ index.search(q_vec, k) →  vector hits
    ├─→ keyword_score(query, all_mems) →  keyword hits
    ├─→ graph_neighbors(seeds, hops=1) →  graph hits
    │
    └─→ combine: 0.6*vector + 0.3*keyword + 0.1*graph
        sort by score, return top_k

learn()
    │
    ├─→ query all episodes, group by task_signature
    ├─→ for each group with ≥ min_samples:
    │     ├─ find common action subsequence (LCS-style)
    │     ├─ extract preconditions (in successes, not failures)
    │     ├─ compute success_rate
    │     └─ store as Procedure + procedural Memory
    │
    └─→ return list[Procedure]
```

### Storage

- **SQLite** with WAL mode (crash-safe, concurrent reads).
- Single file: `~/.howdex/howdex.db`. Copy it to back up. Send it to sync.
- Schema is versioned. `migrate()` runs on startup.
- Tombstones for deletes (CRDT correctness).

### Vector Index

- **HNSW** (via `hnswlib`) when available — production-grade ANN, O(log n) search.
- **NumPy brute-force** fallback — slower, but zero dependencies. Great for tests.
- Index is ephemeral, rebuilt from SQLite on startup. (Future: persistent index.)

### Embedders

| Backend | Dim | Quality | Speed | Deps |
|---|---|---|---|---|
| `hashing` | 384 | ★★☆ | ⚡⚡⚡ | none |
| `sentence-transformers` | 384 | ★★★★ | ⚡⚡ | `pip install howdex-ai[st]` |
| `openai` | 1536 | ★★★★★ | ⚡ | `OPENAI_API_KEY` |

Auto-selection: ST if installed, else hashing. Override with `Howdex(embedder="st")`.

---

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HOWDEX_HOME` | `~/.howdex` | Directory for the database |
| `HOWDEX_EMBEDDER` | auto | Embedding backend: `hash`, `hashing`, `st`, or `openai` |
| `HOWDEX_SYNC_PEER` | (none) | Default sync peer URL/path |

### Python

```python
mem = Howdex(
    path="./agent.db",
    embedder="st",              # or "openai", "hashing", or an Embedder instance
    agent_id="my-bot",
)
```

---

## 📂 Examples

| File | What it shows |
|---|---|
| [`examples/quickstart.py`](examples/quickstart.py) | 60-second tour: remember, search, learn |
| [`examples/langchain_agent.py`](examples/langchain_agent.py) | LangChain integration |
| [`examples/multi_agent_sync.py`](examples/multi_agent_sync.py) | Two agents sharing memory via CRDT |
| [`examples/mcp_client.py`](examples/mcp_client.py) | Calling Howdex over MCP |

Run any of them:

```bash
python examples/quickstart.py
```

---

## 📊 Benchmarks

On a MacBook Pro M2, 100K memories, hashing embedder:

| Operation | Time |
|---|---|
| `remember()` | 1.2 ms |
| `recall()` (top-5) | 4.8 ms (NumPy) / 0.3 ms (HNSW) |
| `learn()` (1K episodes) | 220 ms |
| `sync()` (1000 ops, file) | 45 ms |
| `sync()` (1000 ops, HTTP localhost) | 180 ms |

With sentence-transformers (`all-MiniLM-L6-v2`):

| Operation | Time |
|---|---|
| `remember()` | 18 ms (embedding dominates) |
| `recall()` (top-5) | 22 ms (embedding + HNSW) |

Memory footprint: ~50 MB for 100K memories + embeddings.

---

## ⚖️ Comparison

> **Mem0 remembers context. Howdex indexes know-how.**

Context memory helps an agent remember facts, preferences, and prior
conversations. Howdex focuses on portable agent know-how: what the agent tried,
what failed, what worked, and which successful procedure should guide the next
run. The categories are complementary; the distinction is operational memory
versus reusable execution knowledge.

| Feature | Howdex | LangChain Memory | MemGPT/Letta | Zep | Chroma |
|---|---|---|---|---|---|
| **4-layer cognitive model** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Procedural learning** (`learn()`) | ✅ | ❌ | partial | ❌ | ❌ |
| **Local-first / offline** | ✅ | ✅ | ✅ | ❌ | ✅ |
| **CRDT multi-agent sync** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **MCP server** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Framework-agnostic** | ✅ | LangChain only | own framework | API only | ✅ |
| **Zero-config** | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Knowledge graph** | ✅ | ❌ | ❌ | partial | ❌ |
| **Own your data** | ✅ | ✅ | ✅ | ❌ | ✅ |
| **Open source** | ✅ Apache 2.0 | ✅ MIT | ✅ Apache | ❌ | ✅ Apache |

---

## 🗺️ Roadmap

### v0.3 (current)
- ✅ Four-layer memory (working, semantic, episodic, procedural)
- ✅ SQLite storage with WAL
- ✅ Hybrid retrieval (vector + keyword + graph)
- ✅ HNSW + NumPy vector backends
- ✅ Hashing / sentence-transformers / OpenAI embedders
- ✅ CRDT sync (file + HTTP)
- ✅ MCP server (stdio + HTTP)
- ✅ CLI
- ✅ LangChain, CrewAI, AutoGen, OpenAI adapters
- ✅ Deterministic action canonicalisation
- ✅ Near-match procedural clustering
- ✅ Inspectable confidence and supporting evidence
- ✅ Conservative procedural retrieval
- ✅ Semantic conflict review flags
- ✅ Portable procedure JSON and local Codex registry
- ✅ 83 passing tests

### Next
- ⬜ Persistent HNSW index (no rebuild on startup)
- ⬜ Cross-framework trace conformance benchmark
- ⬜ Signed procedure bundles and review policy
- ⬜ TypeScript SDK

### v1.0
- ⬜ Distributed mode (multi-node Howdex cluster)
- ⬜ Federated learning (agents share procedures without sharing data)
- ⬜ Official Docker image + Helm chart

---

## 🤝 Contributing

We love contributors. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

**Quick start:**

```bash
git clone https://github.com/rossbuckley1990-hash/Howdex
cd howdex
pip install -e ".[dev]"
pytest

# Run an example
python examples/quickstart.py
```

**Good first issues:** look for `good first issue` and `help wanted` labels on GitHub.

---

## ❓ FAQ

**Q: Is this production-ready?**

A: v0.3 is beta-quality. The core API is stable, procedure extraction is
deterministic and evidence-backed, and SQLite remains the durable local store.
For mission-critical use, review learned procedures before executing them and
run with HNSW plus sentence-transformers where retrieval quality matters.

**Q: How is this different from a vector database?**

A: A vector DB gives you similarity search. That's one of three retrieval strategies Howdex uses (vector + keyword + graph). Howdex also has four distinct memory layers, episodic logging, procedural learning via `learn()`, CRDT sync, and an MCP server. A vector DB is a component; Howdex is a system.

**Q: How is this different from LangChain's memory?**

A: LangChain's `ConversationBufferMemory` is a FIFO buffer. It's "chat history," not memory. It doesn't learn, it doesn't consolidate, it doesn't sync across agents, and it loses old context. Howdex is a cognitive memory system.

**Q: Do I need to run a server?**

A: No. Howdex is embedded. `import howdex; howdex.Howdex()` and you're done. The MCP server is optional (for use with Claude Desktop etc.).

**Q: Where is my data stored?**

A: In a single SQLite file at `~/.howdex/howdex.db` by default. You own it. Back it up by copying. Delete it to forget everything.

**Q: Can I use this with my existing agent?**

A: Yes. We have adapters for LangChain, CrewAI, AutoGen, and OpenAI Assistants. If your framework isn't listed, the `GenericAdapter` works anywhere, or wrap `Howdex` directly — it's just a Python class.

**Q: How does sync work across multiple agents?**

A: CRDTs. Each memory has a `(vector_clock, node_id)` pair. Sync is just exchanging op logs. Conflicts resolve deterministically (last-writer-wins on vector_clock, ties by node_id). No central server needed.

**Q: Can I use a different embedding model?**

A: Yes. Subclass `Embedder` and implement `embed(text) -> list[float]`. Pass it to `Howdex(embedder=YourEmbedder())`.

**Q: Is there a cloud version?**

A: Coming in v0.2. "Howdex Cloud" will be managed sync + backup + a web dashboard. $0.10/GB/month. The local-first core stays free and open source forever.

**Q: Why "Howdex"?**

A: It is an index of know-how: the reusable procedures agents build from
successful runs. `from howdex import Howdex; memory.search(query)` reads clearly,
while `memory.recall(query)` remains available for compatibility.

---

## 📄 License

Apache License 2.0. Use it commercially, fork it, embed it, ship it. Just don't sue us.

---

<div align="center">

**Built with the conviction that AI agents deserve better memory.**

If Howdex saves you time, ⭐ the repo. It helps others find it.

[⭐ Star on GitHub](https://github.com/rossbuckley1990-hash/Howdex) · [🐛 Report a bug](https://github.com/rossbuckley1990-hash/Howdex/issues) · [💬 Join the discussion](https://github.com/rossbuckley1990-hash/Howdex/discussions)

</div>

---

## Benchmark proof

Howdex is not just chat history or vector search. It learns reusable procedures from repeated agent/tool-use episodes.

Current SWE-repeat benchmark result:

> Howdex reduced repeated unsafe test failures by **50%** versus no-memory and vector-only baselines on eligible real OSS npm test suites after controlled source-code fault injection.

The benchmark uses:

- real cloned OSS repositories
- real `npm install`
- real clean `npm test`
- controlled source-code fault injection
- real failing `npm test`
- real repair
- real rerun of `npm test`
- no-memory, vector-only, and Howdex procedural-memory baselines

Run it locally:

    HOWDEX_EMBEDDER=hash howdex eval swe-repeat

Read the benchmark report:

    cat BENCHMARKS.md

The core thesis:

> Same agent. Same repos. Same tests. Same fault family. Howdex helped it stop failing the same way twice.
