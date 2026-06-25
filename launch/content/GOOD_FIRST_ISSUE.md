# Good First Issues — Contributor Guide

Welcome to Howdex! This guide helps you find your first contribution.

## Quick start

```bash
git clone https://github.com/rossbuckley1990-hash/Howdex.git
cd Howdex
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest  # should pass 701 tests
```

## Issues tagged `good first issue`

### 1. Publish howdex-ai to PyPI (#32)
**Difficulty:** Easy (no code, just CI/CD setup)
**What:** Run `python -m build`, `twine upload dist/*`. Update README.
**Skills:** Python packaging, PyPI

### 2. Default to sentence-transformers when available (#33)
**Difficulty:** Easy (~10 lines of code)
**What:** In `howdex/vectors/embedder.py:auto_embedder()`, check if `sentence-transformers` is importable and use it by default.
**Skills:** Python, sentence-transformers

### 3. Write a tutorial: Howdex MCP server with Claude Desktop (#37)
**Difficulty:** Easy (documentation, no code)
**What:** Write a step-by-step tutorial with screenshots showing Claude Desktop + Howdex MCP.
**Skills:** Writing, Claude Desktop, MCP

### 4. Add more compliance framework mappings
**Difficulty:** Medium
**What:** Add ISO 42001 or COBIT mappings to `howdex/governance.py:FRAMEWORK_CONTROLS`.
**Skills:** Compliance frameworks, Python

### 5. Improve the semantic search
**Difficulty:** Medium
**What:** The current `registry_search` uses token overlap. Add TF-IDF or BM25 scoring for better ranking.
**Skills:** Information retrieval, Python

### 6. Add a Cursor-specific tutorial
**Difficulty:** Easy (documentation)
**What:** Write a tutorial showing Howdex MCP with Cursor IDE.
**Skills:** Cursor, MCP, writing

## How to contribute

1. Fork the repo
2. Create a branch: `git checkout -b fix/my-contribution`
3. Make your changes
4. Run tests: `python -m pytest`
5. Commit with a clear message
6. Open a PR

## Code style

- Python 3.9+ (uses `X | None` syntax)
- Ruff for linting: `ruff check howdex`
- Mypy for types: `MYPYPATH="" mypy --no-site-packages howdex`
- Line length: 100

## Questions?

Open a GitHub Discussion or issue. We're friendly.
