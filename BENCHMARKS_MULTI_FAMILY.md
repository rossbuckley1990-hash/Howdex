# Howdex Multi-Family SWE-Repeat Benchmark

This report covers the multi-family SWE-repeat benchmark.

## Summary

- Families: 3
- Configured tasks: 9
- Eligible tasks: 9
- Passed tasks: 9
- Failed tasks: 0

## Task results

| Family | Repo | Result | Reason |
|---|---|---:|---|
| `node_export_broken` | `is-number` | PASS | `passed` |
| `node_export_broken` | `kind-of` | PASS | `passed` |
| `node_export_broken` | `is-primitive` | PASS | `passed` |
| `package_json_test_script_missing` | `is-number` | PASS | `passed` |
| `package_json_test_script_missing` | `kind-of` | PASS | `passed` |
| `package_json_test_script_missing` | `is-primitive` | PASS | `passed` |
| `json_config_syntax_broken` | `is-number` | PASS | `passed` |
| `json_config_syntax_broken` | `kind-of` | PASS | `passed` |
| `json_config_syntax_broken` | `is-primitive` | PASS | `passed` |

## Current claim

Howdex's multi-family SWE-repeat runner currently validates 9/9 configured real OSS repair tasks across 3 controlled fault families.

## Caveat

This is still not full SWE-bench. It is a controlled, repeatable SWE-style benchmark over real repositories, real installs, real test suites, injected faults, repairs, and reruns.
