# Architecture

This document describes Howdex's internal design. For usage, see the [README](../README.md).

## Design Principles

1. **Local-first.** Everything works offline. Cloud is optional.
2. **Zero-config by default, configurable when needed.** `Howdex()` just works. `Howdex(embedder="st", path="/data/x.db")` when you care.
3. **Embeddable.** No server process required. One Python import.
4. **Framework-agnostic.** The core knows nothing about LangChain/CrewAI/etc. Adapters bridge.
5. **CRDT-correct.** Sync never loses data. Conflicts resolve deterministically.
6. **Inspectable.** SQLite + JSON. You can always `sqlite3 howdex.db` and look.

## System Diagram

```
┌──────────────────────────────────────────────────────────┐
│                       Agent Code                         │
│              (yours, or a framework adapter)             │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│                    howdex.core.Howdex                     │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │remember()│  │ recall() │  │ learn()  │  │ sync()  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│       │              │              │              │      │
│       ▼              ▼              ▼              ▼      │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              Hybrid Retrieval                       │ │
│  │  ┌────────┐  ┌─────────┐  ┌────────────────────┐   │ │
│  │  │ Vector │  │ Keyword │  │ Graph (1-hop BFS)  │   │ │
│  │  └────┬───┘  └────┬────┘  └─────────┬──────────┘   │ │
│  │       └───────────┴─────────────────┘              │ │
│  │            weighted sum: 0.6/0.3/0.1               │ │
│  └─────────────────────────────────────────────────────┘ │
└────────────────────────┬─────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│  Embedder    │  │   Store     │  │ VectorIndex  │
│              │  │             │  │              │
│ • hashing    │  │ • SQLite    │  │ • HNSW       │
│ • sent-trans │  │ • WAL mode  │  │ • NumPy BF   │
│ • OpenAI     │  │ • tombstones│  │              │
└──────────────┘  └──────┬──────┘  └──────────────┘
                         │
                  ┌──────▼──────┐
                  │  sync_log   │
                  │ (CRDT ops)  │
                  └─────────────┘
```

## The Four Memory Layers

Howdex's layer model is based on cognitive science (Atkinson-Shiffrin memory model + Tulving's episodic/semantic distinction + procedural memory).

| Layer | Cognitive analog | Retention | Write trigger |
|---|---|---|---|
| Working | RAM-like session context | seconds-minutes | Per-task scratchpad |
| Semantic | Declarative knowledge | long-term | Facts, preferences |
| Episodic | Autobiographical memory | long-term | Session logs |
| Procedural | Procedural memory (skills) | long-term | Output of `learn()` |

### Why four layers?

A single "memory" bucket fails because different memories have different lifecycles:
- "User just asked X" is irrelevant in 5 minutes (→ working)
- "User is allergic to peanuts" is forever (→ semantic)
- "Deploy failed at 3am" is a log entry (→ episodic)
- "To deploy: tests → build → ship" is a skill (→ procedural)

Mixing these in one store means you either lose the short-term stuff too fast or drown the long-term stuff in noise. Separate layers = separate retrieval strategies, separate retention policies, separate consolidation paths.

Working-memory prompt injection is deterministic and session-scoped. Expired
items are removed first; the remaining items are ranked by relative recency and
importance using fixed 35%/65% weights, then bounded by item and
character/token budgets. Session close stores a bounded snapshot and memory
references in the resulting episodic memory, while the original working
records retain their TTL.

Episodic memory stores the full raw session as structured evidence, including
task, timing, outcome/error, source/provenance, and structured canonical tool
steps. Long sessions may additionally produce deterministic child episodes.
Boundaries are explicit task markers, conservative target-domain changes,
idle gaps, then maximum step count as a fallback. Children retain
`parent_session_id`; consolidation prefers those children and excludes the raw
parent from duplicate evidence counting.

Semantic memory deliberately avoids implicit prose extraction. Explicit
facts, preferences, entities, and relations retain source, provenance, and
optional confidence metadata. Structured tool calls may deterministically
project the tool system, canonical action, salient target entities, and
action-target relations. Free-form text and secret arguments are excluded.
Optional `SemanticExtractor` implementations—including LLM-backed ones—are
application-controlled, non-deterministic extensions rather than part of the
default path.

