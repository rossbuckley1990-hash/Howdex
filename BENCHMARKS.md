# Howdex Benchmarks

## SWE-repeat benchmark

Howdex is evaluated against no-memory and vector-only baselines on eligible real OSS npm test suites.

The benchmark uses:

- real cloned OSS repositories
- real `npm install`
- real clean `npm test`
- controlled source-code fault injection
- real failing `npm test`
- real repair
- real rerun of `npm test`
- baseline comparison

## Current result

Howdex reduced repeated unsafe test failures by **50%** versus the no-memory baseline.

| Agent | Success rate | Unsafe test failures | Repeated unsafe failures | Avg actions |
|---|---:|---:|---:|---:|
| `no_memory` | 100% | 3 | 2 | 5.00 |
| `vector_only` | 100% | 3 | 2 | 5.00 |
| `howdex_procedural` | 100% | 2 | 1 | 5.67 |

## Eligible repositories

- `is-number`
- `kind-of`
- `is-primitive`

## Learned procedures

### repair node package source code after failing npm test

1. `check_target_file`
2. `fix_target_file`
3. `run_tests`

## Honest caveat

This is not full SWE-bench. It is a smaller, repeatable, local SWE-style benchmark proving the core Howdex thesis:

> Same agent. Same repos. Same tests. Same fault family. Howdex helped it stop failing the same way twice.
