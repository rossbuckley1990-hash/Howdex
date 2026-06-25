# Howdex Verification Receipt Specification v1.0

**Status:** Draft
**Last updated:** 2026-06-25
**License:** Apache-2.0

## 1. Purpose

A **Howdex Verification Receipt** (or "receipt") is a cryptographically-signed,
deterministic proof that an AI agent's procedure was verified by an independent,
non-LLM checker. It is the unit of audit evidence for AI agent governance.

This specification defines the receipt format independently of any specific
implementation. The reference implementation is in
[`howdex/core/receipts.py`](../howdex/core/receipts.py), but any system that
emits receipts conforming to this spec is Howdex-compatible.

**Why this matters:** Enterprises deploying AI agents face a compliance wall
(EU AI Act Articles 9/12/15, NIST AI RMF, ISO 42001, SOC 2's AI criteria).
They need to prove, with tamper-resistant evidence, that their agents' actions
were verified — not just that an LLM claimed success. The Howdex Verification
Receipt is the standardized artifact that satisfies this need.

## 2. Definitions

- **Procedure** — a reusable, parameterized description of how an agent
  accomplished a task. Procedures are guidance, not executable authority.
- **Verifier** — a deterministic, non-LLM checker that confirms a
  procedure's outcome. Examples: `pytest` (exit code 0), `curl` (HTTP 200),
  a build script, a health check.
- **Receipt** — the artifact recording that a verifier was run, what it
  observed, and what it concluded.
- **LLM judgment** — a language model's claim that a task succeeded.
  **LLM judgments are explicitly NOT valid verification evidence under this
  spec.** They are observations, not verifications.

## 3. Receipt Schema

A receipt is a JSON object with the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `receipt_id` | string | yes | SHA-256 content hash of the receipt payload. Unique per (procedure_id, verifier_command, exit_code, observed_signal). |
| `procedure_id` | string | yes | The ID of the procedure this receipt verifies. |
| `task_signature` | string | yes | The canonical task signature of the procedure. |
| `verifier_type` | string | yes | One of: `exit_code`, `http_status`, `test_runner`, `bash`, `build`, `healthcheck`, `file_exists`, `sql_query`. **NOT `llm`.** |
| `verifier_command` | string | yes | The exact command that was run. Reproducible. |
| `expected_signal` | string | yes | The signal the verifier was expected to produce. |
| `observed_signal` | string | yes | The signal the verifier actually produced (truncated to a reasonable size). |
| `exit_code` | integer | yes | The process exit code. `0` = success. |
| `status` | string | yes | One of: `verified`, `failed`, `stale`, `unknown`. `verified` requires `exit_code == 0` AND `expected_signal` is a substring of `observed_signal` (with exceptions for recognized test runners — see §5). |
| `verified_at` | float \| null | no | Unix timestamp (milliseconds) when verification occurred. |
| `environment_fingerprint` | object | no | Key-value map of the environment (OS, runtime versions, etc.) for reproducibility. |
| `artifact_hashes` | object | no | SHA-256 hashes of artifacts produced/consumed by the procedure. |
| `source_episode_id` | string \| null | no | The episode this verification corresponds to. |
| `signature` | string \| null | no | HMAC-SHA256 signature over the receipt payload (see §6). |
| `metadata` | object | no | Arbitrary additional metadata. |

## 4. Verifier Types

Only deterministic, non-LLM verifiers are valid. The recognized types are:

| Type | Description | Success criterion |
|---|---|---|
| `exit_code` | Any process whose exit code is the canonical signal. | `exit_code == 0` |
| `http_status` | An HTTP request whose status code is the signal. | `status_code` in `{200, 201, 202, 204}` |
| `test_runner` | A test runner (`pytest`, `jest`, `cargo test`, `go test`, `rspec`, `mvn test`, `gradle test`, `dotnet test`). | `exit_code == 0` (substring match not required — test runners sometimes suppress the textual summary). |
| `bash` | A bash command with a deterministic exit code. | `exit_code == 0` |
| `build` | A build system (`make`, `cargo build`, `npm run build`). | `exit_code == 0` |
| `healthcheck` | A service health check. | `exit_code == 0` or HTTP 200. |
| `file_exists` | A filesystem existence check. | File exists. |
| `sql_query` | A SQL query whose result set is the signal. | Result matches expected. |

**`llm` is explicitly NOT in this list.** An LLM's claim that a task succeeded
is an observation, not a verification. Systems that accept LLM judgments as
verification evidence are **not Howdex-compatible** and cannot claim to produce
Howdex Verification Receipts.

## 5. The `status` Field

- **`verified`** — the verifier ran, exited 0, and produced the expected
  signal. This is the only status that counts as "proof" for compliance.
- **`failed`** — the verifier ran but did not pass (non-zero exit, or
  expected signal not observed). Failed receipts are RETAINED — they are
  evidence of what didn't work, which is itself auditable.
- **`stale`** — the receipt was valid at one point but the environment has
  changed and re-verification is needed.
- **`unknown`** — no fresh verifier result exists.

## 6. Signatures (Optional but Recommended)

For tamper resistance, receipts SHOULD be signed with HMAC-SHA256 using a
shared secret. The signature is computed over the canonical JSON
serialization of the receipt (sorted keys, no whitespace) excluding the
`signature` field itself.

```python
import hmac, hashlib, json
payload = {k: v for k, v in receipt.items() if k != "signature"}
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
signature = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
```

Verification:
```python
expected = compute_signature(receipt_without_signature, secret)
if not hmac.compare_digest(expected, receipt["signature"]):
    raise TamperError("receipt signature mismatch")
```

## 7. Compliance Mapping

Receipts map directly to common AI governance controls:

| Framework | Control | Receipt fields satisfying it |
|---|---|---|
| SOC 2 | CC7.1 (Detection & Monitoring) | `verifier_command`, `verified_at`, `procedure_id` |
| SOC 2 | CC8.1 (Change Management) | `verifier_command`, `signature`, `receipt_id` |
| EU AI Act | Article 9 (Risk Management) | `verifier_command`, `status`, `expected_signal` |
| EU AI Act | Article 12 (Logging) | `verified_at`, `receipt_id`, `verifier_command` |
| EU AI Act | Article 15 (Accuracy/Robustness) | `status`, `exit_code`, `verifier_type` |
| NIST AI RMF | GOVERN-1 | `signature`, `verifier_command` |
| NIST AI RMF | MEASURE-1 | `verifier_type`, `verifier_command`, `expected_signal`, `observed_signal`, `exit_code` |
| NIST AI RMF | MANAGE-1 | `status`, `exit_code` |

Use `howdex compliance report --framework <framework>` to generate a full
audit-ready report.

## 8. Reproducibility

Receipts are reproducible: an auditor can re-run `verifier_command` in an
environment matching `environment_fingerprint` and expect the same
`exit_code` and `observed_signal`. The `receipt_id` (content hash) lets
the auditor confirm the receipt has not been modified since issuance.

## 9. Versioning

This is spec v1.0. Future versions will be semver-incremented. Receipts
include an implicit spec version via the `receipt_id` hash function
(SHA-256 in v1.x). A v2.0 with a different hash function would require
re-verification of all existing receipts.

## 10. Open Questions

- **Cross-org receipt sharing.** Should receipts be shareable across
  organizations without revealing `verifier_command` (which may contain
  internal URLs)? A redacted variant is under consideration.
- **Receipt expiry.** Should receipts have a TTL after which they become
  `stale` automatically? Environment drift makes old receipts less
  meaningful, but the right TTL is domain-specific.
- **Revocation.** If a verifier is later found to be flawed, how do we
  revoke receipts it produced? A revocation list is the likely answer.

## 11. References

- EU AI Act, Articles 9, 12, 15
- NIST AI Risk Management Framework (AI RMF 1.0)
- ISO/IEC 42001:2023 (AI management systems)
- AICPA Trust Services Criteria (SOC 2)
- Howdex reference implementation: `howdex/core/receipts.py`
- Howdex BootProof gate: `howdex/bootproof.py`
- Howdex compliance reports: `howdex/governance.py`
