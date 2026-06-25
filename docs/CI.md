# Codex CI

Howdex Codex entries should be reviewed like code. The CI path is local-first:
it runs the Howdex CLI against JSON entries in the repository and does not call
a hosted Howdex service, external API, Docker daemon, or model provider.

## GitHub Actions

Use the bundled composite action from the same repository checkout:

```yaml
name: Howdex Codex check

on:
  pull_request:
    paths:
      - "codex/**"

jobs:
  codex-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Howdex
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"

      - name: Check Codex entries
        uses: ./.github/actions/howdex-codex-check
        with:
          codex_path: codex
          fail_on_stale: "true"
          fail_on_high_risk: "true"
```

The action runs:

```bash
howdex codex lint <codex_path>
howdex codex policy-check <codex_path>
howdex codex verify <codex_path>
```

It writes a Markdown job summary and exposes outputs for:

- `summary_markdown`
- `entries_count`
- `candidate_count`
- `verified_count`
- `stale_count`
- `blocked_count`
- `failed_rules`

See [examples/github-actions/codex-check.yml](../examples/github-actions/codex-check.yml).

## Action inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `codex_path` | `codex` | Codex root, entries directory, or single entry JSON file. |
| `verified_only` | `false` | Fail unless every entry has `status=verified`. |
| `require_receipts` | `false` | Fail unless every entry has receipt or attestation metadata. |
| `require_signed_receipts` | `false` | Fail unless every entry includes signed receipt attestation metadata. |
| `fail_on_stale` | `false` | Fail on stale, deprecated, failed, or incompatible entries. |
| `fail_on_high_risk` | `false` | Fail on high or critical risk entries. |
| `banned_commands_file` | empty | Optional newline-delimited regex/pattern file for organization-specific banned commands. |
| `hmac_key` | empty | Optional HMAC key for validating `hmac-sha256` signed attestations during `codex lint` and `codex verify`. |

For signed receipts, pass key material from GitHub Secrets:

```yaml
with:
  codex_path: codex
  require_signed_receipts: "true"
  hmac_key: ${{ secrets.HOWDEX_CODEX_HMAC_KEY }}
```

Do not print verifier keys or raw receipt payloads in logs.

## GitLab CI equivalent

The same checks work in GitLab CI without the GitHub composite action:

```yaml
codex-check:
  image: python:3.12
  script:
    - python -m pip install --upgrade pip
    - python -m pip install -e ".[dev]"
    - howdex codex lint codex
    - howdex codex policy-check codex
    - howdex codex verify codex
```

To require stronger controls:

```yaml
codex-check-strict:
  image: python:3.12
  script:
    - python -m pip install --upgrade pip
    - python -m pip install -e ".[dev]"
    - howdex codex lint codex --hmac-key "$HOWDEX_CODEX_HMAC_KEY"
    - howdex codex policy-check codex
    - howdex codex verify codex --hmac-key "$HOWDEX_CODEX_HMAC_KEY"
```

## Fail on unsafe procedures

Use CI inputs or equivalent shell checks to fail when:

- high-risk entries lack approval metadata;
- stale, deprecated, failed, or incompatible entries are present;
- banned command patterns appear;
- source code or source markers appear in entries that exclude source artifacts;
- verified entries lack receipt metadata;
- signed-verified entries lack valid signed attestation evidence.

The built-in policy floor blocks obvious destructive patterns such as `rm -rf /`,
`sudo rm`, `curl | sh`, `wget | sh`, and unapproved destructive Docker or
Kubernetes commands.

## Require signed receipts

Signed receipts are stronger than ordinary observed evidence. To require them in
GitHub Actions:

```yaml
with:
  require_receipts: "true"
  require_signed_receipts: "true"
  hmac_key: ${{ secrets.HOWDEX_CODEX_HMAC_KEY }}
```

This does not make Howdex a hosted trust service. CI verifies local JSON
attestation metadata using key material you supply.

## Review candidate entries

Candidate entries can be useful operational memory, but they are not proof. A
good review should check:

- what trace or benchmark produced the entry;
- whether `learned_facts` are operational guidance rather than source code;
- whether `avoid` captures failed attempts or known traps;
- whether policy constraints match the target environment;
- whether verification metadata is specific enough to rerun;
- whether receipts or signed attestations exist before promotion.

CI should block unsafe entries, but human review still decides whether a
candidate procedure belongs in a shared Codex.
