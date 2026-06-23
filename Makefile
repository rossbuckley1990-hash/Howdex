# Howdex — Makefile
#
# Common dev commands. Designed to work on any POSIX system with GNU make.
# If you don't have make, see DEV_INSTALL.md for the equivalent raw commands.

PYTHON ?= python
PIP    ?= $(PYTHON) -m pip

BENCHMARK_RESULTS_DIR ?= benchmark-results
DOCKER_BENCH_TRIALS ?= 5
DOCKER_BENCH_MAX_TURNS ?= 15
DOCKER_BENCH_BASE_IMAGE ?= python:3.12-alpine

.PHONY: help install install-dev install-full test test-cov lint format typecheck build clean dist verify examples bench bench-docker bench-docker-n20

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

bench:  ## Show available benchmark commands
	@echo "Available benchmark commands:"
	@echo "  make bench-docker      # Docker A/B benchmark, default n=$${HOWDEX_DOCKER_TRIALS:-$(DOCKER_BENCH_TRIALS)}"
	@echo "  make bench-docker-n20  # Headline Docker A/B benchmark, n=20"
	@echo ""
	@echo "Prerequisites: Docker running, $(DOCKER_BENCH_BASE_IMAGE) present locally, OPENAI_API_KEY set."
	@echo "The benchmark does not auto-pull images."

bench-docker:  ## Run the Docker A/B benchmark with a small default sample
	@mkdir -p "$(BENCHMARK_RESULTS_DIR)"
	@log="$(BENCHMARK_RESULTS_DIR)/docker-recovery-n$${HOWDEX_DOCKER_TRIALS:-$(DOCKER_BENCH_TRIALS)}-$$(date -u +%Y%m%dT%H%M%SZ).log"; \
		echo "Writing benchmark log to $$log"; \
		HOWDEX_DOCKER_TRIALS=$${HOWDEX_DOCKER_TRIALS:-$(DOCKER_BENCH_TRIALS)} \
		HOWDEX_DOCKER_MAX_TURNS=$${HOWDEX_DOCKER_MAX_TURNS:-$(DOCKER_BENCH_MAX_TURNS)} \
		python3 real_docker_recovery_ab_test.py > "$$log" 2>&1; \
		status=$$?; \
		cat "$$log"; \
		exit $$status

bench-docker-n20:  ## Run the headline Docker A/B benchmark with n=20
	@mkdir -p "$(BENCHMARK_RESULTS_DIR)"
	@log="$(BENCHMARK_RESULTS_DIR)/docker-recovery-n20-$$(date -u +%Y%m%dT%H%M%SZ).log"; \
		echo "Writing benchmark log to $$log"; \
		HOWDEX_DOCKER_TRIALS=20 HOWDEX_DOCKER_MAX_TURNS=15 \
		python3 real_docker_recovery_ab_test.py > "$$log" 2>&1; \
		status=$$?; \
		cat "$$log"; \
		exit $$status

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
