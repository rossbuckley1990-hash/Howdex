# Dogfooding Howdex

Howdex is the open verification layer for agent know-how. It turns execution
traces into portable, receipt-backed procedures that any agent can reuse and
any enterprise can audit.

Howdex should build Howdex.

The dogfood harness records the execution traces used to implement Howdex
roadmap phases, learns a procedure from each phase, publishes a local candidate
Codex entry, optionally attaches verifier evidence, and writes sanitized metric
summaries automatically. Ross should not manually maintain a CSV.

This is local-only. It does not require OpenAI, Docker, a hosted registry, or a
cloud service.

Dogfood metrics are internal build evidence only. Dogfood metrics are not
external adoption, traction, users, revenue, market validation, or proof that a
procedure generalizes broadly.

Dogfood entries are part of the internal procedural-memory loop. They can
produce candidate procedures and internal receipts, but they should not be
presented as external adoption or broad proof of compounding at scale.

## Why this exists

Howdex is verified agent procedure infrastructure. The strongest way to improve
that infrastructure is to use it as part of its own build loop:

1. capture a roadmap phase execution trace;
2. capture command logs and test outcomes;
3. learn a reusable procedure from the trace;
4. publish a candidate Codex entry;
5. attach verification evidence when a local verifier passed;
6. render guidance for the next similar phase.

The goal is not to pretend every phase is automatically solved. The goal is to
make the build process observable, repeatable, and reusable.

## Start a phase

```bash
python scripts/howdex_dogfood.py start \
  --phase "phase-8-live-trust-calibration" \
  --objective "Run live procedure trust calibration from actual dogfood traces"
```

This writes:

```text
.howdex/dogfood/current.json
```

The state file records:

- phase and objective;
- start timestamp;
- current branch;
- `git_start_sha`;
- clean/dirty state;
- Python version;
- Howdex version;
- active database path;
- dogfood state path.

## Save guidance

```bash
python scripts/howdex_dogfood.py guidance \
  --objective "Run live procedure trust calibration from actual dogfood traces" \
  --save
```

This renders native Howdex guidance with source artifacts excluded by default,
saves it to:

```text
.howdex/dogfood/guidance/<phase>.md
```

and records:

- `guidance_used=true`;
- guidance character count;
- selected procedure ids.

## Run commands under dogfood tracing

```bash
python scripts/howdex_dogfood.py run \
  --label "pytest" \
  -- PATH="$PWD/.venv/bin:$PATH" python -m pytest
```

The command runner captures:

- command label;
- redacted command string;
- exit code;
- duration;
- pass/fail;
- pytest summary when detected, for example `486 passed`;
- a redacted command log under `.howdex/dogfood/runs/<phase>/`;
- a Howdex step in the active phase trace.

Failed commands automatically increment `failed_attempts`.

Raw dogfood logs are local operational artifacts and should not be committed by
default. The committed evidence path is the sanitized summary under
`dogfood-results/`.

## End a phase automatically

```bash
python scripts/howdex_dogfood.py end --auto
```

Auto-end performs the dogfood closeout:

- replays the active state into Howdex episodic memory;
- runs `learn(min_samples=1)`;
- publishes candidate Codex entries to `.howdex/dogfood/codex`;
- attaches a receipt when the latest pytest/test-labelled command passed;
- records `git_end_sha`;
- records git diff stat and changed files;
- records commit count since `git_start_sha` when available;
- writes `dogfood-results/<phase>/summary.json`;
- appends one row to `dogfood-results/metrics.csv`;
- clears `.howdex/dogfood/current.json`.

The support count in dogfood metrics is intentionally conservative:
procedures learned from one build phase are recorded as `support_count=1`.
That means single-episode, single-repo, single-user dogfood procedures are
useful internal evidence, but they are not proof of broad generalization.

## Status and abort

Check the active phase:

```bash
python scripts/howdex_dogfood.py status
```

Abort safely:

```bash
python scripts/howdex_dogfood.py abort --reason "starting again"
```

By default, abort clears only active state and preserves local logs. To remove
local run logs for the phase:

```bash
python scripts/howdex_dogfood.py abort --reason "starting again" --delete-logs
```

## What is local only

These paths are local runtime artifacts:

```text
.howdex/dogfood/current.json
.howdex/dogfood/howdex.db
.howdex/dogfood/runs/
.howdex/dogfood/guidance/
.howdex/dogfood/codex/
```

They can be useful while operating the loop, but raw logs and local databases
should remain local unless intentionally reviewed and committed.

## What is safe to commit

The intended sanitized evidence path is:

```text
dogfood-results/<phase>/summary.json
dogfood-results/metrics.csv
```

Summaries are redacted and do not include raw stdout, stderr, source artifacts,
or secret-looking values by default.

## Receipts and Codex entries

Dogfood procedures publish as candidate Codex entries. Candidate entries are
useful operational memory, but they are not verified proof.

When a local verifier command passes, the harness attaches a Howdex receipt to
the learned procedure. That receipt is internal evidence for the dogfood phase;
it should not be described as external validation.

## How this supports compounding

Each completed phase can produce:

- an execution trace;
- a command log;
- a test receipt;
- a learned procedure;
- a candidate Codex entry;
- a sanitized dogfood metric summary;
- reusable guidance for the next phase.

That supports the compounding story by making Howdex's own build loop
inspectable. It does not, by itself, prove external adoption or broad
cross-team generalization.
