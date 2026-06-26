# Howdex Release Checklist

## Required before release

- [ ] Full test suite passes
- [ ] `howdex health` passes
- [ ] `howdex redteam run` passes (all 12 defenses held, exit code 0)
- [ ] `howdex eval swe-repeat` passes
- [ ] `BENCHMARKS.md` regenerated
- [ ] No API keys, `.env` files, local DBs, or benchmark clone folders committed
- [ ] Version bumped in `pyproject.toml` AND `howdex/__init__.py`
- [ ] CHANGELOG updated
- [ ] README quickstart works from a fresh virtualenv
- [ ] GitHub Actions CI passes (Tests, Benchmark smoke test, Red-team defenses)
- [ ] Nightly benchmark workflow exists
- [ ] Release tag created (`git tag v0.4.0 && git push origin v0.4.0`)
- [ ] GitHub release notes published
- [ ] PyPI publication automated via `.github/workflows/publish.yml`
      (triggers on tag push; requires `PYPI_API_TOKEN` repo secret)

## Local release gate

    HOWDEX_EMBEDDER=hash python -m pytest -q
    HOWDEX_EMBEDDER=hash howdex health
    HOWDEX_EMBEDDER=hash howdex redteam run
    HOWDEX_EMBEDDER=hash howdex eval swe-repeat
    python benchmarks/report.py
    python -m build
    python -m twine check dist/*

## PyPI publication (automated)

Howdex publishes to PyPI automatically when a `v*` tag is pushed. The
workflow lives at `.github/workflows/publish.yml`.

### One-time setup (operator)

1. **Create a PyPI account** at https://pypi.org/account/register/ (if
   you don't already have one). Use 2FA.

2. **Register the `howdex-ai` project** by uploading the first release
   manually (see "First-time manual upload" below). Subsequent releases
   are automated.

3. **Generate a PyPI API token** at
   https://pypi.org/manage/account/token/ with scope "Entire account"
   (or scoped to `howdex-ai` after the first upload).

4. **Add the token as a GitHub repository secret**:
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `PYPI_API_TOKEN`
   - Value: `pypi-<your token>`

### Publishing a release

    # 1. Ensure main is green and up to date
    git checkout main && git pull origin main

    # 2. Bump version (if not already bumped)
    #    Edit pyproject.toml and howdex/__init__.py
    #    Update CHANGELOG.md

    # 3. Commit and push
    git add -A && git commit -m "release: vX.Y.Z"
    git push origin main

    # 4. Tag and push the tag — this triggers the publish workflow
    git tag vX.Y.Z
    git push origin vX.Y.Z

    # 5. Create a GitHub release from the tag (optional but recommended)
    #    GitHub → Releases → Draft a new release → select the tag

    # 6. Watch the workflow:
    #    GitHub → Actions → "Publish to PyPI" → watch it build, check,
    #    upload, and verify.

    # 7. Verify on PyPI:
    #    https://pypi.org/project/howdex-ai/
    #    pip install howdex-ai==X.Y.Z

### First-time manual upload (if `howdex-ai` is not yet on PyPI)

The automated workflow will fail on the very first upload because the
project doesn't exist yet on PyPI. Do the first upload manually:

    python -m build
    python -m twine upload dist/*

    # Enter your PyPI username and password (or API token with
    # TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-...).

    # After the first upload succeeds, the project exists and the
    # automated workflow will work for all subsequent releases.

## Public release claim

Howdex is a benchmarked prototype of safe procedural memory for AI agents.

Current validated benchmark:

Howdex reduced repeated unsafe test failures by 50% versus no-memory and vector-only baselines on eligible real OSS npm test suites after controlled source-code fault injection.

## Caveat

This is not full SWE-bench yet. It is a smaller, repeatable, local SWE-style benchmark using real repositories, real npm installs, real test suites, and controlled source-code faults.

## 0.4.0 release notes

The 0.4.0 release adds four "outside-the-box" features that move Howdex
from "procedural memory" to "the audit and verification layer for AI
agents":

1. **Procedural compiler** (`howdex.compiler`) — compiles Howdex
   procedures into typed, executable Python skills with pre/post
   conditions and auto-generated tests. Trajectories → runnable code.

2. **Federated procedure library** (`howdex.federation`) — multi-tenant
   shared procedural memory with a proposed → reviewed → published →
   deprecated lifecycle. Teams can share verified procedures across
   agents and projects.

3. **HTML compliance reports** (`howdex.html_renderers`) — interactive,
   visual, audit-ready single-file HTML artifacts for SOC 2, EU AI Act,
   and NIST AI RMF. Inspired by Anthropic's "Unreasonable Effectiveness
   of HTML" article.

4. **Adversarial red-team harness** (`howdex.redteam`) — 12 canonical
   attack vectors across 4 defense surfaces (hallucinated-success,
   audit-trail, recall/ranking, multi-tenant/network). Runs on every
   PR via CI; exit code 2 blocks merge if any defense breaks.

Also includes: Merkle audit ledger, BootProof verifier gate,
`@instrument` decorator, LLM-assisted diagnostics, public procedure
registry, AWM benchmark protocol, and MCP server path-traversal guard.

