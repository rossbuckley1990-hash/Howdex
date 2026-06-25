# Reddit — r/LocalLLaMA

**Title:** I built an open-source memory system for AI agents that verifies fixes before learning from them (BootProof gate + compliance reports)

**Body:**

Most agent memory systems (mem0, Letta, Zep) record what was said or what facts were learned. None of them verify that the work actually succeeded before crystallizing it into permanent memory.

If your LLM hallucinates a fix and says "DONE", and you blindly tell the memory system "success", it will permanently memorize a hallucination. Future agents will follow the hallucinated procedure and fail the same way.

**Howdex** fixes this with a **BootProof verifier gate**: `learn()` refuses to consolidate a session unless a deterministic, non-LLM verifier (pytest exit code, curl HTTP 200, etc.) confirmed the result. An LLM "I think it worked" is explicitly rejected.

It also generates **compliance reports** mapping verification receipts to SOC 2, EU AI Act, and NIST AI RMF controls — audit-ready Markdown with deterministic hashes for reproducibility.

And there's a **public procedure registry** — agents consult it first, get matching verified procedures, and contribute back. Like npm for agent procedures, but built on verification not vibes.

**Stack:** Python 3.9+, SQLite + numpy (zero required deps), 701 tests, MCP server for Claude Desktop/Cursor, local-first.

**Try it:**
```
pip install git+https://github.com/rossbuckley1990-hash/Howdex.git
python examples/first_time_dev.py
```

The first_time_dev.py walks through the full loop in 60 seconds.

Repo: https://github.com/rossbuckley1990-hash/Howdex
Public registry: https://github.com/rossbuckley1990-hash/howdex-public-registry

Looking for feedback on the receipt spec (docs/RECEIPT_SPEC.md) and enterprise design partners.

---

# Reddit — r/LangChain

**Title:** Howdex — procedural memory + verification for LangChain agents (BootProof gate, compliance reports, public registry)

**Body:**

If you're building LangChain agents that do real work (fix bugs, run infra, deploy code), you've probably hit two problems:

1. **Your agent forgets everything between runs.** LangGraph's checkpointer persists session state, but it doesn't learn from past successes. Every run starts cold.

2. **You can't prove your agent's work was verified.** If an LLM says "I fixed it" but the fix is wrong, there's no guardrail preventing the hallucination from becoming permanent memory.

**Howdex** solves both:

- **Procedural memory**: records agent tool calls, consolidates successful traces into reusable procedures, renders guidance for future runs
- **BootProof gate**: blocks learning unless a deterministic verifier (pytest, curl, build script) confirms success
- **Zero-boilerplate integration**: `@instrument(mem)` decorator + `session_scope` context manager auto-log every tool call. Or use `auto_instrument_langchain(mem, [tools])` for one-line integration.
- **Compliance reports**: SOC 2, EU AI Act, NIST AI RMF — audit-ready with deterministic hashes
- **Public registry**: agents consult verified procedures from other teams first

```python
from howdex import Howdex, instrument, session_scope

mem = Howdex(path="...", embedder="hashing")

@instrument(mem)
def search_code(query: str) -> str:
    ...

with session_scope(mem, "fix_bug"):
    result = search_code("def load_config")
    # ... do work ...
# session auto-ended: success on clean exit, failure on exception
```

Repo: https://github.com/rossbuckley1990-hash/Howdex
Good first issues tagged if you want to contribute.

---

# Reddit — r/MachineLearning

**Title:** [D] Howdex — verified procedural memory for AI agents with compliance report generation (SOC 2, EU AI Act, NIST AI RMF)

**Body:**

I've been working on an open-source system that addresses a gap in the agent infrastructure stack: **verified procedural memory**.

The core insight: an LLM's claim of success is an observation, not a verification. Howdex introduces a **receipt primitive** — a deterministic, content-hashed, optionally HMAC-signed proof that a non-LLM verifier (exit code, HTTP status, test runner) confirmed an agent's procedure. LLM judgments are explicitly NOT accepted as verification evidence.

Key components:

1. **BootProof gate** — `learn()` refuses to consolidate sessions without a verified receipt. Prevents hallucinated successes from becoming permanent procedures.

2. **Compliance report generator** — maps receipts to SOC 2 (CC7.1, CC7.2, CC8.1, A1.1), EU AI Act (Articles 9, 12, 15), NIST AI RMF (GOVERN-1, MEASURE-1, MANAGE-1). Deterministic SHA-256 report hash for audit reproducibility.

3. **Public procedure registry** — Git-based registry of verified procedures. The network effect is built on verification, not vibes: only `status=verified` procedures are accepted.

4. **Standalone Receipt Spec** (docs/RECEIPT_SPEC.md) — a framework-agnostic, citable standard for agent verification evidence. Designed to be referenced in AI governance policies.

The system is local-first (SQLite + numpy, zero required deps), has 701 tests, an MCP server for Claude Desktop/Cursor, and adapters for LangChain/CrewAI/AutoGen/OpenAI Agents.

I'd appreciate feedback on:
- The receipt spec — is this the right abstraction for agent auditability?
- The compliance mappings — are the control objectives correct?
- The registry model — does "verification as the network effect" make sense?

Repo: https://github.com/rossbuckley1990-hash/Howdex
Receipt spec: https://github.com/rossbuckley1990-hash/Howdex/blob/main/docs/RECEIPT_SPEC.md
