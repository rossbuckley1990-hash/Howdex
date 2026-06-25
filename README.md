<div align="center">

# Howdex

### Own your AI learning loop.

**Howdex is the open verification layer for agent know-how.** It turns the expensive, hard-won experience of your best AI agents into **verified agent procedures** that any agent can reuse, any team can audit, and any model — frontier or open — can execute.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)]() [![MCP](https://img.shields.io/badge/MCP-ready-7c3aed.svg)]()

*One expensive discovery. Infinite cheap executions.*

</div>

---

> **Howdex turns execution traces into portable, receipt-backed procedures that agents can reuse and enterprises can audit.**

Today your agents are amnesiacs. An agent solves a gnarly problem — recovers a broken service, completes a refund-and-rebooking flow, untangles a build — and the moment the session ends, that competence evaporates. Tomorrow it starts from zero: re-reading the same files, repeating the same dead-ends, burning the same tokens. You are paying frontier prices, over and over, to re-learn things you already knew.

Howdex fixes that. It watches your agents succeed, distills the *repeatable procedure* behind the success, proves it works with attached receipts, and hands it back as clean operational guidance the next agent can follow — deterministically, locally, and portably across every model and framework you use.

## The result, measured

We don't ask you to take this on faith. On a **real Docker Compose recovery task** — a fresh agent must read five files, infer a cross-file configuration dependency, and repair the right one to bring a service healthy:

| Arm | Success rate | Avg attempts |
| --- | --- | --- |
| Fresh agent, no memory | **35%** (7/20) | 13.00 |
| Same agent + Howdex | **90%** (18/20) | 8.75 |

- **n = 20 per arm**, byte-identical task framing across both arms (verified by prompt hash).
- **`source_pasted: 0/20`** — the agent *reconstructed* the fix from learned operational facts. It was never handed the answer. This is real transfer of know-how, not a leaked solution.
- Reproduce it yourself: `make bench-docker-n20`

A 55-point jump in success and a 33% drop in attempts, from memory alone — on a model that had never seen the task.

## Quickstart — five minutes to a smarter agent

```bash
pip install howdex-ai
# or, straight from source:
pip install git+https://github.com/rossbuckley1990-hash/Howdex.git
```

```python
from howdex import Howdex

mem = Howdex()  # local SQLite at ~/.howdex — nothing leaves your machine

# 1. Capture a successful run (wrap the tool calls your agent already makes)
mem.start_session("recover broken compose service")
mem.log_tool_call("read_file",  {"path": "compose.yml"},   observation="ok")
mem.log_tool_call("edit_file",  {"path": "runtime.env"},   observation="set HEALTH_MODE=ready")
mem.log_tool_call("run",        {"cmd": "docker compose up -d --build"}, observation="healthy")
mem.end_session("success")

# 2. Distill the reusable procedure
mem.learn()

# 3. On a new, related task, get clean, inspectable guidance
print(mem.guidance("service /health returns 503 after deploy"))
```

**Plug it into any agent via MCP — no code at all:**

```bash
howdex mcp --db ~/.howdex/howdex.db --codex ./codex
```

Point Claude Desktop, Cursor, Windsurf, or any MCP client at it, and your agent gains `remember`, `learn`, and `guidance` as first-class tools.

---

## Why Howdex is different

Most "agent memory" stores **facts** (who the user is, what they like) by asking an LLM to summarize conversations — opaque, non-deterministic, and locked to one cloud. Howdex stores **how the work was actually done** — and proves it.

| | Conversational / factual memory (Mem0, Zep, Letta) | **Howdex** |
| --- | --- | --- |
| What it stores | facts, preferences, chat history | **reusable procedures — how to do the work** |
| How it's built | LLM summarization | **deterministic — no LLM in the loop** |
| Inspectable & auditable | rarely | **yes — full provenance + receipts** |
| Runs locally, no model required | varies | **yes — numpy-only core** |
| Verifies before trusting | no | **yes — the Codex** |
| Portable across models & clouds | varies | **yes — you own the loop** |

Howdex isn't a competitor to factual memory — it's the **procedural layer** that sits alongside it and does the thing none of them do: make competence *repeatable, portable, and provable*.

---

## What Howdex gives you

### For developers
Drop-in capture around the tool calls you already make. A **5-minute** local setup, an MCP server, and one dependency (`numpy`). No cloud account, no vector database to operate, no API key to babysit. Your agent gets faster and cheaper on every task family you touch — and you can read exactly what it learned, because nothing is a black box.

### For agent frameworks
One integration, every stack. Howdex ships adapters for **LangChain, LangGraph, CrewAI, AutoGen, and the OpenAI Agents SDK**, plus a generic decorator for anything else and a full MCP server. Add procedural memory to your framework of choice without rewriting your agent.

### For teams & enterprises
Howdex is **local-first, vendor-neutral, and audit-friendly by design.** Procedures stay inside your perimeter. Every verified procedure carries provenance, a verifier, and a receipt — so when an agent recalls "how we do X," you can prove where that came from and that it actually worked. Built-in governance (`codex lint`, `policy-check`, signed attestations) gives the verification layer real teeth. Your operational know-how becomes a durable, owned asset — portable across models, frameworks, and clouds — instead of something you rent from a single provider and lose when you switch.

### For multi-agent systems — a shared, verified commons
The **Howdex Codex** is an open, schema'd catalogue of operational procedures with CRDT-based sync. One agent learns a procedure; every other agent can pull it — *with its receipts attached*, so a consuming agent knows whether to trust it. A fleet of agents stops rediscovering the same workflows in parallel and starts compounding a shared library of proven know-how. Specialist agents publish what they're best at; generalist agents reuse it. The commons is inspectable, governed, and owned by you — not a hosted black box.

---

## The teacher → student economics

This is where it gets unfair, in your favor.

Frontier models are brilliant and expensive — and worse, what they learn evaporates and stays theirs. Howdex changes the unit economics of running agents:

1. **Learn with the best.** Run a frontier model (the *teacher*) on a hard task. When it succeeds, Howdex captures the trace and distills a **deterministic, verified procedure** — with receipts proving it worked.
2. **Publish to the registry.** That procedure goes into the Codex: portable, inspectable, model-agnostic guidance. No weights, no prompts to leak — just the operational know-how.
3. **Execute with the cheapest.** A smaller, cheaper, open model (the *student*) pulls the verified procedure from the registry and follows it — inheriting the teacher's hard-won competence on that task at a fraction of the inference cost, with *no LLM in the memory loop at all*.

**Pay frontier prices once to learn. Reuse forever on models that cost a fraction.** Because the procedure is deterministic guidance rather than model-specific weights, it travels across model families, frameworks, and clouds — and because it's receipt-backed, the student knows which procedures are safe to rely on. Cross-model portability is a core design goal of Howdex; large-scale independent transfer benchmarks across models are in progress.

---

## The Codex — verified agent procedures, owned by you

The Codex enforces one rule: **no proof, no procedure.** A learned procedure is `candidate` until **inspectable receipts** show a task-relevant verifier passed — only then is it `verified`. Every entry carries provenance, failed-attempt memory (what to avoid), policy and staleness metadata, and source-exclusion controls.

```bash
howdex codex lint ./codex          # structural + receipt integrity
howdex codex policy-check ./codex  # policy & risk gates
howdex codex verify ./codex        # re-check verifier evidence
```

The Codex is not a prompt library and not an execution engine. **In Howdex, procedures are guidance, not executable authority** — a consuming agent verifies in its current environment before it acts. That boundary is exactly what makes Howdex safe to put in front of high-stakes work.

---

## How it works

```
successful traces ─▶ learn ─▶ canonical procedure (+ provenance, receipts)
                                        │
                            retrieve by task similarity
                                        │
                                    guidance ─▶ next agent succeeds faster, cheaper
```

Deterministic canonicalization turns differently-worded traces into one procedure. Retrieval is budgeted and inspectable. Guidance is operational facts — never pasted source — so reuse proves competence, not copying. **Auditable abstraction: optional LLM proposals, deterministic trust.** Optional, fully auditable LLM-assisted abstraction can propose semantic equivalences, but storage, verification, and trust status always stay deterministic and reversible.

## What Howdex does *not* claim

Credibility is the product, so here is the honest boundary:

- Howdex does not, by itself, make autonomous execution production-safe; it supplies guidance and verification metadata, and the consuming agent remains responsible for verifying before it acts.
- The Docker benchmark above proves **single-procedure transfer to fresh agents**, not compounding across many independent traces or teams at scale.
- Cross-model portability is a design property; we do not claim independently proven live transfer across models.
- Our AWM-style comparison harness currently runs in dry-run mode; we do not claim that dry-run AWM-style harness results are live performance, and we make no claim of beating AWM, WebArena, or Mind2Web. We do not claim that Howdex has beaten the AWM paper.
- `candidate` Codex entries and unaccepted abstraction proposals are not verified.

## Dogfooding Howdex

Howdex is increasingly built through its own procedural-memory loop: as we develop it, Howdex captures the build traces, learns procedures, and attaches receipts from passing test runs. These dogfood metrics are **internal evidence only** — they are **not external users, adoption, traction, market validation**. They show only that the loop runs on a real workload (our own). The reproducible benchmark above, not these internal metrics, is the external evidence.

---

## Install & docs

```bash
pip install howdex-ai           # or: pip install git+https://github.com/rossbuckley1990-hash/Howdex.git
```

Deep dives live in [`docs/`](docs/): architecture, the Codex standard and protocol, MCP, framework adapters, governance, observability, and the [benchmark methodology](docs/benchmarks.md).

## License

Apache-2.0. Own your loop.
