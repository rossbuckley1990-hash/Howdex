# Howdex vs Mem0 Procedural Memory Comparison

This benchmark compares context retrieval against procedural reuse.

## Summary

- tasks: 9
- mem0_available: True
- mem0_error: None
- howdex_procedure_reuse: 9
- mem0_context_retrieval: 0
- mem0_add_error: None
- mem0_search_error: None
- no_memory_procedure_matches: 0
- mem0_procedure_matches: 0
- howdex_procedure_matches: 9

## Results

| Family | Repo | Mem0 retrieved context | Howdex used procedure | Howdex matched procedure |
|---|---|---:|---:|---:|
| `node_export_broken` | `is-number` | False | True | True |
| `node_export_broken` | `kind-of` | False | True | True |
| `node_export_broken` | `is-primitive` | False | True | True |
| `package_json_test_script_missing` | `is-number` | False | True | True |
| `package_json_test_script_missing` | `kind-of` | False | True | True |
| `package_json_test_script_missing` | `is-primitive` | False | True | True |
| `json_config_syntax_broken` | `is-number` | False | True | True |
| `json_config_syntax_broken` | `kind-of` | False | True | True |
| `json_config_syntax_broken` | `is-primitive` | False | True | True |

## Interpretation

This benchmark compares context retrieval against procedural reuse. Mem0 is credited when it retrieves prior context. Howdex is credited when it loads and applies a learned procedure.

## Caveat

This is a procedural-memory comparison, not a general long-term-memory benchmark. Mem0 should also be evaluated on its own strongest use cases: personalization, user preference recall, and long-session context continuity.
