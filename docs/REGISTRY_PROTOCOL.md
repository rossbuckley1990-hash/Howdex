# Howdex Codex registry protocol

Howdex is protocol-first. A hosted registry can come later, but verified agent
procedures must be portable before they are centralized. The registry protocol
therefore starts with formats that already work in ordinary infrastructure:
local folders, Git repositories, and static HTTP hosting.

The registry is a catalogue of operational memory. It is not a prompt library,
not a package manager, and not executable authority. Procedures remain guidance
until a local policy engine and verifier decide they are safe to use.

## Registry modes

### 1. Local folder

A local folder is the reference implementation and the default mode implemented
today. It is suitable for single-user workflows, CI fixtures, and checked-out
team repositories.

```bash
howdex registry init ./codex-registry
howdex registry add ./procedure.json --to ./codex-registry
howdex registry index ./codex-registry
howdex registry verify ./codex-registry
```

### 2. Git-backed registry

A Git-backed registry uses the same folder layout and commits changes through
normal code review. No hosted Howdex service is required. This mode is designed
for teams that want pull-request review, CODEOWNERS, branch protection, and
artifact retention using existing Git governance.

The current implementation defines this protocol mode but rejects `git+https://`
sources with a clear error rather than shelling out to `git`. Future versions
can add a Git adapter without changing the on-disk format.

### 3. Static HTTP registry

A static HTTP registry serves `manifest.json`, procedure entries, receipts,
signatures, and indexes from ordinary object storage or static hosting. Clients
can fetch and verify content hashes locally.

The current implementation defines this protocol mode but does not fetch HTTP
sources in tests or default operation. Future versions can add read-only static
HTTP pull support with size limits, timeouts, and hash verification.

## Layout

```text
codex/
  manifest.json
  procedures/
  receipts/
  signatures/
  indexes/
    by_category.json
    by_tag.json
    by_ecosystem.json
    by_status.json
```

`procedures/` contains Codex procedure entries. `receipts/` contains
verification receipt documents when stored separately. `signatures/` contains
signed receipt attestations. `indexes/` contains deterministic lookup indexes
derived from procedure entries.

## Manifest

`manifest.json` is the registry root metadata:

- `registry_name`
- `registry_version`
- `created_at`
- `updated_at`
- `entry_count`
- `verified_count`
- `candidate_count`
- `supported_schema_versions`
- `root_hash`
- `signing_keys` optional
- `trust_policy` optional

Example:

```json
{
  "candidate_count": 4,
  "created_at": "2026-06-24T12:00:00Z",
  "entry_count": 5,
  "registry_name": "team-codex",
  "registry_version": "1",
  "root_hash": "sha256:...",
  "supported_schema_versions": ["1.0.0"],
  "updated_at": "2026-06-24T12:10:00Z",
  "verified_count": 1
}
```

## Indexes

Indexes are deterministic JSON maps from key to sorted procedure IDs:

- `indexes/by_category.json`
- `indexes/by_tag.json`
- `indexes/by_ecosystem.json`
- `indexes/by_status.json`

They are derived data. `howdex registry index <path>` rebuilds them from
`procedures/*.json`.

## Root hash

`root_hash` is a SHA-256 digest over canonical registry content in:

- `procedures/*.json`
- `receipts/*.json`
- `signatures/*.json`
- `indexes/*.json`

The manifest itself is excluded from the root hash so `updated_at` and
`root_hash` can change without recursively changing the digest. File paths and
canonical JSON bytes are included, so renaming or editing content changes the
hash.

`howdex registry verify <path>` recomputes the root hash and fails if it does
not match the manifest.

## Trust model

The registry separates status from proof:

- `candidate`: useful operational memory, not proof;
- `experimental`: benchmark- or trace-derived guidance that still needs review;
- `verified`: requires inspectable verification metadata;
- `blocked`: should not be rendered as recommended guidance;
- `deprecated`: historical, stale, or superseded guidance.

Candidate entries must never be silently promoted to verified. Verification
requires receipt evidence, and signed verification requires valid signed
attestation metadata.

## Signed receipts

Signed receipt attestations live in `signatures/` or inside entry verification
metadata. They bind verifier evidence to a canonical payload hash and signature.
The first Howdex implementation supports local HMAC-SHA256 attestations without
requiring external cryptography packages.

Signed receipts do not grant execution authority. They show that a verifier
passed for a specific procedure and environment.

## CLI protocol

```bash
howdex registry init <path>
howdex registry index <path>
howdex registry verify <path>
howdex registry pull <source> --to <path>
howdex registry add <procedure-json> --to <path>
howdex registry trust-policy <path>
```

Current source support:

- local paths;
- `file://` paths.

Defined but not implemented yet:

- `git+https://...`;
- `https://...` static manifests.

Unsupported remote modes fail closed with a clear error. They do not fall back
to network calls or shell commands.

## Verification

Registry verification checks:

- all entries lint against Codex governance rules;
- manifest counts match the procedure files;
- `root_hash` matches canonical registry content;
- indexes match procedure entries;
- signature files parse and their payload hashes match when present.

This is enough for local folders, Git repositories, and static file hosting to
share the same trust envelope.

## Future hosted registry compatibility

A hosted registry should serve the same manifest, entries, receipts, signatures,
and indexes. A hosted service may add authentication, access controls,
replication, transparency logs, or enterprise policy workflows, but it should
not require a different procedure format.

That is the point of the protocol: agents should be able to carry verified
know-how across models, frameworks, clouds, and registry implementations.
