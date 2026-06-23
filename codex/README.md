# Howdex Codex

The Howdex Codex is a public, versioned catalogue of reusable operational
procedures learned from agent execution traces. Each entry describes what an
agent observed, what sequence proved useful, which failed paths should be
avoided, how success must be verified, and which policy constraints govern
reuse.

It is machine-readable operational memory for agents that do work.

## What it is not

The Codex is not a prompt library, a list of tips, a source-snippet collection,
or an instruction to execute commands blindly. Entries encode procedural
knowledge and evidence boundaries. They do not grant permission, bypass local
policy, or prove that a procedure is safe in a new environment.

## Why entries are open source

Operational memory benefits from the same public scrutiny as code and
protocols. Open entries make assumptions, failure modes, provenance, policy,
and verification requirements inspectable. They also let different agent
frameworks share a stable procedure format without depending on a hosted
service or proprietary model.

Open publication does not imply production readiness. Every consumer remains
responsible for evaluating an entry against its own environment and policy.

## Procedures and receipts

`schemas/procedure.schema.json` defines the catalogue entry. A procedure
contains:

- learned operational facts;
- failed approaches to avoid;
- a verification contract;
- a policy envelope;
- provenance and limitations;
- a versioned identity.

`schemas/receipt.schema.json` defines run-specific verification evidence. A
receipt records the verifier, expected and observed signals, exit status,
environment, timestamp, and artifact hashes. Receipts are separate from
procedures because one reusable procedure may be verified repeatedly in
different environments.

“No proof, no procedure.”

An entry without current proof must remain explicitly candidate or
experimental. A verified status requires attached, inspectable receipts. Even a
verified entry is guidance rather than executable authority.

## How entries are verified

Verification must use a real, task-relevant signal: a test suite, build result,
HTTP health response, decoded target, or another deterministic verifier.
Self-reported agent completion is not proof. The entry's `verification` object
states the required verifier and expected signal; individual executions can
produce receipts conforming to the receipt schema.

Verification is environment-specific. A receipt from one operating system,
runtime, dependency graph, or policy context does not automatically validate a
different one.

## Rendering entries into guidance

A Codex consumer can map an entry into Howdex's native guidance renderers:

1. Preserve the title, category, version, risk, provenance, and verification
   status.
2. Render `learned_facts` as ordered operational guidance.
3. Render `avoid` separately as known failed or unsafe approaches.
4. Render `verification` as the completion gate.
5. Apply `policy` before suggesting any concrete tool call.
6. Keep the output deterministic and bounded for prompt injection.

The rendered result should say what prior execution taught the agent while
making clear that current observations and verification take precedence.

## Source artifacts are excluded by default

Codex entries describe know-how, not copied implementations. Excluding source
artifacts reduces accidental code leakage, brittle replay, licensing ambiguity,
and the temptation to mistake a historical implementation for a portable
procedure. A future private registry may reference approved artifacts under an
explicit policy, but public entries should remain operational and
implementation-independent.

## Policy-aware reuse

The same procedure can be acceptable in one environment and prohibited in
another. Package installation may require registry approval. Docker recovery
may permit local Compose operations but prohibit image pulls or host mounts.
Decryption may be allowed for owned test fixtures but forbidden for unrelated
data.

Consumers must intersect an entry's `policy` with current agent, organization,
tool, and environment policy. The stricter rule wins. High-risk or ambiguous
actions should require review rather than being inferred as authorized.

## Using Codex entries

Future agents can:

- search entries by category, tags, risk, and task similarity;
- retrieve the best matching procedure before acting;
- bind placeholders to current files, packages, ports, or resources;
- render compact Howdex operational guidance;
- execute only policy-approved steps;
- run the declared verifier;
- attach a new receipt;
- record new failures and publish a versioned improvement.

An agent should never treat a match as an instruction to execute automatically.
Codex entries are operational memory, not executable authority.

