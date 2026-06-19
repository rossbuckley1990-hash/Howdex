# Howdex Identity Notes

This source tree uses **Howdex** as its final identity.

## Intended identity

- Product/system name: Howdex
- Python distribution: `howdex-ai`
- Import package: `howdex`
- Main class: `Howdex`
- CLI command: `howdex`
- Default home directory: `~/.howdex`
- Default database: `~/.howdex/howdex.db`
- Environment variables: `HOWDEX_HOME`, `HOWDEX_EMBEDDER`
- GitHub repo target: `github.com/rossbuckley1990-hash/Howdex`

## API note

The method `memory.recall(...)` is intentionally preserved as a generic retrieval verb.
The CLI uses `howdex search ...` as the primary search command and keeps `howdex recall ...` as an alias.

## Validation commands

```bash
HOWDEX_EMBEDDER=hash python -m pytest -q
HOWDEX_EMBEDDER=hash python -m howdex --version
HOWDEX_EMBEDDER=hash python -m howdex health
HOWDEX_EMBEDDER=hash howdex eval swe-repeat-9
```

## Validation result

- Editable install: passed in a repository-local virtual environment.
- Tests: 55 passed.
- Module and installed CLI version: `howdex 0.2.1`.
- Healthcheck: passed.
- Remember/search database flow: passed.
- `recall` CLI compatibility alias: passed.
- Default `HOWDEX_HOME` path: passed.
- Built wheel: contains `howdex`, contains no old import package, and installs cleanly.
- SWE-repeat-9: 9/9 eligible tasks passed across 3 fault families.
- Stale identity scan: no old product, package, environment-variable, path, or repository references remain.

## Final renamed paths

- `howdex/`
- `BENCHMARKS_HOWDEX_VS_MEM0.md`
- `docs/HOWDEX_SWE_REPEAT_50.md`
- `howdex_mcp_deploy_server.py`
- `langchain_howdex_agent_demo.py`
- `mcp_howdex_agent_demo.py`
- `openai_agents_howdex_demo.py`
- `openai_agents_howdex_demo_v2.py`
- `real_llm_agent_howdex_demo.py`

## Updated files

- Metadata/config: `pyproject.toml`, `.gitignore`, `Makefile`, `LICENSE`,
  `conftest.py`, `.github/workflows/ci.yml`,
  `.github/workflows/nightly-benchmarks.yml`, `scripts/release_gate.sh`.
- Documentation: `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `DEV_INSTALL.md`, `RELEASE_CHECKLIST.md`, `RELEASE_HARDENING_REPORT.md`,
  `BENCHMARKS.md`, `BENCHMARKS_MULTI_FAMILY.md`,
  `BENCHMARKS_HOWDEX_VS_MEM0.md`, `docs/ARCHITECTURE.md`,
  `docs/HOWDEX_SWE_REPEAT_50.md`, `benchmarks/swe_repeat/MEM0_COMPARISON.md`.
- Examples/demos: every file in `examples/`, all renamed demo files above,
  `real_agent_demo.py`, `real_agent_demo_v2.py`, `wow_demo.py`,
  `wow_demo_v2.py`, `breakthrough_gauntlet.py`, and every `stress_*.py` file.
- Benchmarks: `benchmarks/oss_repo_repair_benchmark.py`,
  `benchmarks/real_repo_repair_benchmark.py`,
  `benchmarks/real_test_suite_benchmark.py`, `benchmarks/report.py`,
  `benchmarks/swe_repeat_benchmark.py`, and the identity-bearing files in
  `benchmarks/swe_repeat/`.
- Tests: `tests/test_adapters_import.py`, `tests/test_cli.py`,
  `tests/test_engine.py`, `tests/test_meta_cognition_filter.py`,
  `tests/test_production_api.py`, `tests/test_store.py`,
  `tests/test_sync.py`, `tests/test_types.py`, `tests/test_vectors.py`.
- Package: every file under `howdex/`; `Howdex.search()` is now the preferred
  API and delegates to the retained `Howdex.recall()` implementation.

## Repository note

This workspace does not contain Git metadata, and the target GitHub repository
was not accessible during validation. The source tree is ready, but creating or
attaching the `github.com/rossbuckley1990-hash/Howdex` remote is still required
before pushing.
