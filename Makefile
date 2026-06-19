# Howdex — Makefile
#
# Common dev commands. Designed to work on any POSIX system with GNU make.
# If you don't have make, see DEV_INSTALL.md for the equivalent raw commands.

PYTHON ?= python
PIP    ?= $(PYTHON) -m pip

.PHONY: help install install-dev install-full test test-cov lint format typecheck build clean dist verify examples

help:  ## Show this help
	@echo "Howdex — common commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install Howdex (basic, hashing embedder only)
	$(PIP) install .

install-editable:  ## Editable install for development (no reinstall on edit)
	$(PIP) install -e .

install-full:  ## Install with all optional extras (hnsw + sentence-transformers)
	$(PIP) install ".[full]"

install-dev:  ## Editable install with dev tools (pytest, ruff, mypy)
	$(PIP) install -e ".[dev]"

test:  ## Run the test suite
	$(PYTHON) -m pytest

test-cov:  ## Run tests with coverage report
	$(PYTHON) -m pytest --cov=howdex --cov-report=term-missing

lint:  ## Lint with ruff
	$(PYTHON) -m ruff check howdex/ tests/

format:  ## Auto-format with ruff
	$(PYTHON) -m ruff format howdex/ tests/

typecheck:  ## Type-check with mypy
	$(PYTHON) -m mypy howdex/

build:  ## Build sdist (.tar.gz) and wheel (.whl) into dist/
	$(PYTHON) -m pip install --quiet --upgrade build
	$(PYTHON) -m build

dist: build  ## Alias for build

verify:  ## End-to-end smoke test: install, run tests, run quickstart
	$(PIP) install -e .
	$(PYTHON) -m pytest
	$(PYTHON) examples/quickstart.py

examples:  ## Run all examples (quickstart, multi-agent, mcp)
	$(PYTHON) examples/quickstart.py
	$(PYTHON) examples/multi_agent_sync.py
	$(PYTHON) examples/mcp_client.py

clean:  ## Remove build artifacts, caches, and test databases
	rm -rf build/ dist/ *.egg-info howdex/*.egg-info
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.db" -not -path "./.git/*" -delete 2>/dev/null || true
	find . -name "*.db-wal" -delete 2>/dev/null || true
	find . -name "*.db-shm" -delete 2>/dev/null || true
	rm -rf .mypy_cache/ .ruff_cache/ htmlcov/ .coverage
