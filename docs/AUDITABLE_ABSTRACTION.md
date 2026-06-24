# Auditable abstraction

Howdex is deterministic by default. The core learning path canonicalizes traces,
parameterizes volatile values, consolidates evidence, and tracks verification
receipts without mandatory LLM calls.

Optional LLM-assisted abstraction exists for one narrow reason: two procedures
can be semantically equivalent even when their traces are worded differently or
their deterministic templates do not line up cleanly. An LLM can help propose
that equivalence, but its output is never silently promoted into trusted
memory.

LLM output is never silently promoted into trusted memory.

## Trust boundary

An LLM may propose:

- a shared canonical task;
- why two or more procedures appear equivalent;
- a parameter mapping;
- shared preconditions;
- a proposed verifier.

An LLM may not:

- mark a procedure verified;
- attach or fabricate verification receipts;
- delete source procedures;
- publish a verified Codex entry;
- bypass policy, staleness, or receipt checks;
- include source artifacts by default.

Accepted abstraction proposals create candidate memory only. Candidate memory
must still be verified by an inspectable receipt before it can become a verified
procedure or verified Codex entry.

## Auditability

Every `AbstractionProposal` records:

- source procedure IDs;
- proposed canonical task;
- proposed equivalence reason;
- proposed parameter mapping;
- proposed shared preconditions;
- proposed shared verifier;
- model name;
- prompt hash;
- response hash;
- creation timestamp;
- status;
- reviewer;
- audit log.

The prompt and response hashes make the proposal inspectable without storing raw
source artifacts in the proposal by default. The audit log records creation,
acceptance, rejection, and reviewer context.

## Reversible proposals

Proposals do not mutate or delete source procedures. Rejection preserves the
proposal and reason. Acceptance creates a new candidate abstraction linked back
to the source procedure IDs.

That makes review reversible: teams can inspect what was proposed, who accepted
or rejected it, and which original procedures remain available.

## Relation to AWM-style generalization

AWM-style workflow memory aims to generalize across successful workflows.
Howdex keeps that idea behind an audit boundary:

- deterministic extraction remains the trusted path;
- LLM abstraction is optional;
- LLM output is proposal-only;
- accepted abstractions stay candidate until verified;
- publication as verified requires receipts.

This lets teams experiment with broader semantic generalization without turning
model guesses into unreviewed operational memory.

## Dry-run mode

`propose_abstraction(..., dry_run=True)` requires no OpenAI, no cloud service,
and no model dependency. It creates a deterministic rule-based proposal useful
for tests, local review workflows, and CI validation of the audit mechanics.

## Minimal example

```python
from howdex.abstraction import (
    accept_abstraction,
    propose_abstraction,
)

proposal = propose_abstraction([procedure_a, procedure_b], dry_run=True)

# Human or deterministic policy review decides whether the proposal is useful.
candidate = accept_abstraction(proposal.proposal_id, reviewer="ops-review")

assert candidate["status"] == "candidate"
assert candidate["procedure_status"] == "unverified"
```

The candidate is not verified. It becomes verified only after a task-relevant
verifier succeeds and a valid receipt is attached.
