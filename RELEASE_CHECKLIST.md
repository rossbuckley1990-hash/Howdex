# Howdex Release Checklist

## Required before release

- [ ] Full test suite passes
- [ ] `howdex health` passes
- [ ] `howdex eval swe-repeat` passes
- [ ] `BENCHMARKS.md` regenerated
- [ ] No API keys, `.env` files, local DBs, or benchmark clone folders committed
- [ ] Version bumped in `pyproject.toml`
- [ ] CHANGELOG updated
- [ ] README quickstart works from a fresh virtualenv
- [ ] GitHub Actions CI passes
- [ ] Nightly benchmark workflow exists
- [ ] Release tag created
- [ ] GitHub release notes published

## Local release gate

    HOWDEX_EMBEDDER=hash python -m pytest -q
    HOWDEX_EMBEDDER=hash howdex health
    HOWDEX_EMBEDDER=hash howdex eval swe-repeat
    python benchmarks/report.py
    python -m build

## Public release claim

Howdex is a benchmarked prototype of safe procedural memory for AI agents.

Current validated benchmark:

Howdex reduced repeated unsafe test failures by 50% versus no-memory and vector-only baselines on eligible real OSS npm test suites after controlled source-code fault injection.

## Caveat

This is not full SWE-bench yet. It is a smaller, repeatable, local SWE-style benchmark using real repositories, real npm installs, real test suites, and controlled source-code faults.
