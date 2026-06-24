# AWM-style head-to-head harness

This directory contains a benchmark harness for comparing three conditions:

1. `vanilla`: no procedural memory.
2. `awm_style`: a local AWM-style workflow-memory approximation.
3. `howdex`: deterministic Howdex procedure extraction plus verified guidance.

This is a harness, not a victory claim.

The `awm_style` condition is not an official AWM implementation. It is a local
approximation that extracts a freeform workflow summary from successful traces
and injects that summary into later tasks. A real AWM implementation should be
integrated later if available.

Do not claim that Howdex beats AWM from this harness alone.

## Run dry-run mode

```bash
python -m benchmarks.awm_head_to_head.runner --dry-run
```

Dry-run mode requires no OpenAI, Docker, external benchmark datasets, or
network. It validates:

- comparable output schema across conditions;
- identical base task framing;
- memory strategy isolation;
- source leakage checks;
- auditability scoring;
- verification/calibration/portability metrics.

The dry-run success numbers are deterministic harness checks, not live model
results.

## Run live-local mode

```bash
python -m benchmarks.awm_head_to_head.runner --task docker --trials 20 --live-local
```

Until a real AWM baseline or explicit local evaluator is integrated, live-local
mode reports `SKIP` rather than fabricating results.

## Metrics

Each condition reports:

- success rate;
- average attempts;
- extraction cost;
- guidance characters;
- source leakage;
- auditability score;
- verification coverage;
- calibration coverage;
- portability score.

## Framing rule

All conditions must share identical base task framing. Only the memory strategy
may differ.

The runner enforces this by hashing the base prompt for every condition.

## Result schema

Machine-readable output follows `results_schema.json`.

## Claim boundary

Allowed:

- “This harness compares vanilla, a local AWM-style approximation, and Howdex.”
- “The dry-run validates benchmark plumbing and metric calculation.”
- “The AWM-style baseline is local and approximate until a real AWM integration
  is added.”

Forbidden:

- “Howdex beats AWM.”
- “Howdex beats AWM on live tasks.”
- “The local AWM-style approximation is the official AWM implementation.”
- “Dry-run metrics prove field performance.”
