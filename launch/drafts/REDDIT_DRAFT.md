# Reddit draft

Before posting: read the target subreddit rules manually. Only post in
communities that allow project discussion, and adapt this draft to the local
norms. Do not spam multiple communities with identical copy.

Title idea:

Technical feedback wanted: local-first procedural memory for AI agents

Draft:

I am working on Howdex, an open-source project for procedural memory in AI
agents.

The problem I am trying to solve is that agents often rediscover the same
operational procedure repeatedly. Howdex records execution traces, turns
successful and failed attempts into reusable procedure guidance, and can attach
verification receipts so the memory is inspectable.

The positioning is deliberately narrow:

- not chat memory;
- not a prompt library;
- not a cloud service;
- not production-safe autonomous execution;
- not a claim that broad compounding is already proven.

The intended primitive is a portable, receipt-backed procedure:

- learned from execution traces;
- rendered as operational guidance;
- backed by verification evidence when available;
- source artifacts excluded by default;
- portable through local Codex JSON and MCP.

The repo includes a local MCP server and optional adapters for LangGraph,
LangChain, OpenAI Agents, CrewAI, AutoGen, and framework-neutral Python loops.

The README cites one internal Docker recovery A/B benchmark with n=20 per arm:
control success rate 0.35, treatment success rate 0.90, and source pasted 0/20.
That is an internal benchmark for one task family, not broad proof.

I am looking for technical feedback from people building agents that actually
use tools:

- Does this procedure/receipt model map to your agent traces?
- What metadata would make a procedure trustworthy enough to reuse?
- Would MCP be the right integration path for your workflow?
- What would make this safer or more auditable?

Repo: <add repository link when posting>

Please tell me if this is too early, too narrow, or missing an obvious prior
art. I am trying to keep the claims honest.
