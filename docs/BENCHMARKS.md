# Howdex Benchmarks

Howdex benchmarks are meant to test procedural memory, not model capability in
the abstract. The central question is whether a verified execution trace can be
turned into reusable operational guidance for a fresh agent without pasting
source or changing the base task framing.

## Headline Docker recovery A/B n20

Source of truth: committed log
`evidence/docker_n20/docker_hard_ab_n20_20260623_172737.txt`.

Reproduction command:

```bash
make bench-docker-n20
```

Equivalent command:

```bash
HOWDEX_DOCKER_TRIALS=20 HOWDEX_DOCKER_MAX_TURNS=15 python3 real_docker_recovery_ab_test.py
```

The benchmark uses a fresh broken local Docker Compose runtime. The teacher
discovers and verifies the recovery. The control arm gets no prior memory. The
treatment arm gets Howdex operational memory. The benchmark framing is:
identical base prompt; only learned memory differs.

| Metric | Control | Treatment |
|---|---:|---:|
| n per arm | 20 | 20 |
| successes | 7 | 18 |
| success rate | 0.35 | 0.90 |
| avg_attempts | 13.00 | 8.75 |
| memory_used | 0/20 | 20/20 |
| source_pasted | 0/20 | 0/20 |

Logged deltas:

- success rate lift: `+0.55`
- attempt reduction: `+4.25`
- verdict: `PASS`

Logged verdict text:

> Howdex transferred a verified local Docker recovery procedure without pasting source.

## What this proves

This demonstrates one verified procedure transferring to fresh agents. It shows
that Howdex can turn a successful Docker recovery trace into operational
guidance that improves treatment performance under the logged benchmark
conditions.

## What it does not prove yet

This does not yet prove compounding over many accumulated traces. It also does
not claim production-safe autonomous execution, universal task memory, or that
all Codex entries are verified.

It also does not prove live cross-model transfer, does not compare against the
AWM paper or public WebArena/Mind2Web baselines, and does not show that
dry-run harness results predict live performance.

## Additional local benchmark evidence

These benchmarks are useful engineering evidence, but they have narrower claim
boundaries than the headline Docker n20 result.

### Real MacGyver filesystem artifact replay

File:

```text
real_macgyver_test.py
```

What it tests:

- real temporary filesystem;
- generated `custom_parser.py`;
- real data files;
- subprocess execution;
- deletion of the teacher's parser before the student run;
- student re-creation from Howdex memory.

Claim boundary:

```text
Artifact replay regression test. Not yet a no-memory capability-lift test.
```

Run:

```bash
python3 real_macgyver_test.py
```

### Real MacGyver A/B hard-tool benchmark

File:

```text
real_macgyver_ab_test.py
```

Representative local result previously recorded:

| Metric | Control | Treatment |
|---|---:|---:|
| trials | 5 | 5 |
| successes | 2 | 5 |
| success rate | 0.40 | 1.00 |
| avg attempts | 7.20 | 2.60 |
| Howdex memory used | 0/5 | 5/5 |
| source pasted | 0/5 | 0/5 |

Run:

```bash
HOWDEX_AB_TRIALS=5 HOWDEX_AB_MAX_TURNS=20 python3 real_macgyver_ab_test.py
```

Claim boundary:

```text
Local A/B benchmark evidence for one hard filesystem/tool-reuse task family.
Not a production-safety claim.
```

### Polyglot MacGyver crypto transfer benchmark

File:

```text
polyglot_macgyver_test.py
```

Representative local result previously recorded:

| Metric | Control | Treatment |
|---|---:|---:|
| trials | 5 | 5 |
| successes | 0 | 5 |
| success rate | 0.00 | 1.00 |
| avg attempts | 11.00 | 3.60 |
| Howdex memory used | 0/5 | 5/5 |
| source pasted | 0/5 | 0/5 |

Run:

```bash
HOWDEX_POLY_TRIALS=5 HOWDEX_POLY_MAX_TURNS=12 python3 polyglot_macgyver_test.py
```

Claim boundary:

```text
Language-agnostic operational transfer using synthesized Howdex memory facts.
Not proof that no-synthesis abstraction is solved.
```

### AWM-style head-to-head harness

Result doc:

```text
evidence/awm_head_to_head/AWM_HEAD_TO_HEAD_RESULTS.md
```

The current AWM-style result is a dry-run harness output. It compares vanilla,
a local AWM-style workflow-memory approximation, and Howdex's deterministic
procedure guidance path.

Required caveat:

```text
This is a local AWM-style approximation unless explicitly stated otherwise. It is not a claim that Howdex has beaten the AWM paper or public WebArena/Mind2Web baselines.
```

### Trust calibration

Result doc:

```text
evidence/trust_calibration/TRUST_CALIBRATION_RESULTS.md
```

The current dogfood trust-calibration result is internal evidence only and
reported `INSUFFICIENT DATA`. It validates the harness path, not external
calibration.

## Prerequisites

- Docker must be running.
- `python:3.12-alpine` must already be present locally.
- `OPENAI_API_KEY` must be set for the live model calls.
- The benchmark does not auto-pull Docker images.
