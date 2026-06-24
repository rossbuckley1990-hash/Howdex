# Procedure trust calibration

Howdex is the open verification layer for agent know-how. It turns execution
traces into portable, receipt-backed procedures that any agent can reuse and
any enterprise can audit.

Procedure trust calibration asks a blunt question:

> Do Howdex confidence and verification states predict real held-out success?

Howdex becomes trust infrastructure only if its trust signals are predictive.
High-confidence or verified procedures should succeed more often than
candidate, stale, or failed-verification procedures.

Calibration is how Howdex checks whether its verification states and confidence
signals are predictive. Dry-run calibration validates machinery only; dogfood
calibration is internal evidence only until enough held-out real samples exist.

## Why calibration matters

Procedural memory is useful only when agents and operators know how much to
trust it. A learned procedure can be helpful, but a confidence score that does
not match reality is dangerous. Calibration measures whether predicted
confidence and verification states line up with observed outcomes.

The calibration harness reports:

- calibration bins from `0.0-0.2` through `0.8-1.0`;
- predicted mean confidence per bin;
- actual success rate per bin;
- count and absolute error per bin;
- an expected calibration error approximation;
- success rates by verification state;
- support-count distribution.

## What confidence means

Howdex confidence is a deterministic procedure-quality signal derived from
local evidence such as extraction confidence, support count, success count, and
feedback. It is not a model probability and it is not a guarantee.

Calibration treats confidence as a prediction to be tested against later
observed success.

## What verified means

`verified` means a procedure has inspectable verifier evidence: for example a
test command or health check whose observed signal matched the expected signal
with exit code zero.

Verification does not mean production-safe autonomous execution. It means a
specific verifier passed in a specific environment. Procedures remain guidance,
not executable authority.

## Modes

### Dry-run synthetic mode

```bash
HOWDEX_CALIBRATION_DRY_RUN=1 python procedure_trust_calibration_test.py
```

Dry-run mode creates deterministic synthetic samples to validate the benchmark
machinery. It requires no OpenAI, Docker, network, dogfood data, or live model
calls.

Allowed claim: the calibration harness runs and computes metrics.

Disallowed claim: Howdex is calibrated in the real world.

### Dogfood mode

```bash
HOWDEX_CALIBRATION_SOURCE=dogfood python procedure_trust_calibration_test.py
```

Dogfood mode reads existing local dogfood evidence:

```text
evidence/dogfood/results/*/summary.json
dogfood-results/*/summary.json
.howdex/dogfood/codex/procedures/*.json
```

Committed sanitized dogfood evidence lives under
`evidence/dogfood/results/`. The legacy `dogfood-results/` path remains
supported for local runtime output. The harness does not mutate dogfood state,
dogfood databases, Codex entries, receipts, or raw logs.

If there are too few dogfood samples, the harness reports:

```text
INSUFFICIENT DATA
```

Dogfood calibration is internal evidence only. It is not external adoption,
traction, users, market validation, or proof of broad generalization.

### Future external/live mode

A future external/live calibration mode should evaluate independently collected
held-out tasks across teams, environments, and procedure families. That mode
must still avoid fabricated results and must label the evidence source clearly.

## Output

The harness prints a human table:

```text
bin | predicted_mean | actual_success | count | error
```

It also prints a machine-readable JSON summary containing:

- `source`;
- `bins`;
- `verified_success_rate`;
- `candidate_success_rate`;
- `stale_success_rate`;
- `failed_verification_success_rate`;
- `calibration_error`;
- `support_count_distribution`;
- `sample_count`;
- `verdict`.

## Verdicts

- `DRY RUN PASS`: synthetic machinery validated; no live claim.
- `INSUFFICIENT DATA`: too few real or dogfood samples.
- `CALIBRATED`: enough held-out samples and calibration error below threshold.
- `MIS-CALIBRATED`: confidence materially overstates success or error is high.
- `DOGFOOD INTERNAL ONLY`: dogfood-derived evidence must stay internally scoped.

## Allowed claims

Allowed:

- “The dry-run calibration harness validates metric computation.”
- “Dogfood calibration currently has insufficient data.”
- “This dogfood result is internal evidence only.”
- “A future live run is required before making external calibration claims.”

Not allowed:

- “Howdex is calibrated” from dry-run data.
- “Dogfood metrics prove market adoption.”
- “A verified procedure is production-safe autonomous authority.”
- “Candidate procedures are verified without receipt evidence.”
