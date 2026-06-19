# Howdex-SWE-Repeat-50

## Goal

Howdex-SWE-Repeat-50 is the benchmark target for proving Howdex as a serious agent-memory primitive.

The test asks:

> Can the same coding agent stop failing the same way twice across repeated real software-engineering task families?

## Target benchmark

- 50 tasks
- 10 bug families
- 5 tasks per family
- same agent
- same model
- same tool budget
- same verification command
- no-memory baseline
- vector-only memory baseline
- Howdex procedural memory baseline

## Required metrics

- pass rate
- repeated failed command reduction
- repeated unsafe failure reduction
- tool-call count
- time-to-green
- procedure reuse events
- cognitive leakage rate
- adversarial memory control failures

## Target result

A compelling public result would look like:

| Metric | No memory | Vector-only | Howdex procedural |
|---|---:|---:|---:|
| Pass rate | 28% | 30% | 42% |
| Repeated unsafe failures | 40 | 37 | 18 |
| Avg tool calls | 41 | 44 | 29 |
| Procedure reuse events | 0 | 0 | 32 |
| Cognitive leakage | n/a | n/a | 0 |
| Adversarial memory control failures | n/a | n/a | 0 |

## Public breakthrough line

Same agent. Same model. Same tests. Howdex made it stop failing the same way twice.

## Current status

The current SWE-repeat benchmark is a smaller precursor using eligible real OSS npm test suites and controlled source-code fault injection.

Current validated claim:

> Howdex reduced repeated unsafe test failures by 50% versus no-memory and vector-only baselines on eligible real OSS npm test suites after controlled source-code fault injection.

## Next expansion families

1. Node export broken
2. package.json test script missing
3. Python import/function renamed
4. pyproject build backend broken
5. CLI argument parsing regression
6. JSON config syntax broken
7. TypeScript export broken
8. environment variable validation failure
9. filesystem/path handling regression
10. dependency config mismatch
