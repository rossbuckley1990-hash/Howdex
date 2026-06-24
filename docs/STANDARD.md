# Howdex Procedure Standard

Howdex formalises a portable, receipt-backed primitive for agent know-how:
the verified agent procedure.

The category is Verified Agent Procedure Infrastructure. The standard is
designed so a procedure learned in one model, framework, or cloud can be
inspected, rendered, reverified, and reused elsewhere without pretending that
memory is authority.

No proof, no verified procedure.

## What a Howdex Procedure is

A Howdex Procedure is a machine-readable operational memory object. It records
how an agent completed a task and what evidence supports that procedure.

A procedure is:

- learned from execution traces;
- derived from one or more episodes;
- normalized into reusable steps;
- rendered as operational guidance;
- linked to source episodes and supporting examples;
- governed by policy and compatibility metadata;
- optionally backed by verification receipts;
- portable across models, agents, frameworks, and clouds.

The useful unit is not a prompt and not a transcript. It is a reusable
procedure with provenance, status, and verification boundaries.

## What a Howdex Procedure is not

A Howdex Procedure is not:

- executable authority;
- permission to run a tool;
- proof that an action is safe in the current environment;
- pasted source code;
- a model-specific prompt template;
- a hidden chain-of-thought transcript;
- a universal memory claim;
- a production-safety guarantee.

Procedures guide agents. Current policy, sandboxing, approval, and verification
still govern execution.

## Procedure lifecycle

```text
trace
  -> episode
  -> learned procedure
  -> candidate Codex entry
  -> verified procedure
  -> stale/deprecated procedure
```

1. `trace`: raw agent/tool execution evidence, including attempts, failures,
   observations, structured tool calls, and verifier output.
2. `episode`: a persisted task-bounded record with session metadata, steps,
   outcome, timing, and provenance.
3. `learned procedure`: deterministic consolidation of successful episodes into
   reusable canonical and parameterized steps.
4. `candidate Codex entry`: portable public or private entry that is useful
   guidance but not proof.
5. `verified procedure`: a candidate plus inspectable verification receipt(s)
   showing a real verifier succeeded.
6. `stale/deprecated procedure`: a procedure whose environment, version,
   verifier, policy, or compatibility metadata requires review or replacement.

## Required procedure fields

A portable Howdex Procedure should include:

- `id`: stable procedure identifier.
- `title` or `task_signature`: human-readable task identity.
- `version`: version of the entry or procedure document.
- `category`: operational domain such as docker, package-manager, filesystem,
  crypto, build, test, deployment, or other.
- `status`: candidate, experimental, verified, stale, deprecated, or
  failed_verification.
- `steps`: reusable canonical or parameterized operational steps.
- `learned_facts`: compact operational facts rendered into guidance.
- `avoid`: failed attempts, unsafe approaches, or known traps.
- `verification`: verifier contract and receipt summary.
- `policy`: reuse and execution constraints.
- `provenance`: source episodes, source system, and limitations.
- `risk_level`: expected operational risk.
- `tags`: searchable tags.
- `created_at` and `updated_at` where available.
- `source_episode_ids` where available.
- `confidence`, `support_count`, and success/failure counts where available.

The schema may evolve, but a procedure must remain inspectable: an agent or
reviewer should be able to understand why it exists, where it came from, how it
should be verified, and what it must not authorize.

## Required receipt fields

A verification receipt should include:

- `receipt_id`: stable receipt identifier.
- `procedure_id` or `task_signature`: what the receipt verifies.
- `verifier_type`: test, build, bootproof, health-check, custom, or other.
- `verifier_command`: verifier target or command, without secrets.
- `expected_signal`: what success should prove.
- `observed_signal`: bounded observed result, without source or secrets.
- `exit_code`: verifier exit status.
- `verified_at`: timestamp.
- `environment` or `environment_fingerprint`: runtime, OS, tool, dependency,
  policy, or sandbox context.
- `artifact_hashes`: hashes of relevant artifacts where safe.
- `source_episode_id`: episode that produced the receipt where available.
- `status`: verified, failed, stale, or unknown.
- `metadata`: bounded extension data.

Receipts must be inspectable and defensively stored. A claim that an agent
"finished" is not enough.

## Candidate vs verified status

Candidate procedures are useful memory. They may reflect repeated successful
episodes or a single observed support trace, but they are not trusted proof.

Verified procedures require at least one inspectable receipt showing that a
task-relevant verifier passed. `status=verified` must not be emitted merely
because an agent said the task was complete.

Failed, stale, or unknown receipts must remain visible. They should lower
confidence or require review rather than being overwritten by newer optimism.

## Policy metadata

Policy metadata defines how a procedure may be reused. It should capture:

- allowed uses;
- forbidden uses;
- required approvals;
- source artifact policy;
- sandbox or perimeter constraints;
- side-effect and risk boundaries;
- human-review requirements;
- organization or team policy notes.

Consumers must intersect procedure policy with current runtime policy. The
stricter rule wins.

## Staleness metadata

Staleness metadata protects agents from reusing old know-how under changed
conditions. It should include where relevant:

- ecosystem;
- package, framework, service, or tool name;
- version range;
- tested versions;
- last verified timestamp;
- stale-after window;
- deprecation signals;
- known incompatible versions.

Fresh procedures may render normally. Warning, unknown, stale, and incompatible
procedures must render with review or reverification requirements. Incompatible
procedures should be treated as blocked or historical memory, not recommended
guidance.

## Source artifact exclusion rules

Source artifacts are excluded by default.

A Howdex Procedure should carry operational memory: facts, steps, bindings,
failed attempts, policy, provenance, and verification. It should not publish
raw source code, secrets, private outputs, or copied implementation artifacts
unless an explicit policy allows it.

Reasons:

- avoids source leakage;
- avoids license ambiguity;
- avoids brittle source replay;
- keeps the procedure portable;
- forces agents to use current environment evidence;
- separates guidance from execution authority.

## Compatibility across agents, models, and frameworks

Procedures should be model-neutral and framework-neutral. A procedure learned
from a Claude, OpenAI Agents, LangGraph, CrewAI, AutoGen, MCP, or plain Python
agent loop should remain usable as a portable operational artifact.

Compatibility is achieved through:

- canonical and parameterized steps;
- structured tool-call evidence;
- JSON procedure and receipt schemas;
- policy and staleness metadata;
- source artifact exclusion by default;
- guidance rendering that can target many agent runtimes;
- verification receipts independent of the model that produced the trace.

## Guidance, not executable authority

A procedure can tell an agent what worked before. It cannot grant permission to
act now.

Agents and systems consuming procedures must still:

- check current objective and environment;
- apply local policy and approvals;
- respect sandbox constraints;
- bind placeholders to current resources;
- avoid known failed attempts;
- run the declared verifier;
- attach new receipts when verification succeeds or fails.

The standard’s safety line is simple: memory can guide; proof can verify;
policy can authorize. A procedure alone does not execute.
