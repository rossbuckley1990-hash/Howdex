# Installation Guide

Howdex ships in three forms. Pick whichever matches your environment.

## 1. From a wheel (zero build tooling required)

If you have `howdex_ai-0.3.0-py3-none-any.whl` (in `dist/` of the zip), you can install it without any build backend:

```bash
pip install howdex_ai-0.3.0-py3-none-any.whl
```

This works on any pip ≥ 19 and requires **no setuptools, no wheel, no internet** (after download). Use this for:
- Air-gapped / restricted environments
- CI where you don't want to compile anything
- Older systems with legacy setuptools

## 2. From source (PEP 517)

```bash
unzip howdex-0.3.0.zip
cd howdex
pip install .
```

Requires `setuptools >= 61` (the minimum that supports the `[project]` table in `pyproject.toml`). This ships with Python 3.9+ and pip 21+, so most modern environments have it.

If you get `error: invalid command 'bdist_wheel'`, install wheel explicitly:

```bash
pip install --upgrade setuptools wheel
pip install .
```

## 3. Editable / development install

```bash
unzip howdex-0.3.0.zip
cd howdex
pip install -e ".[dev]"
```

The `-e` flag installs in "editable" mode — edits to the source take effect immediately without reinstalling. The `[dev]` extra pulls in `pytest`, `ruff`, and `mypy`.

## 4. Try without installing

You can run Howdex straight from the unzipped source tree, no install needed:

```bash
unzip howdex-0.3.0.zip
cd howdex

# The `python -m howdex` form works because howdex/__main__.py exists
python -m howdex init
python -m howdex remember "hello world"
python -m howdex search "hello"

# Run the test suite
python -m pytest

# Run an example
python examples/quickstart.py
```

This works because Python adds the current directory to `sys.path` when you run `-m`, so the `howdex` package is importable from the source tree.

## Optional extras

| Extra | Command | What it adds |
|---|---|---|
| `hnsw` | `pip install ".[hnsw]"` | Production-grade HNSW vector index (recommended for >10K memories) |
| `st` | `pip install ".[st]"` | `sentence-transformers` for neural embeddings (~80MB model) |
| `openai` | `pip install ".[openai]"` | OpenAI `text-embedding-3-small` (1536-dim, needs `OPENAI_API_KEY`) |
| `full` | `pip install ".[full]"` | `hnsw` + `st` |
| `dev` | `pip install -e ".[dev]"` | pytest, ruff, mypy (for contributors) |

You can combine extras: `pip install ".[hnsw,openai]"`.

## Verify the install

```bash
howdex --version          # should print: howdex 0.3.0
howdex init               # creates ~/.howdex/howdex.db
howdex remember "test"
howdex search "test" --min-score 0.0
```

## Common issues

### `pip install .` fails with `error: invalid command 'bdist_wheel'`

Your setuptools is too old. Fix:

```bash
pip install --upgrade setuptools wheel
pip install .
```

Or just use the prebuilt wheel from `dist/`.

### `python -m howdex.cli` says `No module named howdex.cli`

You're outside the source directory and haven't installed. Either:
- `cd` into the unzipped `howdex/` directory, **or**
- `pip install .` (or the wheel), **or**
- use `python -m howdex` (the top-level entry, added in v0.1.1)

### Tests pass but CLI doesn't work

This means `howdex` is not on your `PATH`. Either:
- Use `python -m howdex ...` instead, **or**
- Reinstall: `pip install --force-reinstall .`, **or**
- Find the script: `python -c "import shutil; print(shutil.which('howdex'))"` and add its directory to `PATH`.

### `ModuleNotFoundError: No module named 'hnswlib'` when recalling

You didn't install the `hnsw` extra. Howdex falls back to the NumPy brute-force index automatically, but it's slower. To fix:

```bash
pip install ".[hnsw]"
```

### `sentence-transformers` is slow on first use

The first call downloads the model (~80MB for `all-MiniLM-L6-v2`). Subsequent calls use the cached model. To pre-warm:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

## Uninstall

```bash
pip uninstall howdex-ai
rm -rf ~/.howdex    # optional: remove local databases
```
