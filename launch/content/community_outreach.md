# Community Outreach Templates

## Discord/Slack — Agent Framework Communities

### LangChain Discord (#tools or #memory channel)

```
Hey — I just open-sourced Howdex, a verified procedural memory system that works with LangChain. The key differentiator vs. LangGraph's checkpointer: it actually LEARNS from past runs (consolidates traces into reusable procedures) and requires a deterministic verifier (pytest exit code, HTTP 200) before consolidating — so hallucinated successes can't become permanent memory.

Zero-boilerplate LangChain integration:
```python
from howdex import Howdex, auto_instrument_langchain
mem = Howdex(path="agent.db", embedder="hashing")
auto_instrument_langchain(mem, [tool1, tool2, tool3])
```

Also has compliance report generation (SOC 2, EU AI Act, NIST AI RMF) and a public procedure registry. 701 tests, MCP server for Claude Desktop.

Repo: https://github.com/rossbuckley1990-hash/Howdex
Would love feedback from anyone building production LangChain agents.
```

### CrewAI Discord

```
Just open-sourced Howdex — verified procedural memory for AI agents. Has a CrewAI adapter (`howdex/adapters/crewai.py`). The unique feature: a BootProof gate that blocks learning unless a real verifier (not an LLM) confirms success. Also generates SOC 2 / EU AI Act compliance reports from agent receipts.

Repo: https://github.com/rossbuckley1990-hash/Howdex
Looking for CrewAI users to try the adapter and give feedback.
```

### AutoGen Discord

```
Open-sourced Howdex — procedural memory + verification for AI agents. Has an AutoGen adapter. The core insight: an LLM saying "I fixed it" is not proof. Howdex requires a deterministic verifier (exit code, HTTP status, test pass) before consolidating a procedure. Also has compliance reports (SOC 2, EU AI Act, NIST AI RMF) and a public registry of verified procedures.

Repo: https://github.com/rossbuckley1990-hash/Howdex
Good first issues tagged if anyone wants to contribute.
```

### MCP Community (Discord/Slack)

```
Built an MCP server for verified procedural memory: Howdex. 10 tools (remember_trace, learn, guidance, codex_search, codex_publish, attach_receipt, etc.) that let any MCP-compatible agent (Claude Desktop, Cursor, Windsurf) record traces, learn verified procedures, and get guidance.

The differentiator: a BootProof gate that requires a deterministic, non-LLM verifier before a procedure can be consolidated. Plus compliance report generation (SOC 2, EU AI Act, NIST AI RMF).

Try it:
```
howdex mcp --db ~/.howdex/howdex.db --codex ./codex
```

Repo: https://github.com/rossbuckley1990-hash/Howdex
Config examples: https://github.com/rossbuckley1990-hash/Howdex/tree/main/examples/pilot
```

### r/LocalLLaMA Discord / AI Engineer communities

```
Open-sourced Howdex — the verification layer for AI agents. If you're running local LLMs with agents (Ollama + LangChain, etc.), Howdex gives you:
- Procedural memory (record → learn → guidance)
- BootProof gate (blocks hallucinated successes)
- Compliance reports (SOC 2, EU AI Act, NIST AI RMF)
- Public registry of verified procedures
- Local-first (SQLite + numpy, no cloud, no API keys needed)

Repo: https://github.com/rossbuckley1990-hash/Howdex
Works with any agent framework via MCP or Python adapters.
```

## Direct Outreach — AI Governance/Compliance

### To AI governance tooling companies (Holistic AI, Credo AI, etc.)

**Subject:** Open-source receipt primitive for AI agent verification — potential integration?

```
Hi [name],

I've open-sourced Howdex — a verification layer for AI agents that generates compliance-ready evidence (SOC 2, EU AI Act, NIST AI RMF) from deterministic verification receipts.

The core primitive: a Howdex Verification Receipt is a content-hashed, optionally HMAC-signed proof that a non-LLM verifier (exit code, HTTP status, test runner) confirmed an agent's procedure. LLM judgments are explicitly NOT accepted as verification evidence.

I think there's a natural integration with [their platform] — your policy/risk layer + Howdex's receipt evidence = end-to-end AI governance. The receipt spec is published as a standalone standard: https://github.com/rossbuckley1990-hash/Howdex/blob/main/docs/RECEIPT_SPEC.md

Would you be open to a conversation?

Repo: https://github.com/rossbuckley1990-hash/Howdex
```

### To AI engineering teams at enterprises (fintech, healthcare, infra)

**Subject:** Open-source tool for proving AI agent work was verified (SOC 2 / EU AI Act ready)

```
Hi [name],

I noticed [company] is deploying AI agents in [context]. I've open-sourced a tool called Howdex that might be relevant: it's a verification layer that records what agents do and requires a deterministic, non-LLM verifier (pytest, curl, build script) to confirm success before the procedure is memorized.

It also generates compliance reports mapping verification receipts to SOC 2, EU AI Act, and NIST AI RMF controls — with deterministic hashes for audit reproducibility.

The problem it solves: when an agent says "I fixed it" but the fix is wrong, most memory systems will permanently memorize the hallucination. Howdex's BootProof gate blocks this.

It's local-first (SQLite + numpy, no cloud required), has an MCP server for Claude Desktop/Cursor, and adapters for LangChain/CrewAI/AutoGen.

I'm looking for design partners who are hitting the compliance wall with agent deployments. Would [company] be interested in trying it?

Repo: https://github.com/rossbuckley1990-hash/Howdex
```
