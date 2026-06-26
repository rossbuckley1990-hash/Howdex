# Howdex Red-Team Harness — Operator Guide

Howdex ships an unusually strong defense surface for agent memory:
BootProof verifier gates, a Merkle audit ledger, a safety multiplier,
integrity warnings for hallucinated successes, an MCP path-traversal
guard, CRDT clock-checked deletes, and a trust calibration curve.

But defenses rot. New code paths get added, refactors break invariants,
and the only way to know the wall is still standing is to **try to break
it on purpose**. The red-team harness does exactly that — it runs each
canonical adversarial vector against an isolated Howdex instance,
captures the actual outcome, and classifies it as ``blocked`` /
``vulnerable`` / ``review``.

Every vector is **deterministic**: no LLM, no network, no external
services. Safe to run in CI on every pull request.

---

## Quick start

```bash
# List all available attack vectors
howdex redteam list

# Show details for one vector
howdex redteam show hallucinated_success

# Run the full harness (text report to stdout, exit 0 if all pass)
howdex redteam run

# Write a structured report to disk (format inferred from extension)
howdex redteam run --output redteam.html
howdex redteam run --output redteam.json
howdex redteam run --output redteam.md

# Run only a subset of vectors (comma-separated IDs)
howdex redteam run --only hallucinated_success,ledger_tamper_detection

# Explicit format override (text|markdown|json|html)
howdex redteam run --format json
```

**Exit codes** (useful for CI gating):

- ``0`` — all defenses held (or only ``review`` outcomes, no ``vulnerable``)
- ``2`` — at least one defense is broken (``vulnerable`` classification)
- ``1`` — harness usage error (unknown subcommand, bad vector id, etc.)

Recommended CI snippet:

```yaml
- name: Howdex red-team
  run: |
    howdex redteam run --output redteam.html
    howdex redteam run --format json --output redteam.json
  # The run subcommand exits 2 if any defense is broken, failing the job.
```

---

## Python API

```python
from howdex.redteam import RedTeamHarness, ATTACK_LIBRARY, list_vectors

# Inspect the attack library
for v in list_vectors():
    print(v["id"], v["name"])

# Run the full harness against an isolated Howdex instance
report = RedTeamHarness.run_all_default()
print(report.to_text())

if report.vulnerable_count > 0:
    raise SystemExit(f"{report.vulnerable_count} defense(s) broken!")

# Render the report in any format
print(report.to_markdown())
print(report.to_json(indent=2))

from howdex.html_renderers import render_redteam_report_html
html = render_redteam_report_html(report)
Path("redteam.html").write_text(html)

# Run a single vector
harness = RedTeamHarness()
result = harness.run_vector("ledger_tamper_detection")
print(result.classification, result.actual)

# Run a subset
report = harness.run_all(only=["hallucinated_success", "bootproof_blocks_learn"])
```

---

## Attack vectors

The library ships with 12 canonical vectors, organized by the defense
they target. Each vector is a self-contained function that spins up a
fresh temp-dir Howdex instance, runs the attack, tears it down, and
returns a structured ``AttackResult``.

### Hallucinated-success surface

| ID | Name | Defense tested |
|----|------|----------------|
| ``hallucinated_success`` | Hallucinated success with no verifier receipt | ``integrity_warnings()`` records ``unverified_success`` when ``end_session("success")`` is called after a failure-marked step with no receipt |
| ``strict_mode_downgrade`` | Strict ``require_receipt`` downgrades hallucinated success | With ``require_receipt_for_success=True``, outcome is downgraded from ``success`` to ``unverified`` |
| ``bootproof_blocks_learn`` | BootProof refuses to consolidate unverified sessions | ``BootProof.learn()`` returns ``[]`` and populates ``rejected_sessions`` |
| ``llm_verifier_rejected`` | BootProof rejects LLM-judgment receipts | ``BootProof.is_verified()`` returns ``False`` for ``verifier_type='llm_judgment'`` even when ``status='verified'`` |
| ``forged_verified_status`` | ``verify_procedure`` refuses verified status with failing exit code | ``verify_procedure(status='verified', exit_code=1)`` raises ``ValueError`` |

### Audit-trail surface

| ID | Name | Defense tested |
|----|------|----------------|
| ``ledger_tamper_detection`` | Merkle ledger detects tampered blocks | After modifying a row in ``memory_ledger``, ``ledger.verify()`` returns ``(False, msg)`` |
| ``trust_inflation_via_failed`` | Failed receipts cannot inflate trust calibration | ``trust_calibration_curve()`` reports ``verified=0`` when only failed receipts are attached |

### Recall / ranking surface

