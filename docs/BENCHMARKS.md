# Howdex Benchmarks

Howdex benchmarks are meant to test procedural memory, not model capability in
the abstract. The central question is whether a verified execution trace can be
turned into reusable operational guidance for a fresh agent without pasting
source or changing the base task framing.

## Headline Docker recovery A/B n20

Source of truth: committed log
`benchmark_results/docker_hard_ab_n20_20260623_172737.txt`.

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

## Prerequisites

- Docker must be running.
- `python:3.12-alpine` must already be present locally.
- `OPENAI_API_KEY` must be set for the live model calls.
- The benchmark does not auto-pull Docker images.
