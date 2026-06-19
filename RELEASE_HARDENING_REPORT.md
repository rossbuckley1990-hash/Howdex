# Howdex Release Hardening Report

## Current status

Howdex is a benchmarked prototype of safe procedural memory for AI agents.

It has moved beyond demos into a production-style foundation:

- stable session API
- first-class trust metadata helper
- production healthcheck
- CLI evaluation command
- framework adapter modules
- regression tests
- CI workflow
- real OSS failing test-suite benchmark

## Core validated claim

Howdex helps agents stop failing the same way twice.

## Strongest benchmark result

Howdex reduced repeated unsafe test failures versus no-memory and vector-only baselines on eligible real OSS npm test suites after controlled source-code fault injection.

The current SWE-repeat benchmark uses:

- real cloned OSS repositories
- real npm install
- real clean npm test
- controlled source-code fault injection
- real failing npm test
- real repair
- real rerun of npm test
- baseline comparison

## Production APIs added

### Session API

    from howdex import Howdex

    mem = Howdex("./howdex.db")

    with mem.session("deploy api") as s:
        s.step("check_database_url", "present")
        s.step("run_tests", "passed")

### Trust-aware memory API

    mem.remember_trusted(
        "Before deployment, check DATABASE_URL.",
        source="system",
        trust="verified",
        safety="operational",
    )

### Evaluation CLI

    howdex health
    howdex eval swe-repeat

## Framework adapters

Initial adapters have been added for:

- LangChain
- OpenAI Agents SDK
- MCP

These expose Howdex memory as inspect/remember tools for agent frameworks.

## CI

GitHub Actions runs:

- install
- healthcheck
- unit tests
- production API tests
- SWE-repeat benchmark smoke test

CI uses HOWDEX_EMBEDDER=hash to avoid external model downloads.

## Current caveats

Howdex is not yet fully production-grade.

Remaining work:

1. Versioned database migrations
2. Concurrent writer safety tests
3. More adversarial memory poisoning tests
4. Larger multi-family SWE-style benchmark
5. Adapter examples with full agent loops
6. Packaged documentation site
7. PyPI release checklist
8. Semantic versioning policy
9. API stability guarantees
10. Long-running memory ageing and forgetting tests

## Honest public claim

Howdex is a benchmarked prototype of safe procedural memory for AI agents.

It has demonstrated repeated-failure reduction versus no-memory and vector-only baselines on controlled real OSS test-suite repair tasks.

It is not yet full SWE-bench and not yet production-proven at enterprise scale.
