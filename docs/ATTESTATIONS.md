# Signed receipt attestations

Howdex procedures can carry verification receipts. A receipt says that some
verifier observed a signal for a procedure. A signed attestation is stronger:
it binds the receipt evidence to a canonical payload hash and a verifier
signature.

This is still local-first infrastructure. Howdex does not contact a hosted
registry, trust service, or model provider to validate attestations.

## Receipt vs signed attestation

A receipt is structured evidence:

- verifier command
- expected signal
- observed signal
- exit code
- environment fingerprint
- artifact hashes
- timestamp

A signed attestation is a receipt plus tamper evidence:

- canonical JSON payload
- `payload_hash`
- `signature_algorithm`
- `signature`
- `signer_id`

The portable schema lives at
`codex/schemas/signed_receipt_attestation.schema.json`.

The first implementation uses standard-library HMAC-SHA256. That is useful for
local teams and CI systems that already share verifier key material. It is not a
claim of public-key, third-party, or hardware-backed production security.

## Why signatures matter

Without a signature, a receipt can still be useful evidence, but anyone with
write access to the local database or JSON file could alter it. With a valid
signature, Howdex can detect when receipt evidence has been changed after the
verifier signed it.

Signed attestations help avoid hallucinated success because a procedure can be
marked as signed verified only when all of these are true:

1. the verifier exit code is `0`;
2. the observed signal contains the expected signal;
3. the payload hash matches the canonical attestation payload;
4. the signature validates with supplied key material.

Unsigned receipts remain supported, but they are labelled as observed evidence,
not signed verification.

## Import an attestation

```bash
howdex receipt import ./attestation.json --hmac-key "$HOWDEX_VERIFIER_KEY"
```

If the attestation includes `procedure_id`, no extra procedure identifier is
needed. Otherwise provide one:

```bash
howdex receipt import ./attestation.json \
  --procedure-id procedure-123 \
  --hmac-key "$HOWDEX_VERIFIER_KEY"
```

Howdex also accepts BootProof-like JSON files containing verifier command,
observed signal, exit code, artifact hashes, environment metadata, and optional
signature or payload hash fields. BootProof is not required as a package.

## Verify an attestation without importing it

```bash
howdex receipt verify ./attestation.json --hmac-key "$HOWDEX_VERIFIER_KEY"
```

The command prints a deterministic JSON result with:

- attestation status;
- evidence validity;
- payload hash validity;
- signature validity;
- reasons for warnings or failures.

## Publish verified Codex entries

Normal Codex publishing keeps backwards compatibility:

```bash
howdex codex publish
```

To require signed verification before publishing:

```bash
howdex codex publish --require-signed-receipt
```

With this flag, Howdex refuses procedures that do not have a signed verified
receipt. Unsigned verified receipts remain evidence, but they are not enough for
signed verified Codex publication.

## Status model

- `evidence_observed`: verifier evidence passed, but no signature was present.
- `signed_verified`: verifier evidence passed, payload hash matched, and the
  HMAC signature validated.
- `failed`: verifier evidence did not pass.
- `invalid`: signed evidence was tampered with or the signature did not validate.
- `unknown`: Howdex could not fully evaluate the attestation, usually because
  signature key material was not supplied.

Procedures are still guidance, not executable authority. A signed attestation
shows that a verifier passed for a specific payload and environment; it does not
grant permission to run the procedure in a different environment.
