Show HN: Howdex — verified procedural memory for AI agents (with compliance reports)

I built an open-source system that records what AI agents do, learns reusable procedures from successful runs, and verifies them with deterministic, non-LLM checkers before they can be reused. The key insight: an LLM saying "I fixed it" is not proof — you need an objective verifier (exit code, HTTP status, test suite pass).

Howdex does four things:

1. **Procedural memory** — records agent execution traces (tool calls, arguments, observations), consolidates repeated successful traces into parameterized procedures, and renders guidance for future agents. Like a CI/CD pipeline for agent know-how.

2. **BootProof verifier gate** — blocks `learn()` from consolidating a session unless a deterministic, non-LLM verifier (pytest exit code, curl HTTP 200, etc.) confirmed the result. An LLM "I think it worked" is explicitly rejected. This prevents hallucinated successes from becoming permanent procedures.

3. **Compliance reports** — generates audit-ready Markdown reports mapping verification receipts to SOC 2 (CC7.1, CC7.2, CC8.1, A1.1), EU AI Act (Articles 9, 12, 15), and NIST AI RMF (GOVERN-1, MEASURE-1, MANAGE-1). Each report has a deterministic SHA-256 hash for audit reproducibility.

4. **Public procedure registry** — a Git-based registry of verified procedures. Agents consult it first (`howdex public-registry pull`), get matching procedures merged into their guidance, and contribute back (`howdex public-registry push`). The network effect is built on verification, not vibes.

Why I built this: every agent-memory system I looked at (mem0, Letta, Zep) records what was said or what facts were learned. None of them record how work was done, and none of them verify that the work actually succeeded. In a production setting, an agent that hallucinates a fix and says "DONE" will crystallize that hallucination into permanent memory. BootProof blocks this.

The receipt primitive is the core: a deterministic, content-hashed, optionally HMAC-signed proof that a verifier ran and passed. It's designed to be the "SSL certificate" of agent governance — a standardized artifact that auditors can verify.

Tech: Python 3.9+, SQLite + numpy (zero required deps), 701 tests, MCP server for Claude Desktop/Cursor, adapters for LangChain/CrewAI/AutoGen/OpenAI Agents, local-first (no cloud required).

Try it:

    pip install git+https://github.com/rossbuckley1990-hash/Howdex.git
    python examples/first_time_dev.py

The first_time_dev.py script walks through the full loop in 60 seconds: record a trace → learn a procedure → attach a real receipt → pull guidance for a fresh task → publish to a local Codex → lint it.

The public registry is live at https://github.com/rossbuckley1990-hash/howdex-public-registry with 4 verified procedures (Docker recovery, Node missing dep, ZB2 decoder, OpenSSL).

I'm looking for: enterprise design partners (compliance teams deploying agents), contributors (good first issues tagged), and feedback on the receipt spec (docs/RECEIPT_SPEC.md).
