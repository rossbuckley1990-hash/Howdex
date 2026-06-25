Howdex — verified procedural memory for AI agents

🧵 Thread:

1/ I built an open-source system that records what AI agents do, learns reusable procedures from successful runs, and verifies them with deterministic, non-LLM checkers before they can be reused.

The key insight: an LLM saying "I fixed it" is not proof.

2/ Howdex does 4 things:

• Procedural memory — records traces, consolidates into reusable procedures, renders guidance
• BootProof gate — blocks learning unless a deterministic verifier (pytest, curl, etc.) confirms success
• Compliance reports — SOC 2, EU AI Act, NIST AI RMF
• Public registry — verified procedures shared across teams

3/ The BootProof gate is the moat.

If your LLM hallucinates a fix and says "DONE", and you blindly tell the memory system "success", it will permanently memorize a hallucination.

BootProof blocks this: learn() refuses to consolidate without a real exit code / HTTP 200 / test pass.

4/ The receipt primitive: a deterministic, content-hashed, optionally HMAC-signed proof that a verifier ran and passed.

LLM judgments are explicitly NOT accepted as verification evidence.

This is the "SSL certificate" of agent governance.

5/ Compliance reports map receipts directly to control objectives:

• SOC 2: CC7.1 (monitoring), CC8.1 (change mgmt), A1.1 (availability)
• EU AI Act: Art 9 (risk), Art 12 (logging), Art 15 (accuracy)
• NIST AI RMF: GOVERN-1, MEASURE-1, MANAGE-1

Each report has a deterministic SHA-256 hash for audit reproducibility.

6/ The public registry is live: https://github.com/rossbuckley1990-hash/howdex-public-registry

Agents consult it first, get matching verified procedures merged into their guidance, and contribute back.

The network effect is built on verification, not vibes.

7/ Try it in 60 seconds:

pip install git+https://github.com/rossbuckley1990-hash/Howdex.git
python examples/first_time_dev.py

This walks through the full loop: record → learn → verify → publish → lint.

701 tests. Zero required deps (SQLite + numpy). MCP server for Claude Desktop.

8/ Stack:
• Python 3.9+, local-first (no cloud required)
• MCP server (10 tools) for Claude Desktop / Cursor / Windsurf
• Adapters for LangChain, CrewAI, AutoGen, OpenAI Agents
• @instrument decorator + session_scope for zero-boilerplate integration

9/ I'm looking for:
• Enterprise design partners (compliance teams deploying agents)
• Contributors (good first issues tagged on GitHub)
• Feedback on the receipt spec (docs/RECEIPT_SPEC.md)

Repo: https://github.com/rossbuckley1990-hash/Howdex

10/ The positioning: not "memory for agents" (that gets absorbed by LangGraph/OpenAI/Anthropic). 

The wedge: "the audit and verification layer for AI agents" — a separate buying center (CISO/compliance) with a budget that doesn't get cut in downturns.

Compliance spend > tooling spend. That's the path.
