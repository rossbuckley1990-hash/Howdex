# Awesome Agent Memory [![Awesome](https://awesome.re/badge.svg)](https://awesome.re)

> A curated, **vendor-neutral** list of research, systems, benchmarks, and standards for giving AI agents memory — so they stop redoing solved work and start improving from experience.

This list aims to be the honest reference for the whole field: factual one-line descriptions, fair coverage, no marketing. If a project's description here is wrong or out of date, open a PR.

## Contents
- [What "agent memory" means](#what-agent-memory-means)
- [Surveys & background](#surveys--background)
- [Foundations (pre-LLM roots)](#foundations-pre-llm-roots)
- [Experiential / trajectory learning](#experiential--trajectory-learning)
- [Procedural / workflow-memory induction](#procedural--workflow-memory-induction)
- [Open-source & commercial memory systems](#open-source--commercial-memory-systems)
- [Deterministic / verifiable / local-first procedural memory](#deterministic--verifiable--local-first-procedural-memory)
- [Benchmarks](#benchmarks)
- [Standards & protocols](#standards--protocols)
- [How the approaches differ (cheat sheet)](#how-the-approaches-differ-cheat-sheet)

## What "agent memory" means
A useful split the field keeps rediscovering:
- **Semantic / factual memory** — *who the user is*, preferences, entities, facts. (Personalization.)
- **Episodic memory** — *what happened*, raw trajectories of past runs.
- **Procedural memory** — *how to do the work*, reusable routines distilled from successful experience. (The least-served, hardest layer.)
- **Working memory** — the current task's scratchpad / live context.

## Surveys & background
- [A Survey on the Memory Mechanism of Large Language Model based Agents](https://arxiv.org/abs/2404.13501) — comprehensive taxonomy of agent memory types, storage, and retrieval.
- [LLM Agent Memory: From LLMs to MoAs and Beyond](https://arxiv.org/abs/2504.13173) — surveys memory architectures across single-agent and multi-agent systems.

## Foundations (pre-LLM roots)
*Procedural/skill memory is a 40-year-old idea; cite the lineage honestly.*
- **Case-based reasoning (CBR)** — reuse and adapt solutions to past cases. (Schank; Kolodner; Aamodt & Plaza.)
- **Macro-operator learning** — compile successful action sequences into reusable macros (classical planning).
- **Programming / learning by demonstration** — induce procedures from demonstrated traces.

## Experiential / trajectory learning
- [**Reflexion**](https://arxiv.org/abs/2303.11366) — agents improve via verbal self-reflection on past failures.
- [**ExpeL**](https://arxiv.org/abs/2308.10144) — extract insights/skills from collected experience for future tasks.
- [**Voyager**](https://arxiv.org/abs/2305.16291) (NeurIPS 2023) — lifelong agent that writes code *skills* from experience and stores them in a retrievable skill library.
- [**Generative Agents**](https://arxiv.org/abs/2304.03442) (Park et al. 2023) — memory stream + reflection for believable agent behavior.
- [**REMEMBERER**](https://arxiv.org/abs/2403.14381) — persistent experience memory of (goal, observation, action, value) records, retrieved to bias action selection.

## Procedural / workflow-memory induction
*The sub-field Howdex sits in — induce reusable routines from successful trajectories and reuse them.*
- [**Agent Workflow Memory (AWM)**](https://arxiv.org/abs/2409.07429) — Wang, Mao, Fried, Neubig (CMU/MIT), ICML 2025. Induces reusable workflows from agent trajectories (rule-based *or* LLM-based extraction; LLM-based generalized better), retrieves by goal similarity, offline + online; evaluated on WebArena & Mind2Web. **The reference baseline for this category.**
- [**ProcMEM**](https://arxiv.org/abs/2502.11434) — learning reusable procedural memory from experience (non-parametric, RL-flavored).
- [**WISE-Flow**](https://arxiv.org/abs/2502.19094) — workflow-induced structured experience for self-evolving service agents; emphasizes explicit, checkable prerequisites and recovery paths.
- [**AutoGuide**](https://arxiv.org/abs/2310.01464) — distills offline trajectories into concise, context-aware conditional guidelines retrieved at test time.
- [**A-MEM**](https://arxiv.org/abs/2502.12110) — agentic memory for LLM agents (self-organizing memory notes).
- [**ACE (Agentic Context Engineering)**](https://arxiv.org/abs/2505.13446) — evolving contexts for self-improving models.

## Open-source & commercial memory systems
*Mostly semantic/factual + temporal; LLM-summarization-based; cloud-first.*
- [**Mem0**](https://github.com/mem0ai/mem0) — popular memory layer for agents (facts/preferences); SDK + hosted.
- [**Zep / Graphiti**](https://github.com/getzep/zep) — temporal knowledge-graph memory; strong on recall benchmarks.
- [**Letta**](https://github.com/letta-ai/letta) (formerly MemGPT) — OS-inspired agent runtime with self-editing memory blocks; self-hostable.
- [**Cognee**](https://github.com/topoteretes/cognee) — local-first memory/knowledge pipelines for agents.
- [**LangMem**](https://github.com/langchain-ai/langmem) — memory utilities in the LangChain ecosystem.
- [**MemOS**](https://arxiv.org/abs/2507.03724) — "memory operating system" framing for LLM memory.
- **Supermemory / Memobase** — memory APIs (several aimed at coding agents via MCP).

## Deterministic / verifiable / local-first procedural memory
*A distinct stance: no LLM in the extraction loop, inspectable, portable, with verification.*
- [**Howdex**](https://github.com/rossbuckley1990-hash/Howdex) — deterministic, local-first **procedural** memory for AI agents. Distills successful execution traces into canonical, inspectable procedures with provenance and a verification layer (the **Howdex Codex**: an open catalogue where a procedure's trust status is gated on attached receipts — "no proof, no procedure"). Portable across models, frameworks, and clouds; MCP server + framework adapters.
  - *Tradeoff stated honestly:* deterministic extraction trades some generalization (vs LLM-based extraction, per AWM's own results) for auditability, zero extraction cost, and local/private operation.

## Benchmarks
- [**WebArena**](https://webarena.dev/) — 812 realistic web tasks across 5 sites (the AWM benchmark).
- [**Mind2Web**](https://osu-nlp-group.github.io/Mind2Web/) — generalist web-agent benchmark (1000+ tasks, 200+ domains).
- [**LoCoMo / LongMemEval**](https://arxiv.org/abs/2410.10813) — long-conversation / long-term-memory recall benchmarks (semantic-memory-leaning).
- *(Procedural memory lacks a strong shared benchmark — a real opening for the community.)*

## Standards & protocols
- [**Model Context Protocol (MCP)**](https://modelcontextprotocol.io/) — the emerging standard for connecting agents to tools/servers; the practical distribution channel for any memory backend.

## How the approaches differ (cheat sheet)

| Axis | Semantic memory (Mem0/Zep/Letta) | Workflow induction (AWM, ProcMEM) | Deterministic procedural (Howdex) |
|---|---|---|---|
| Stores | facts, preferences | reusable routines | reusable routines |
| Extraction | LLM summarization | LLM or rule-based | rule-based (no LLM) |
| Inspectable / auditable | usually no | partial | yes (provenance + receipts) |
| Generalization | n/a | high (LLM) | bounded by canonicalizer |
| Local-first / no-LLM | varies | no | yes |
| Verification of reuse | rare | rare | explicit (Codex) |

## Contributing
PRs welcome. Entries must be factual and neutral. One line per project, link to the primary source (paper or repo). No promotional language — including for the maintainers' own projects.