Procedural retrieval can run before an action. `suggest_procedure()` combines
task-signature similarity, canonical action overlap, target/domain hints, and
stored confidence/success evidence using fixed local weights. It returns
structured suggestions with source episode IDs and match components.
`render_procedure_guidance()` produces bounded prompt text with an explicit
guidance-only warning; retrieval never authorizes or executes an action.

Procedure feedback is stored as an idempotent event state keyed by procedure
and session/episode reference: suggested, used-but-unverified, then observed
success or failure. Suggestions do not affect efficacy statistics. Verified
outcomes update aggregate success/failure counts, provenance episode IDs,
success rate, and a deterministic confidence blend of extraction confidence,
observed success, and evidence volume. Successful or failed session close
automatically resolves pending uses; partial sessions remain unverified.

## Storage: SQLite

We chose SQLite for the v0.1 storage backend because:

1. **Embedded.** No server process. `import howdex` and it works.
2. **Crash-safe.** WAL mode + atomic transactions. No corruption on power loss.
3. **Single-file.** Copy `howdex.db` to back up. Send it to sync. Done.
4. **Fast enough.** 100K memories + HNSW = sub-5ms recall.
5. **Universal.** Every platform has SQLite. Every language can read it.

Schema is in `howdex/storage/sqlite_store.py`. Key tables:

- `memories` — all four layers, with embedding BLOB, relations JSON, vector_clock
- `episodes` — denormalized session logs (for fast consolidation)
- `procedures` — learned workflows (also mirrored into `memories` as procedural layer)
- `sync_log` — CRDT op log (every write/delete appended here)

### Tombstones

Deletes are soft (`deleted=1`), not physical. This is required for CRDT correctness — if agent A deletes a memory that agent B hasn't seen yet, B needs to learn about the deletion when they sync. `vacuum()` physically removes tombstones older than 7 days.

## Vector Index

Two backends, same interface:

### HNSW (preferred)

- Library: `hnswlib`
- Complexity: O(log n) search, O(log n) insert
- Quality: high recall (>95% at k=10)
- Memory: ~1KB per vector (M=16, ef=64)

### NumPy brute-force (fallback)

- Complexity: O(n) search
- Quality: exact (100% recall)
- Memory: 4 bytes × dim per vector

Auto-selected at startup based on whether `hnswlib` is installed.

The index is **ephemeral** — it lives in process memory and is rebuilt from SQLite on engine startup. This is fine for <1M memories (rebuild takes ~1s per 100K). v0.2 will add persistent index files.

## Embedders

Three backends:

| Backend | Dim | Quality | Latency | Cost |
|---|---|---|---|---|
| `hashing` | 384 | low | <1ms | free, offline |
| `sentence-transformers` | 384 | high | ~15ms | free, offline, ~80MB model |
| `openai` | 1536 | highest | ~100ms | $0.02/1M tokens |

`auto_embedder()` picks a local sentence-transformer when the optional backend
is available, then falls back to hashing. Override with
`Howdex(embedder="hashing")` for deterministic CI/offline use or pass any
custom `Embedder`.

The `hashing` embedder is intentionally simple — char n-gram hashing into 384-dim space, L2-normalized. It's deterministic, dependency-free, and good enough for testing and small datasets. For production, use ST.

## Retrieval: Hybrid Search

`recall()` uses three retrieval strategies and combines them:

1. **Vector** (weight 0.6): cosine similarity over embeddings via HNSW
2. **Keyword** (weight 0.3): TF overlap on tokenized content + metadata
3. **Graph** (weight 0.1): 1-hop BFS over `memory.relations`

Final score = `0.6 * vector + 0.3 * keyword + 0.1 * graph`, filtered by `min_score`, sorted desc, truncated to `top_k`.

### Why hybrid?

- Vector alone misses exact-match queries ("error code 5001")
- Keyword alone misses semantic similarity ("deploy" vs "ship to prod")
- Graph alone is too sparse (most memories have no relations)

The weights (0.6/0.3/0.1) are empirical defaults. v0.2 will make them configurable.

## Consolidation: `learn()`

The consolidation algorithm is intentionally simple and explainable:

