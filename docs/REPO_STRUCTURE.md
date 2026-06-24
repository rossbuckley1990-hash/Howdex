# Repository structure

Howdex keeps public product surfaces, implementation code, benchmark harnesses,
and committed evidence separated so the repository reads like infrastructure,
not a scratchpad.

## Top-level files

- `README.md` — external product overview and quickstarts.
- `LICENSE` — project license.
- `pyproject.toml` — package metadata and dependencies.
- `Makefile` — common development and benchmark commands.
- `CHANGELOG.md` — release notes.

## Main directories

- `howdex/` — package code. Do not move public package source out of this
  directory.
- `tests/` — pytest suite covering package APIs, CLI behavior, docs, benchmark
  harnesses, and safety boundaries.
- `docs/` — user and developer documentation. Long explanations live here
  rather than in the README.
- `examples/` — runnable examples and integration snippets.
- `benchmarks/` — benchmark harness implementations. Root-level benchmark files
  should be compatibility wrappers only.
- `evidence/` — committed sanitized evidence and result artifacts. Runtime logs
  can still be written to local output folders, but curated committed evidence
  belongs here.
- `scripts/` — local and development helper scripts.
- `codex/` — procedure schemas and example Howdex Codex catalogue entries.
- `launch/` — external outreach drafts and tracking, split into `drafts/` and
  `tracking/`.

## Evidence layout

- `evidence/docker_n20/` — committed Docker recovery A/B n20 evidence.
- `evidence/dogfood/results/` — sanitized dogfood summary evidence.
- `evidence/trust_calibration/` — trust-calibration result notes.
- `evidence/awm_head_to_head/` — AWM-style head-to-head result notes.

## Compatibility wrappers

Some root-level benchmark script names are retained as compatibility wrappers
because docs, Makefile targets, or users may still run them directly. The
implementation should live under `benchmarks/`.

Examples:

- `real_docker_recovery_ab_test.py` wraps
  `benchmarks/docker_recovery/real_docker_recovery_ab_test.py`.
- `procedure_trust_calibration_test.py` wraps
  `benchmarks/trust_calibration/procedure_trust_calibration_test.py`.

New benchmark implementations should go under `benchmarks/` first.
