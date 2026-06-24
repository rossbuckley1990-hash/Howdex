# Codex governance

The Howdex Codex is operational memory, not a prompt library and not executable
authority. Teams should govern Codex entries with the same care they apply to
code: review diffs, lint policy metadata, detect semantic conflicts, deprecate
stale entries, and require receipts before trusting verified procedures.

## Governance lifecycle

1. Learn procedures from execution traces.
2. Publish candidate Codex entries.
3. Lint entries before review or CI merge.
4. Diff and merge entries with conflict detection.
5. Attach verifier receipts or signed attestations.
6. Promote trust only when proof exists.
7. Deprecate stale, unsafe, or superseded entries.

Candidate entries can still be useful guidance. They are not trusted proof.
Verified entries require inspectable verification metadata, and signed-verified
entries require signed attestation evidence.

## CLI commands

```bash
howdex codex lint codex
howdex codex diff left.json right.json
howdex codex merge --interactive left.json right.json --output merged.json
howdex codex verify codex
howdex codex deprecate howdex.example --reason "superseded" --codex-path codex
howdex codex trust howdex.example --level candidate --codex-path codex
howdex codex policy-check codex
```

`merge --interactive` currently performs deterministic conflict detection and
prints a TODO when manual resolution is needed. It does not yet provide a full
terminal editor workflow.

## Lint rules

`howdex codex lint <path>` checks:

- required fields are present;
- status values are supported;
- verification metadata exists;
- policy metadata exists;
- risk level is present and valid;
- source code blocks and obvious source markers are excluded by default;
- verified entries include receipt or attestation metadata;
- signed-verified entries include signed attestation evidence;
- banned command patterns are not present;
- unresolved placeholders are warned before execution;
- stale or incompatible compatibility metadata is warned.

Warnings do not fail lint. Errors return nonzero.

## Banned command defaults

The governance layer blocks obvious host-destructive commands by default:

- `rm -rf /`
- `sudo rm`
- `chmod 777 /`
- `curl | sh`
- `wget | sh`
- `docker system prune -a` without approval metadata
- `kubectl delete namespace` without approval metadata

This is not a complete policy engine. It is a deterministic safety floor that
teams can run locally and in CI.

## CI usage

```bash
python -m howdex codex lint codex
python -m howdex codex policy-check codex
python -m howdex codex verify codex
```

Use these checks before accepting a Codex entry from another team, benchmark, or
agent run.

## Diff and merge examples

`howdex codex diff` focuses on governance-relevant fields:

- `learned_facts`
- `avoid`
- `verification`
- `policy`
- `compatibility`
- `status`
- `receipts`

`howdex codex merge` detects semantic conflicts such as:

- near-same tasks with conflicting trust status;
- one entry verified while another is failed, stale, blocked, or deprecated;
- policy conflicts where one entry allows behavior the other forbids;
- conflicting compatibility or version ranges;
- incompatible verifier command families for the same task family.

## Deprecation

Deprecation preserves the entry and records why it should not be reused as
current guidance:

```bash
howdex codex deprecate howdex.old_entry \
  --reason "React version assumptions are stale" \
  --codex-path codex
```

Deprecated procedures remain historical evidence. They should not be rendered as
recommended guidance without explicit review.

## Trust levels

```bash
howdex codex trust howdex.entry --level candidate
howdex codex trust howdex.entry --level verified
howdex codex trust howdex.entry --level blocked
```

The CLI refuses to mark an entry `verified` unless receipt or attestation
metadata exists. It does not fabricate proof.

## Policy checks

`howdex codex policy-check <path>` fails when high-risk or critical entries lack
human-review or approval metadata, and when banned command patterns appear in
executable guidance fields.

Procedures remain guidance. Governance metadata helps decide whether guidance is
safe to show, review, deprecate, or block; it does not grant execution authority.