```
for each task_signature with ≥ min_samples episodes:
    successes = episodes where outcome == "success"
    failures  = episodes where outcome == "failure"
    
    common_steps = longest action subsequence common to ≥50% of successes
    preconditions = actions in successes but not in failures
    success_rate = len(successes) / len(episodes)
    
    write Procedure(task_signature, common_steps, preconditions, success_rate)
```

### Why not ML?

We considered training a sequence model on episodes. We decided against it for v0.1:

1. **Explainability.** An agent needs to explain *why* it knows something. A Procedure is human-readable. A model's weights are not.
2. **No training data needed.** LCS-style extraction works on day one, with 3 samples.
3. **Deterministic.** Same episodes → same procedure. Easy to test.
4. **Cheap.** ~200ms for 1K episodes. No GPU.

v0.3 will add an optional ML-based consolidator for users who want higher quality and have more data.

## CRDT Sync

Conflict-free Replicated Data Types. The properties we need:

1. **Convergence.** All nodes eventually agree on the same state.
2. **Intention preservation.** No op is silently dropped.
3. **Commutativity.** Ops can be applied in any order.

### Implementation

Every memory carries:
- `vector_clock` (int, monotonically increasing per node)
- `node_id` (UUID, assigned at `init`)

Conflict resolution: **last-writer-wins on `(vector_clock, node_id)`**. Ties broken by `node_id` lexicographically. Deterministic across all nodes.

Deletes are tombstones (the row stays, `deleted=1`). This ensures a delete propagates correctly even if the other node hasn't seen the create yet.

### Sync transport

Two modes:

- **File** — `sync_to_file()` writes pending ops to JSON. `sync_from_file()` reads + applies. Great for air-gapped / sneakernet.
- **HTTP** — `sync_with_peer()` POSTs our pending ops to `peer/sync/push` (peer applies them), then GETs `peer/sync/pull` (we apply theirs). Two-way sync in one round trip.

The HTTP transport is served by the MCP server's `/sync/push` and `/sync/pull` endpoints. So any Howdex node can be a sync peer.

## MCP Server

[Model Context Protocol](https://modelcontextprotocol.io) is Anthropic's standard for tool servers. Howdex's MCP server exposes:

- `tools/list` — returns the 5 tool schemas
- `tools/call` — dispatches to `remember` / `search` / `learn` / `forget` / `stats`

Two transports:

- **stdio** — for local clients (Claude Desktop, Cursor). Each message is a newline-delimited JSON-RPC request.
- **HTTP** — for remote clients. POST `/mcp` with JSON-RPC body. Also serves `/sync/push`, `/sync/pull`, `/health`.

## Framework Adapters

Adapters are thin wrappers that expose `Howdex` through a framework's expected interface:

- `LangChainMemoryAdapter` implements LangChain's `BaseMemory` (`load_memory_variables`, `save_context`)
- `CrewAIMemoryAdapter` implements `store` / `search` / `reset`
- `AutoGenMemoryAdapter` exposes `retrieve(query) -> list[str]`
- `OpenAIAssistantToolsAdapter` returns OpenAI function-calling tool schemas
- `GenericAdapter` — bare wrapper, use anywhere

Adapters never store state themselves — they delegate everything to `Howdex`. This means sync, consolidation, and all retrieval strategies work transparently through any adapter.

## Performance Characteristics

| Operation | Time | Bottleneck |
|---|---|---|
| `remember()` (hashing) | 1ms | SQLite write |
| `remember()` (ST) | 18ms | Embedding computation |
| `recall()` (HNSW, top-5) | 0.3ms + embed | Embedding computation |
| `recall()` (NumPy BF, top-5) | 4.8ms + embed | Linear scan |
| `learn()` (1K episodes) | 220ms | LCS extraction |
| `sync()` (1K ops, file) | 45ms | JSON serialize + SQLite apply |
| `sync()` (1K ops, HTTP) | 180ms | Network + JSON |

Memory footprint: ~50MB for 100K memories (dominated by embeddings in the vector index).

## Future Directions

- **Rust core** (v0.2) — PyO3 bindings for 10x throughput on hot paths
- **Persistent HNSW** (v0.2) — no rebuild on startup
- **WASM plugins** (v0.3) — custom embedders / consolidators in any language
- **Graph query language** (v0.3) — Cypher-subset for the knowledge graph
- **Distributed mode** (v1.0) — multi-node Howdex clusters with sharding
