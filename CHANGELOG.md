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
