# Changelog

## 0.3.0 - Inspectable Procedural Extraction

### Added

- Deterministic canonical action vocabulary for common software-agent traces
- Domain-portable canonicalisation from structured tool names, typed arguments,
  and framework metadata
- Stable target projection with canonical argument hashing and secret redaction
- First-class deterministic intent and side-effect ontologies with inspectable
  matched rules
- Session-scoped working-memory context with deterministic importance/recency
  eviction, prompt budgeting, and bounded episodic snapshots
- Structured episodic provenance and conservative task/target/idle/step-count
  segmentation with raw-parent preservation
- Explicit provenance-rich semantic writes and deterministic tool
  system/action/target entity relations with stable IDs
- Deterministic pre-action procedure suggestions and bounded prompt guidance
  with match explanations and source episode evidence
- Idempotent procedure suggestion/use/outcome feedback with automatic session
  resolution and deterministic success/confidence updates
- Provider-neutral, idempotent verification receipts for procedures, including
  optional defensive import of local BootProof-like attestations
- Receipt-backed verification status in procedure suggestions and portable
  procedure exports
- Deterministic procedure parameterisation for volatile command and tool-call
  arguments, with stable typed placeholders and redacted example bindings
- Generalized procedure templates layered on canonical actions so repeated
  workflows learn reusable algorithms rather than hardcoded macros
- Strictly typed deterministic ingestion records and middleware for dirty
  terminal, stdout, stderr, observation, and error payloads
- ANSI stripping, progress/stack/repeated-line compression, bounded payload
  truncation, and mandatory secret redaction before episodic storage
- Additive DAG metadata for episodic and procedural steps, including stable
  step IDs, parent edges, spans, parallel groups, timing, and display ordering
- Deterministic parallel-span resolution, order-insensitive consolidation
  nodes, portable DAG JSON, and grouped human guidance rendering
- Canonical structured-step learning identities with recursive JSON
  normalization, safe JSON-string decoding, and stable compact serialization
- Structured shell-command adaptation so JSON key order, whitespace, and
  parameterized package/path literals cannot fragment procedure extraction
- Near-match grouping using canonical subsequence and Jaccard similarity
- Procedure confidence, support/success counts, source episode IDs, and raw evidence
- Conservative procedural retrieval capped at three high-confidence results
- Semantic conflict flags for obvious contradictory preferences
- Additive SQLite migration for v0.3 procedure evidence
- Portable procedure format v2 with backward-compatible v1 imports

### Changed

- Learned procedure steps now use stable canonical action names
- Internal memory calls and unknown-dominated traces are excluded
- Package version advanced to `0.3.0`

### Fixed

- Procedure LCS now compares canonical parameter slots and normalized
  structured arguments instead of concrete path, package, and command values
- Equivalent traces such as `edit app.js` / `edit server.js` and
  `npm install cors` / `npm install express` now consolidate into one reusable
  template without making English phrasing part of identity
- Structured write content and file arguments now use typed
  `<CONTENT_n>` / `<FILE_PATH_n>` slots, fixing `fs.write` workflows that
  previously split on concrete payloads
- Package-manager and file-execution commands now mask volatile targets across
  npm, pnpm, yarn, pip, poetry, cargo, Go, pytest, Python, Node, and ts-node
- Parameterized learning provenance and exports use `<SECRET_REDACTED>` and
  never retain secret values as example bindings

## 0.2.0 - Production Foundation

### Added

- Stable session API: `with mem.session(...) as s`
- Trust-aware memory API: `remember_trusted(...)`
- Production healthcheck: `howdex health`
- Evaluation CLI: `howdex eval swe-repeat`
- LangChain adapter
- OpenAI Agents SDK adapter
- MCP adapter
- CI-safe hash embedder via `HOWDEX_EMBEDDER=hash`
- Meta-cognition filter to prevent `inspect_howdex` leaking into learned procedures
- Procedure JSON normalisation at API/storage boundaries
- SWE-repeat benchmark over eligible real OSS npm test suites
- JSON benchmark export
- `BENCHMARKS.md` report generator
- Nightly benchmark GitHub Actions workflow
- Release hardening report
- Howdex-SWE-Repeat-50 roadmap

### Fixed

- Procedure learning from JSON-encoded episode steps
- Existing procedure update from dict-backed storage
- Hashing embedder `ngram` initialisation
- Hugging Face model loading during hash/offline mode
- Cognitive tool leakage into executable procedures

### Current benchmark result

Howdex reduced repeated unsafe test failures by 50% versus no-memory and vector-only baselines on eligible real OSS npm test suites after controlled source-code fault injection.

### Caveat

This is not full SWE-bench yet. It is a smaller, repeatable, local SWE-style benchmark.
