"""Local governance utilities for Howdex Codex entries.

The functions here intentionally avoid external services and schema
dependencies. They provide deterministic checks that can run in CI before a
team publishes, merges, or trusts operational memory.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from howdex.attestation import verify_attestation

REQUIRED_FIELDS = {
    "avoid",
    "category",
    "id",
    "learned_facts",
    "policy",
    "provenance",
    "risk_level",
    "source",
    "status",
    "tags",
    "title",
    "verification",
    "version",
}
VALID_STATUSES = {
    "blocked",
    "candidate",
    "deprecated",
    "experimental",
    "verified",
}
VALID_TRUST_LEVELS = {"candidate", "verified", "blocked"}
RISK_LEVELS = {"low", "medium", "high", "critical", "unknown"}
DIFF_FIELDS = (
    "learned_facts",
    "avoid",
    "verification",
    "policy",
    "compatibility",
    "status",
    "receipts",
)
SOURCE_MARKERS = (
    "```",
    "def ",
    "import ",
    "class ",
    "#!/usr/bin/env",
)
PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_]*>")


@dataclass(frozen=True)
class GovernanceFinding:
    severity: str
    code: str
    message: str
    path: str = ""
    entry_id: str = ""

    def format(self) -> str:
        location = self.path or self.entry_id or "codex"
        return f"{self.severity.upper()} {self.code} {location}: {self.message}"


@dataclass
class GovernanceReport:
    findings: list[GovernanceFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[GovernanceFinding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> list[GovernanceFinding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: GovernanceReport) -> None:
        self.findings.extend(other.findings)


def lint_codex(path: str | Path, *, hmac_key: str | None = None) -> GovernanceReport:
    """Lint one Codex entry, entries folder, or Codex root."""
    report = GovernanceReport()
    paths = entry_paths(path)
    if not paths:
        report.findings.append(
            GovernanceFinding("error", "no_entries", "no Codex entries found", str(path))
        )
        return report
    for entry_path in paths:
        report.extend(lint_entry(load_entry(entry_path), entry_path, hmac_key=hmac_key))
    return report


def verify_codex(path: str | Path, *, hmac_key: str | None = None) -> GovernanceReport:
    """Run lint plus verification-specific checks."""
    report = lint_codex(path, hmac_key=hmac_key)
    for entry_path in entry_paths(path):
        entry = load_entry(entry_path)
        verification = _mapping(entry.get("verification"))
        if verification.get("status") == "verified" and entry.get("status") != "verified":
            report.findings.append(
                GovernanceFinding(
                    "warning",
                    "verification_status_mismatch",
                    "verification says verified but entry status is not verified",
                    str(entry_path),
                    str(entry.get("id") or ""),
                )
            )
    return report


def policy_check_codex(path: str | Path) -> GovernanceReport:
    """Check policy metadata independently from structural lint."""
    report = GovernanceReport()
    for entry_path in entry_paths(path):
        entry = load_entry(entry_path)
        entry_id = str(entry.get("id") or "")
        policy = _mapping(entry.get("policy"))
        if entry.get("risk_level") in {"high", "critical"} and not _has_approval(policy):
            report.findings.append(
                GovernanceFinding(
                    "error",
                    "approval_required",
                    "high-risk or critical entries require human review or approval metadata",
                    str(entry_path),
                    entry_id,
                )
            )
        report.findings.extend(_banned_command_findings(entry, entry_path))
    return report


def lint_entry(
    entry: Mapping[str, Any],
    path: str | Path = "",
    *,
    hmac_key: str | None = None,
) -> GovernanceReport:
    report = GovernanceReport()
    entry_id = str(entry.get("id") or "")
    location = str(path)

    missing = sorted(REQUIRED_FIELDS - set(entry.keys()))
    for field_name in missing:
        report.findings.append(
            GovernanceFinding(
                "error",
                "missing_required_field",
                f"missing required field {field_name}",
                location,
                entry_id,
            )
        )

    status = str(entry.get("status") or "")
    if status not in VALID_STATUSES:
        report.findings.append(
            GovernanceFinding(
                "error",
                "invalid_status",
                f"unsupported status {status!r}",
                location,
                entry_id,
            )
        )

    risk_level = str(entry.get("risk_level") or "")
    if risk_level and risk_level not in RISK_LEVELS:
        report.findings.append(
            GovernanceFinding(
                "error",
                "invalid_risk_level",
                f"unsupported risk_level {risk_level!r}",
                location,
                entry_id,
            )
        )

    verification = _mapping(entry.get("verification"))
    if not verification:
        report.findings.append(
            GovernanceFinding("error", "missing_verification", "verification metadata is required", location, entry_id)
        )
    else:
        for required in ("expected_signal", "verifier_command", "verifier_type", "status"):
            if not verification.get(required):
                report.findings.append(
                    GovernanceFinding(
                        "error",
                        "incomplete_verification",
                        f"verification.{required} is required",
                        location,
                        entry_id,
                    )
                )

    policy = _mapping(entry.get("policy"))
    if not policy:
        report.findings.append(
            GovernanceFinding("error", "missing_policy", "policy metadata is required", location, entry_id)
        )
    elif "requires_human_review" not in policy:
        report.findings.append(
            GovernanceFinding(
                "error",
                "incomplete_policy",
                "policy.requires_human_review is required",
                location,
                entry_id,
            )
        )

    if status == "verified" and not _has_receipt_material(entry):
        report.findings.append(
            GovernanceFinding(
                "error",
                "verified_without_receipt",
                "verified entries require attached receipt or attestation metadata",
                location,
                entry_id,
            )
        )

    if verification.get("signature_status") == "signed_verified":
        if not _has_signed_attestation(entry, hmac_key=hmac_key):
            report.findings.append(
                GovernanceFinding(
                    "error",
                    "signed_verified_without_valid_attestation",
                    "signed-verified entries require a valid signed attestation payload",
                    location,
                    entry_id,
                )
            )

    if not _include_source_allowed(entry):
        for marker in SOURCE_MARKERS:
            if _marker_present(entry, marker):
                report.findings.append(
                    GovernanceFinding(
                        "error",
                        "source_artifact_present",
                        f"source marker {marker!r} is not allowed by default",
                        location,
                        entry_id,
                    )
                )

    report.findings.extend(_banned_command_findings(entry, Path(location) if location else Path("")))

    for text in _command_like_strings(entry):
        if PLACEHOLDER_RE.search(text):
            report.findings.append(
                GovernanceFinding(
                    "warning",
                    "unresolved_parameter_binding",
                    "placeholder parameters must be bound before execution",
                    location,
                    entry_id,
                )
            )
            break

    if _staleness_warning(entry):
        report.findings.append(
            GovernanceFinding(
                "warning",
                "staleness_review_required",
                "compatibility metadata indicates this entry may need reverification",
                location,
                entry_id,
            )
        )

    return report


def diff_codex_entries(left: str | Path, right: str | Path) -> list[str]:
    """Return human-readable field diffs for governance-relevant fields."""
    left_entry = first_entry(left)
    right_entry = first_entry(right)
    lines: list[str] = []
    for field_name in DIFF_FIELDS:
        left_value = left_entry.get(field_name)
        right_value = right_entry.get(field_name)
        if left_value != right_value:
            lines.append(f"changed {field_name}:")
            lines.append(f"- {json.dumps(left_value, sort_keys=True, ensure_ascii=False)}")
            lines.append(f"+ {json.dumps(right_value, sort_keys=True, ensure_ascii=False)}")
    return lines


def detect_merge_conflicts(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[str]:
    """Detect semantic conflicts before merging Codex entries."""
    conflicts: list[str] = []
    if _same_or_near_task(left, right):
        left_status = str(left.get("status") or "")
        right_status = str(right.get("status") or "")
        left_verification = str(_mapping(left.get("verification")).get("status") or "")
        right_verification = str(_mapping(right.get("verification")).get("status") or "")
        if {left_status, right_status} & {"verified"} and (
            {left_status, right_status} & {"blocked", "deprecated"}
            or {left_verification, right_verification} & {"failed", "stale"}
        ):
            conflicts.append("trust status conflict: verified entry conflicts with failed/stale/blocked entry")
        if _policy_conflict(left, right):
            conflicts.append("policy conflict: one entry allows behavior the other forbids")
        if _version_conflict(left, right):
            conflicts.append("compatibility conflict: version ranges or incompatible versions disagree")
        if _command_family(left) and _command_family(right) and _command_family(left) != _command_family(right):
            conflicts.append("command conflict: verifier command families differ for near-same task")
    return conflicts


def merge_codex_entries(
    left: str | Path,
    right: str | Path,
    output: str | Path,
    *,
    interactive: bool = False,
) -> tuple[bool, list[str]]:
    """Merge two entries when no semantic conflicts are detected."""
    left_entry = first_entry(left)
    right_entry = first_entry(right)
    conflicts = detect_merge_conflicts(left_entry, right_entry)
    if conflicts:
        if interactive:
            conflicts.append("TODO: interactive conflict resolution is not implemented yet")
        return False, conflicts
    merged = _merged_entry(left_entry, right_entry)
    _write_entry(Path(output), merged)
    return True, []


def deprecate_entry(entry_id: str, reason: str, *, codex_path: str | Path = "codex") -> Path:
    """Mark one Codex entry deprecated and record deprecation metadata."""
    path, entry = _find_entry(entry_id, codex_path)
    entry["status"] = "deprecated"
    entry["deprecation"] = {
        "deprecated_at": _iso_now(),
        "reason": reason,
    }
    _write_entry(path, entry)
    return path


def set_trust_level(entry_id: str, level: str, *, codex_path: str | Path = "codex") -> Path:
    """Set a conservative trust level for one Codex entry."""
    if level not in VALID_TRUST_LEVELS:
        raise ValueError(f"unsupported trust level: {level}")
    path, entry = _find_entry(entry_id, codex_path)
    if level == "verified" and not _has_receipt_material(entry):
        raise ValueError("cannot mark entry verified without receipt metadata")
    entry["status"] = level
    entry["trust"] = {
        "level": level,
        "updated_at": _iso_now(),
    }
    _write_entry(path, entry)
    return path


def entry_paths(path: str | Path) -> list[Path]:
    root = Path(path)
    if root.is_file():
        return [root]
    if (root / "entries").is_dir():
        return sorted((root / "entries").glob("*.json"))
    if (root / "procedures").is_dir():
        return sorted((root / "procedures").glob("*.json"))
    if root.is_dir():
        return sorted(root.glob("*.json"))
    return []


def first_entry(path: str | Path) -> dict[str, Any]:
    paths = entry_paths(path)
    if not paths:
        raise FileNotFoundError(f"no Codex entry found at {path}")
    return load_entry(paths[0])


def load_entry(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Codex entry must be an object: {path}")
    return payload


def _find_entry(entry_id: str, codex_path: str | Path) -> tuple[Path, dict[str, Any]]:
    for path in entry_paths(codex_path):
        entry = load_entry(path)
        if entry.get("id") == entry_id:
            return path, entry
    raise FileNotFoundError(f"no Codex entry with id={entry_id!r} under {codex_path}")


def _has_receipt_material(entry: Mapping[str, Any]) -> bool:
    verification = _mapping(entry.get("verification"))
    receipts = (
        verification.get("receipts")
        or verification.get("attestations")
        or entry.get("receipts")
    )
    return bool(receipts or verification.get("receipt_id"))


def _has_signed_attestation(entry: Mapping[str, Any], *, hmac_key: str | None = None) -> bool:
    verification = _mapping(entry.get("verification"))
    candidates = verification.get("attestations") or entry.get("attestations") or []
    if isinstance(candidates, Mapping):
        candidates = [candidates]
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, Mapping):
            continue
        result = verify_attestation(candidate, key_material=hmac_key)
        if result.status == "signed_verified":
            return True
    return False


def _include_source_allowed(entry: Mapping[str, Any]) -> bool:
    policy = _mapping(entry.get("policy"))
    return bool(entry.get("include_source")) or policy.get("source_artifacts") == "included"


def _marker_present(entry: Mapping[str, Any], marker: str) -> bool:
    target = marker if marker == "```" else marker.casefold()
    for text in _strings(entry):
        haystack = text if marker == "```" else text.casefold()
        if target in haystack:
            return True
    return False


def _banned_command_findings(entry: Mapping[str, Any], path: Path) -> list[GovernanceFinding]:
    findings: list[GovernanceFinding] = []
    entry_id = str(entry.get("id") or "")
    policy = _mapping(entry.get("policy"))
    approval = _has_approval(policy)
    for command in _command_like_strings(entry):
        normalized = " ".join(command.casefold().split())
        banned = None
        requires_approval = False
        if "rm -rf /" in normalized:
            banned = "rm -rf /"
        elif "sudo rm" in normalized:
            banned = "sudo rm"
        elif "chmod 777 /" in normalized:
            banned = "chmod 777 /"
        elif re.search(r"\bcurl\b.*\|\s*sh\b", normalized):
            banned = "curl | sh"
        elif re.search(r"\bwget\b.*\|\s*sh\b", normalized):
            banned = "wget | sh"
        elif "docker system prune -a" in normalized:
            banned = "docker system prune -a"
            requires_approval = True
        elif "kubectl delete namespace" in normalized:
            banned = "kubectl delete namespace"
            requires_approval = True
        if banned and (not requires_approval or not approval):
            findings.append(
                GovernanceFinding(
                    "error",
                    "banned_command",
                    f"banned command pattern detected: {banned}",
                    str(path),
                    entry_id,
                )
            )
    return findings


def _command_like_strings(entry: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    verification = _mapping(entry.get("verification"))
    if verification.get("verifier_command"):
        values.append(str(verification["verifier_command"]))
    for key in ("learned_facts", "allowed"):
        source: Any
        if key == "allowed":
            source = _mapping(entry.get("policy")).get("allowed", [])
        else:
            source = entry.get(key, [])
        if isinstance(source, list):
            values.extend(str(item) for item in source if isinstance(item, str))
    return values


def _has_approval(policy: Mapping[str, Any]) -> bool:
    return bool(
        policy.get("requires_human_review")
        or policy.get("approval_required")
        or policy.get("explicit_approval")
        or policy.get("approval")
        or policy.get("approval_metadata")
    )


def _staleness_warning(entry: Mapping[str, Any]) -> bool:
    compatibility = _mapping(entry.get("compatibility"))
    if compatibility.get("known_incompatible_versions"):
        return True
    stale_after = compatibility.get("stale_after_days")
    last_verified = compatibility.get("last_verified_at")
    if not stale_after or not last_verified:
        return False
    try:
        stale_after_s = int(stale_after) * 86400
        last_verified_s = _parse_year_month_day(str(last_verified))
    except ValueError:
        return True
    return time.time() - last_verified_s > stale_after_s


def _same_or_near_task(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("id") == right.get("id"):
        return True
    if left.get("category") != right.get("category"):
        return False
    left_tokens = _tokens(" ".join([str(left.get("title") or ""), *map(str, left.get("tags", []))]))
    right_tokens = _tokens(" ".join([str(right.get("title") or ""), *map(str, right.get("tags", []))]))
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return overlap >= 0.35


def _policy_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_policy = _mapping(left.get("policy"))
    right_policy = _mapping(right.get("policy"))
    left_allowed = {str(item).casefold() for item in left_policy.get("allowed", []) if isinstance(item, str)}
    right_allowed = {str(item).casefold() for item in right_policy.get("allowed", []) if isinstance(item, str)}
    left_forbidden = {str(item).casefold() for item in left_policy.get("forbidden", []) if isinstance(item, str)}
    right_forbidden = {str(item).casefold() for item in right_policy.get("forbidden", []) if isinstance(item, str)}
    return bool(left_allowed & right_forbidden or right_allowed & left_forbidden)


def _version_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_compat = _mapping(left.get("compatibility"))
    right_compat = _mapping(right.get("compatibility"))
    for key in ("version_range", "known_incompatible_versions"):
        if left_compat.get(key) and right_compat.get(key) and left_compat.get(key) != right_compat.get(key):
            return True
    return False


def _command_family(entry: Mapping[str, Any]) -> str:
    command = str(_mapping(entry.get("verification")).get("verifier_command") or "").strip()
    return command.split()[0] if command else ""


def _merged_entry(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key in ("learned_facts", "avoid", "tags"):
        merged[key] = _unique([*left.get(key, []), *right.get(key, [])])
    merged["policy"] = _merge_mapping(_mapping(left.get("policy")), _mapping(right.get("policy")))
    merged["provenance"] = _merge_mapping(_mapping(left.get("provenance")), _mapping(right.get("provenance")))
    if right.get("status") == "verified":
        merged["status"] = "verified"
        merged["verification"] = right.get("verification")
    return merged


def _merge_mapping(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = _unique([*merged[key], *value])
        elif key not in merged:
            merged[key] = value
    return merged


def _write_entry(path: Path, entry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold()) if len(token) > 2}


def _unique(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    output: list[Any] = []
    for value in values:
        key = json.dumps(value, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _parse_year_month_day(value: str) -> float:
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        raise ValueError(value)
    return time.mktime(tuple([int(match.group(1)), int(match.group(2)), int(match.group(3)), 0, 0, 0, 0, 0, -1]))


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


__all__ = [
    "GovernanceFinding",
    "GovernanceReport",
    "deprecate_entry",
    "detect_merge_conflicts",
    "diff_codex_entries",
    "entry_paths",
    "lint_codex",
    "merge_codex_entries",
    "policy_check_codex",
    "set_trust_level",
    "verify_codex",
]
