# Howdex vs Mem0 SWE-Repeat Comparison

This benchmark compares Howdex against Mem0 on repeated execution-failure repair tasks.

## Goal

Measure whether a memory system helps an agent avoid repeating the same failed execution path.

## Compared systems

1. `no_memory`
2. `mem0_context_memory`
3. `howdex_procedural_memory`

## Why this is fair

Mem0 is a strong persistent memory system for LLM applications and agents. It is commonly used for storing and retrieving durable context, preferences, facts, and relationships across sessions.

Howdex is designed around execution memory: episodes, actions, failures, and learned procedures.

This benchmark does not claim Mem0 is bad. It tests a narrower question:

> Does the memory layer convert prior execution traces into reusable procedures?

## Install optional Mem0 dependency

    python -m pip install mem0ai

Depending on configuration, Mem0 may require an LLM provider, embedder, vector store, or local service.

## Primary metric

Repeated unsafe failures.

An unsafe repeated failure is counted when an agent repeats a previously observed bad action sequence after memory should have helped it avoid that path.

## Expected interpretation

If Mem0 retrieves prior text but does not alter the action sequence, it is context memory.

If Howdex changes the action sequence by applying a learned procedure, it is procedural memory.
