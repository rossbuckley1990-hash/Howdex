# Contributing to Howdex

Thanks for considering a contribution! Howdex is built by the community, for the community.

## Quick Start

```bash
git clone https://github.com/rossbuckley1990-hash/Howdex
cd Howdex
python -m pip install -e ".[dev]"
pytest
```

## Code Style

- We use [ruff](https://github.com/astral-sh/ruff) for linting and formatting.
- Line length: 100 chars.
- Python 3.9+ (use `from __future__ import annotations` for modern type hints).

```bash
ruff check howdex/ tests/
ruff format howdex/ tests/
```

## Type Checking

```bash
mypy howdex/
```

We're not at 100% mypy coverage yet, but new code should be typed.

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=howdex --cov-report=html

# Run a specific test file
pytest tests/test_engine.py -v
```

All PRs must pass the existing test suite. New features need new tests.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design. TL;DR:

- `howdex/core/` — the engine, types, consolidation, retrieval
- `howdex/storage/` — SQLite backend (pluggable)
- `howdex/vectors/` — HNSW/NumPy index + embedders
- `howdex/sync/` — CRDT sync
- `howdex/adapters/` — framework integrations
- `howdex/mcp/` — MCP server
- `howdex/cli/` — the `howdex` command

## Adding a New Framework Adapter

1. Create `howdex/adapters/yourframework.py`
2. Implement the framework's memory interface, delegating to `Howdex`
3. Add tests in `tests/test_adapters.py`
4. Add an example in `examples/`
5. Update `README.md`'s Framework Adapters section

## Adding a New Embedder

1. Subclass `Embedder` in `howdex/vectors/embedder.py`
2. Implement `embed(text) -> list[float]` and `embed_batch(texts) -> list[list[float]]`
3. Set the `dim` and `name` class attributes
4. Add it to `auto_embedder()`'s selection logic if it should be auto-discoverable
5. Add a test

## Adding a New Storage Backend

The storage interface is defined by `Store` in `howdex/storage/sqlite_store.py`. To add a new backend (e.g. DuckDB, Postgres):

1. Create `howdex/storage/duckdb_store.py`
2. Implement all public methods of `Store`
3. Add a backend selector in `howdex/storage/__init__.py`
4. Add tests

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add DuckDB storage backend
fix: handle empty embedding in HNSW search
docs: clarify CRDT conflict resolution
test: add integration test for multi-agent sync
refactor: extract consolidation algorithm
```

## Pull Request Process

1. Fork the repo, create a feature branch (`git checkout -b feat/my-feature`)
2. Write tests for your changes
3. Ensure `pytest` and `ruff check` pass
4. Update `CHANGELOG.md`
5. Open a PR with a clear description

## Reporting Bugs

Use [GitHub Issues](https://github.com/rossbuckley1990-hash/Howdex/issues). Include:

- Howdex version (`howdex --version`)
- Python version
- OS
- Minimal reproduction script
- Expected vs actual behavior

## Feature Requests

We'd love to hear your ideas. Open an issue with the `enhancement` label. The best way to get a feature shipped is to contribute it.

## Code of Conduct

Be kind. Be patient. Assume good intent. We're building something together.
