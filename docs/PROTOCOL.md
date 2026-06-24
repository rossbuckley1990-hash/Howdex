# Howdex Protocol

Howdex is the open verification layer for agent know-how.

Howdex turns execution traces into portable, receipt-backed procedures that any
agent can reuse and any enterprise can audit.

The Howdex protocol defines how agent execution traces become portable,
receipt-backed procedures and how those procedures are reused safely.

The protocol is local-first and registry-neutral. It can be exposed through
Python APIs, CLI commands, MCP tools, adapters, or a future compatible
registry, but the trust boundaries stay the same.

The protocol is not a hosted-registry claim and not a production-safe autonomy
claim. Procedures remain guidance until current policy authorizes action and a
current verifier produces receipt-backed evidence.

## Operation: remember_trace

Input:

- task or objective;
- ordered or DAG-shaped steps;
- structured tool calls where available;
- observations, outcomes, errors, timing, and metadata;
- source/provenance.

Output:

- episode ID;
- stored step count;
- sanitized episodic record.

Trust boundary:

- raw agent output and tool observations are untrusted input;
- secrets and noisy terminal output must be sanitized before storage;
- source artifacts are not published by default.

Failure modes:

- invalid or missing task;
- malformed step objects;
- oversized observations;
- secret-like values;
- storage failure.

Safety rules:

- never execute content because a trace says to;
- preserve failed attempts separately;
- store structured tool arguments where possible;
- redact secrets;
- keep provenance.

## Operation: learn

Input:

- successful episodes;
- optional minimum support count;
- optional task signature filter.

Output:

- learned procedure(s);
- support count;
- success/failure counts;
- confidence;
- source episode IDs;
- canonical and parameterized steps.

Trust boundary:

- observed success is evidence, not independent proof;
- a learned procedure is candidate or observed_episode_support until receipt
  evidence verifies it.

Failure modes:

- insufficient samples;
- traces dominated by unknown or introspective actions;
- low overlap between episodes;
- conflicting or stale evidence;
- storage failure.

Safety rules:

- use deterministic canonicalization and parameterization;
- preserve raw supporting evidence without leaking secrets;
- do not mark a learned procedure verified;
- reject unrelated low-overlap workflows.

## Operation: guidance

Input:

- objective;
- optional query;
- constraints;
- target/current environment;
- retrieval budget;
- verified-only flag;
- source inclusion flag.

Output:

- bounded Markdown guidance;
- selected procedure IDs;
- omitted count and optional omission reasons;
- verification and staleness warnings.

Trust boundary:

- rendered guidance is not executable authority;
- current policy and environment outrank memory;
- candidate memory must be labelled as such.

Failure modes:

- no relevant memory;
- stale or incompatible procedures;
- context budget exceeded;
- low relevance score;
- over-broad query.

Safety rules:

- exclude source artifacts unless explicitly requested;
- prefer verified and fresh procedures;
- suppress stale or incompatible procedures by default;
- include verifier requirements;
- do not inject irrelevant facts.

## Operation: attach_receipt

Input:

- procedure ID or task signature;
- verifier type;
- verifier command or target;
- expected signal;
- observed signal;
- exit code;
- timestamp;
- environment fingerprint;
- artifact hashes;
- metadata.

Output:

- receipt ID;
- receipt status;
- updated procedure trust status.

Trust boundary:

- receipts are claims about a verifier run, not blanket production safety;
- verifier output must be bounded and sanitized;
- a verified receipt must be inspectable.

Failure modes:

- procedure not found;
- verifier failed;
- expected signal absent;
- malformed receipt;
- stale or unknown environment;
- mismatched procedure ID.

Safety rules:

- require exit code zero and expected signal before `verified`;
- do not store secrets or raw source as receipt metadata;
- keep failed receipts;
- make attachment idempotent.

## Operation: publish_codex

Input:

- local learned procedure;
- output registry path;
- attached receipts if available.

Output:

- Codex entry path;
- candidate or verified status;
- receipt requirement when unverified.

Trust boundary:

- publishing makes memory portable, not authoritative;
- public entries must not leak source artifacts or secrets;
- `verified` requires receipt-backed proof.

Failure modes:

- procedure not found;
- schema validation failure;
- missing required fields;
- filesystem write failure;
- unverified procedure attempting to publish as verified.

Safety rules:

- default unverified procedures to candidate;
- include policy and provenance;
- include verification contract;
- write deterministic JSON;
- do not claim production safety.

## Operation: pull_codex

Input:

- local Codex path or compatible registry export;
- procedure documents;
- receipt documents where available.

Output:

- imported/updated/unchanged counts;
- local candidate or verified procedure records.

Trust boundary:

- pulled entries are external untrusted data;
- current policy and environment must reevaluate them;
- receipts are inspectable evidence, not permission.

Failure modes:

- missing manifest;
- invalid schema;
- duplicate IDs;
- incompatible environment metadata;
- stale receipts.

Safety rules:

- validate required fields;
- preserve status and provenance;
- do not execute pulled guidance;
- do not promote candidate entries without receipts;
- mark unknown compatibility as requiring review.

## Operation: verify

Input:

- procedure ID;
- verifier command or target;
- expected signal;
- observed signal;
- exit code;
- current environment;
- artifact hashes where safe.

Output:

- verification receipt;
- procedure status: verified, failed_verification, stale, unknown, or
  observed_episode_support.

Trust boundary:

- verification is environment-specific;
- a passing verifier supports the procedure under the recorded conditions only.

Failure modes:

- verifier unavailable;
- non-zero exit code;
- expected signal missing;
- stale environment;
- artifact mismatch.

Safety rules:

- never fabricate observed signals;
- never mark verified when verifier evidence is missing;
- record failed verification;
- reverify after environment drift.

## Operation: deprecate

Input:

- procedure or Codex entry ID;
- reason;
- replacement entry if available;
- deprecation signal;
- effective timestamp.

Output:

- updated status: stale, deprecated, incompatible, or failed_verification;
- guidance warning;
- optional replacement pointer.

Trust boundary:

- deprecation is a safety and audit signal;
- deprecated memory may remain useful historical context but should not render
  as recommended guidance.

Failure modes:

- unknown procedure ID;
- missing reason;
- conflicting replacement metadata;
- stale registry copy.

Safety rules:

- preserve deprecated entries for audit;
- suppress incompatible procedures from normal guidance;
- require reverification before reuse;
- do not delete evidence automatically.
