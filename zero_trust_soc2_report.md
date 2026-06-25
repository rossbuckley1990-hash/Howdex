# Howdex Compliance Report — SOC2

**Generated:** 2026-06-25T12:09:04.254928+00:00
**Reporting period:** (all time) to (now)
**Report hash:** `76a6c6a6aeddff8a7ecf7b6bdda4a885a2d71b634de0feb9c5190e6e5c743170`

## Executive Summary

- **Total procedures:** 1
- **Verified (independently proven):** 1
- **Failed (verifier rejected):** 0
- **Candidate (observed, not verified):** 0
- **Total verification receipts:** 1
- **Cryptographically signed receipts:** 0
- **Verifier types in use:** exit_code

## Control Mapping

### CC7.1 — Detection and Monitoring — entity detects and monitors system changes

**Howdex evidence:**

- Every agent tool call is logged with a timestamp, agent_id, and session_id
- Procedures record their source episode IDs for full traceability

**Receipt fields satisfying this control:** `verifier_command, verified_at, procedure_id`

### CC7.2 — Anomaly Identification — entity detects anomalies and responds

**Howdex evidence:**

- Failed receipts (status='failed') are retained alongside verified ones
- Integrity warnings (unverified_success, step_observed_failure) surface hallucinated successes

**Receipt fields satisfying this control:** `status, exit_code, expected_signal, observed_signal`

### CC8.1 — Change Management — entity authorizes and documents changes

**Howdex evidence:**

- Each procedure has a verification receipt documenting the verifier command and observed signal
- Signed attestations provide tamper resistance via HMAC

**Receipt fields satisfying this control:** `verifier_command, signature, receipt_id`

### A1.1 — Availability — entity maintains availability of system operations

**Howdex evidence:**

- BootProof gate prevents unverified procedures from being deployed
- Trust calibration curve surfaces the verified-to-candidate ratio

**Receipt fields satisfying this control:** `status, verifier_type`

## Reproducibility

This report is deterministic. Re-running with the same database and
framework will produce the same report hash (`76a6c6a6aeddff8a7ecf7b6bdda4a885a2d71b634de0feb9c5190e6e5c743170`).
Auditors can verify integrity by regenerating and comparing hashes.

## Method

All verification evidence is derived from Howdex's receipt primitive.
A receipt is created only when a **deterministic, non-LLM verifier**
(exit code, HTTP status, test runner, etc.) confirms a procedure's
outcome. LLM judgments are explicitly NOT accepted as verification
evidence — see the BootProof gate in `howdex.bootproof`.