| ID | Name | Defense tested |
|----|------|----------------|
| ``dangerous_memory_downranked`` | Dangerous instructions down-ranked on recall | ``recall()`` ranks a safe rule above a higher-importance "ignore all safety checks" rule |
| ``needle_in_haystack_risk`` | Needle-in-haystack risk signal surfaces context collapse | ``needle_in_haystack_risk()`` returns a non-empty ``risk_level`` and ``recommendation`` |
| ``canonicalization_drift`` | Canonicalization drift detected for brittle procedures | ``detect_canonicalization_drift()`` returns a list (possibly empty) without crashing |

### Multi-tenant / network surface

| ID | Name | Defense tested |
|----|------|----------------|
| ``mcp_path_traversal`` | MCP ``codex_publish`` rejects path traversal | ``_validate_codex_path`` raises ``ValueError`` for ``..`` segments, ``~`` prefixes, and out-of-allowlist paths |
| ``crdt_replay_delete`` | Stale CRDT delete cannot tombstone newer memory | ``apply_remote_op`` ignores delete ops whose ``vector_clock`` is below the existing memory's clock |

---

## Classifications

Each vector's outcome is classified as one of:

- **``blocked``** — the defense held. The attack was rejected or flagged as
  expected. This is the success outcome.
- **``vulnerable``** — the attack succeeded. The defense is broken or
  absent. Treat as a release blocker.
- **``review``** — the outcome is ambiguous and warrants human inspection.
  Used when the harness itself crashed (e.g. an upstream API changed
  shape), or when the defense is heuristic (e.g. ranking-based vectors
  where "safe rank = 1, malicious rank > 1" is the goal but neither
  ranking is fully wrong).

A ``review`` outcome is not a release blocker, but should be triaged.
Common causes:

1. The Howdex internal API changed shape (e.g. a method was renamed).
   The harness couldn't run the attack at all. Fix the harness.
2. The defense is heuristic and the test is too strict. Loosen the
   assertion or split the vector into two more specific ones.

---

## Report formats

### Text (default)

Terminal-friendly summary. Prints one line per vector with the
classification badge, vector id, name, expected outcome, and actual
outcome. Ends with a verdict line.

### Markdown

A complete Markdown document with a summary table and one section per
vector. Suitable for attaching to a pull request, issue, or incident
report.

### JSON

A structured JSON object with ``started_at``, ``finished_at``,
``duration_s``, ``summary`` (counts + pass rate), and ``results``
(one object per vector with all fields). Suitable for piping into a
GRC tool, dashboard, or long-term storage for trend analysis.

### HTML

A single-file interactive HTML artifact with:

- Pass-rate summary dashboard with visual progress bar
- Attack-surface coverage matrix (vector × status)
- Collapsible cards per vector with threat model, expected/actual
  outcome, and remediation guidance
- Print-friendly CSS for PDF export (Ctrl+P → Save as PDF)

Open the HTML file in any browser. No external dependencies.

---

## Adding a new attack vector

The harness is designed to grow. When you discover a new attack class
(in a postmortem, a security review, or a user report), add a vector:

1. **Write a runner function** in ``howdex/redteam.py`` following the
   pattern of ``_v01_hallucinated_success_no_receipt``. It should:
   - Use ``_fresh_howdex()`` to spin up an isolated temp-dir instance.
   - Run the attack.
   - Return ``_blocked(vec, actual)`` / ``_vulnerable(vec, actual)`` /
     ``_review(vec, actual)`` based on the outcome.
   - Always clean up with ``mem.close(); shutil.rmtree(tmp, ignore_errors=True)``
     in a ``finally`` block.

2. **Register the vector** in ``ATTACK_LIBRARY`` with a stable id, a
   clear name, the threat model, the expected outcome, and the
   remediation guidance.

3. **Add a test** in ``tests/test_redteam.py``. The parametrized
   ``test_vector_runs_and_defense_holds`` will pick it up automatically.
   Add explicit assertions if the vector has invariants worth checking
   beyond the classification.

4. **Document the vector** in this file's "Attack vectors" table.

Vector ids should be ``snake_case`` and stable across releases — CI
scripts and dashboards key off them.

---

## Why a red-team harness matters for Howdex

Howdex's value proposition is **auditability**: every agent action has
a cryptographic receipt, every procedure is verified before it's
consolidated, the ledger is tamper-evident. If any of these defenses
silently break, the entire audit story collapses — and the breakage
will only be discovered during a real audit, by which point it's too
late.

The red-team harness converts "trust us, the defenses work" into
"here's the proof, regenerated on every commit." It is the operational
expression of Howdex's positioning as the audit and verification layer
for AI agents.

Run it. Pin it in CI. Treat a ``vulnerable`` classification as a
release blocker. The day a vector goes red is the day you found a bug
before your auditor did.
