# Changelog

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
