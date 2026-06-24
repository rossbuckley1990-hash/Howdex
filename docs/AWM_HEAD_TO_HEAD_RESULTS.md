# AWM head-to-head result note

Howdex is the open verification layer for agent know-how. It turns execution
traces into portable, receipt-backed procedures that any agent can reuse and
any enterprise can audit.

This document records the current reproducible output from the local
AWM-style head-to-head harness.

## Exact command

```bash
PATH="$PWD/.venv/bin:$PATH" python -m benchmarks.awm_head_to_head.runner --dry-run --trials 5
```

## Conditions

- `vanilla`: no workflow or procedural memory.
- `awm_style`: local AWM-style workflow-memory summary approximation.
- `howdex`: Howdex deterministic procedure extraction plus verified guidance.

## Results

| condition | trials | successes | success rate | avg attempts | source leakage | auditability score | verification coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vanilla` | 5 | 1 | 0.20 | 7.60 | 0 | 0.00 | 0.00 |
| `awm_style` | 5 | 3 | 0.60 | 5.20 | 0 | 0.30 | 0.00 |
| `howdex` | 5 | 4 | 0.80 | 3.60 | 0 | 1.00 | 1.00 |

Additional dry-run metrics from the same command:

| condition | extraction cost | guidance chars | calibration coverage | portability score | verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `vanilla` | 0.00 | 38 | 0.00 | 0.00 | DRY-RUN BASELINE |
| `awm_style` | 1.00 | 432 | 0.00 | 0.30 | DRY-RUN APPROXIMATION |
| `howdex` | 0.00 | 1060 | 1.00 | 1.00 | DRY-RUN HOWDEX CONDITION |

## AWM-style baseline status

The `awm_style` condition is a local approximation, not a real AWM implementation. It models an AWM-style workflow-memory baseline by extracting a
freeform workflow summary from successful traces and injecting that summary into
later tasks.

This is a local AWM-style approximation unless explicitly stated otherwise. It is not a claim that Howdex has beaten the AWM paper or public WebArena/Mind2Web baselines.

## Caveats

- These are dry-run harness numbers. They validate condition wiring, metric
  calculation, identical base framing, source-leakage detection, and result
  schema shape.
- This run does not call OpenAI, Docker, external benchmark datasets, or a real
  AWM implementation.
- The dry-run success rates are deterministic harness checks, not live model
  performance.
- Source leakage was `0` under the local marker-based detector. That is useful
  hygiene evidence, not a complete privacy or security proof.
- Verification coverage is higher for `howdex` because the Howdex condition is
  receipt-backed in the harness. It does not mean every real-world Howdex
  procedure is verified.
- A live comparison against a real AWM implementation, WebArena, or Mind2Web
  baseline has not been recorded here.
