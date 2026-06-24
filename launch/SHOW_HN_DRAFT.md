# Show HN draft

Title idea:

Show HN: Howdex — portable, receipt-backed procedures for AI agents

Draft:

Hi HN,

I am building Howdex, an open verification layer for agent know-how.

The idea is simple: agents should not start every run cold. Howdex records
execution traces, learns reusable procedures from what worked and what failed,
and renders those procedures back as operational guidance. A procedure can carry
verification receipts, policy context, staleness metadata, and provenance.

It is not a prompt library and it is not executable authority. The goal is
portable agent know-how: guidance that can move across models, frameworks, and
clouds while staying inspectable and local-first.

Current pieces include:

- local SQLite storage;
- deterministic trace-to-procedure extraction;
- source artifacts excluded by default;
- verification receipts for procedures;
- a local MCP server;
- optional adapters for LangGraph, LangChain, OpenAI Agents, CrewAI, AutoGen,
  and plain Python loops;
- a local Codex format for portable procedure entries.

The README includes an internal Docker recovery A/B benchmark with n=20 per arm:
control success rate 0.35, treatment success rate 0.90, memory used 20/20, and
source pasted 0/20. The caveat is important: this demonstrates one internal
verified procedure transferring to fresh agents. It does not prove broad
compounding or production-safe autonomy.

I am looking for pilot users who have agents doing real work and want to own the
learning loop instead of leaving it trapped in transcripts or one model stack.

Useful feedback would be:

- where the procedure format is too weak;
- which agent/runtime integrations matter most;
- what receipts or policy metadata would make this auditable in practice;
- whether the local-first design fits your security constraints.

Repo: <add repository link when posting>

Thanks for taking a look.
