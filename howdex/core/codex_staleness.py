"""Deterministic Codex environment compatibility and staleness checks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

STALENESS_STATUSES = {
    "fresh",
    "warning",
    "stale",
    "incompatible",
    "unknown",
}


@dataclass(frozen=True)
class StalenessDecision:
    """Inspectable decision for whether a Codex procedure is current enough."""

    status: str = "unknown"
    reasons: list[str] = field(default_factory=list)
    required_reverification: bool = True
    confidence_multiplier: float = 0.6


def evaluate_codex_staleness(
    entry: Any,
    current_environment: Mapping[str, Any] | str | None,
) -> StalenessDecision:
    """Evaluate a Codex entry against the current environment.

    The evaluator deliberately supports only simple deterministic version
    matching. Unknowns degrade confidence and require reverification; entries
    are never deleted automatically.
    """
    compatibility = compatibility_metadata(entry)
    if not compatibility:
        return StalenessDecision(
            status="unknown",
            reasons=["entry has no compatibility metadata"],
            required_reverification=True,
            confidence_multiplier=0.6,
        )

    environment = _normalize_environment(current_environment)
    if not environment:
        return StalenessDecision(
            status="unknown",
            reasons=["current environment is unknown"],
            required_reverification=True,
            confidence_multiplier=0.6,
        )

    reasons: list[str] = []
    warning_reasons: list[str] = []
    stale_reasons: list[str] = []
    incompatible_reasons: list[str] = []
    unknown_reasons: list[str] = []

    ecosystem = _string_value(compatibility.get("ecosystem"))
    environment_ecosystem = _string_value(environment.get("ecosystem"))
    if ecosystem and environment_ecosystem and ecosystem != environment_ecosystem:
        warning_reasons.append(
            f"ecosystem differs: entry={ecosystem}, current={environment_ecosystem}"
        )

    target_name = _compatibility_target(compatibility)
    version = _environment_version(environment, target_name)
    version_range = _string_value(compatibility.get("version_range"))
    if version:
        for pattern in _string_list(compatibility.get("known_incompatible_versions")):
            match = _version_matches_pattern(version, pattern)
            if match is True:
                incompatible_reasons.append(
                    f"{target_name or 'target'} version {version} matches incompatible {pattern}"
                )
                break
        if not incompatible_reasons and version_range:
            in_range = _version_in_range(version, version_range)
            if in_range is False:
                warning_reasons.append(
                    f"{target_name or 'target'} version {version} is outside {version_range}"
                )
            elif in_range is None:
                unknown_reasons.append(
                    f"could not fully evaluate version range {version_range}"
                )
    elif version_range or compatibility.get("known_incompatible_versions"):
        unknown_reasons.append("current target version is unknown")

    stale_reason = _stale_reason(compatibility, environment)
    if stale_reason:
        stale_reasons.append(stale_reason)

    deprecation_reason = _deprecation_reason(compatibility, environment)
    if deprecation_reason:
        warning_reasons.append(deprecation_reason)

    if incompatible_reasons:
        reasons.extend(incompatible_reasons)
        reasons.extend(stale_reasons)
        reasons.extend(warning_reasons)
        reasons.extend(unknown_reasons)
        return StalenessDecision(
            status="incompatible",
            reasons=reasons,
            required_reverification=True,
            confidence_multiplier=0.0,
        )
    if stale_reasons:
        reasons.extend(stale_reasons)
        reasons.extend(warning_reasons)
        reasons.extend(unknown_reasons)
        return StalenessDecision(
            status="stale",
            reasons=reasons,
            required_reverification=True,
            confidence_multiplier=0.4,
        )
    if warning_reasons:
        reasons.extend(warning_reasons)
        reasons.extend(unknown_reasons)
        return StalenessDecision(
            status="warning",
            reasons=reasons,
            required_reverification=True,
            confidence_multiplier=0.7,
        )
    if unknown_reasons:
        return StalenessDecision(
            status="unknown",
            reasons=unknown_reasons,
            required_reverification=True,
            confidence_multiplier=0.6,
        )

    reasons.append("compatibility metadata matches current environment")
    return StalenessDecision(
        status="fresh",
        reasons=reasons,
        required_reverification=False,
        confidence_multiplier=1.0,
    )


def compatibility_metadata(entry: Any) -> dict[str, Any]:
    """Return normalized compatibility metadata from a procedure-like object."""
    compatibility = _get(entry, "compatibility")
    if compatibility is None:
        compatibility = _get(entry, "environment_compatibility")
    if compatibility is None:
        metadata = _get(entry, "metadata")
        if isinstance(metadata, Mapping):
            compatibility = metadata.get("compatibility")
    if not isinstance(compatibility, Mapping):
        return {}
    return dict(compatibility)


def has_compatibility_metadata(entry: Any) -> bool:
    """Return whether a procedure-like object has Codex compatibility data."""
    return bool(compatibility_metadata(entry))


def apply_staleness_confidence(confidence: float, decision: StalenessDecision) -> float:
    """Apply deterministic confidence decay without mutating the entry."""
    return max(0.0, min(1.0, float(confidence) * decision.confidence_multiplier))


def staleness_guidance_text(decision: StalenessDecision) -> str:
    """Render a compact guidance warning for a staleness decision."""
    reason = "; ".join(decision.reasons) if decision.reasons else "no reason recorded"
    if decision.status == "fresh":
        return f"fresh; {reason}"
    if decision.status == "incompatible":
        return (
            "incompatible; blocked/historical only; do not render as a "
            f"recommended procedure until reverified ({reason})"
        )
    if decision.status == "stale":
        return f"stale; reverify before relying on it ({reason})"
    if decision.status == "warning":
        return f"warning; verify before relying on it ({reason})"
    return f"unknown compatibility; lower confidence and reverify ({reason})"


def _normalize_environment(
    current_environment: Mapping[str, Any] | str | None,
) -> dict[str, Any]:
    if current_environment is None:
        return {}
    if isinstance(current_environment, Mapping):
        return dict(current_environment)
    text = str(current_environment).strip()
    if not text:
        return {}
    environment: dict[str, Any] = {"description": text}
    version_match = re.search(r"\b(\d+(?:\.\d+){0,3})\b", text)
    if version_match:
        environment["version"] = version_match.group(1)
    lowered = text.casefold()
    for name in ("react", "docker", "compose", "node", "npm", "python"):
        if name in lowered:
            environment.setdefault("framework", name)
            environment.setdefault("tool", name)
            break
    return environment


def _compatibility_target(compatibility: Mapping[str, Any]) -> str:
    for key in ("package_name", "framework", "tool"):
        value = _string_value(compatibility.get(key))
        if value:
            return value
    return ""


def _environment_version(environment: Mapping[str, Any], target_name: str) -> str:
    versions = environment.get("versions")
    if isinstance(versions, Mapping):
        for key in _target_aliases(target_name):
            value = _string_value(versions.get(key))
            if value:
                return value
    for key in (
        "version",
        "package_version",
        "framework_version",
        "tool_version",
        f"{target_name}_version" if target_name else "",
    ):
        if key:
            value = _string_value(environment.get(key))
            if value:
                return value
    return ""


def _target_aliases(target_name: str) -> list[str]:
    value = target_name.casefold().strip()
    aliases = [value] if value else []
    if value and "/" in value:
        aliases.append(value.rsplit("/", 1)[-1])
    return aliases


def _stale_reason(
    compatibility: Mapping[str, Any],
    environment: Mapping[str, Any],
) -> str:
    stale_after_days = _int_value(compatibility.get("stale_after_days"))
    if stale_after_days is None:
        return ""
    last_verified_at = _datetime_value(compatibility.get("last_verified_at"))
    if last_verified_at is None:
        return "last_verified_at is missing"
    as_of = _datetime_value(environment.get("as_of")) or datetime.now(timezone.utc)
    age_days = (as_of - last_verified_at).days
    if age_days > stale_after_days:
        return (
            f"last verified {age_days} days ago, beyond stale_after_days={stale_after_days}"
        )
    return ""


def _deprecation_reason(
    compatibility: Mapping[str, Any],
    environment: Mapping[str, Any],
) -> str:
    signals = _string_list(compatibility.get("deprecation_signals"))
    if not signals:
        return ""
    environment_text = _flatten_text(environment).casefold()
    for signal in signals:
        if signal.casefold() in environment_text:
            return f"current environment contains deprecation signal: {signal}"
    return ""


def _version_in_range(version: str, range_expr: str) -> bool | None:
    text = str(range_expr or "").replace(",", " ").strip()
    if not text:
        return True
    tokens = [token.strip() for token in text.split() if token.strip()]
    if not tokens:
        return True
    result: bool | None = True
    for token in tokens:
        match = _version_matches_pattern(version, token)
        if match is None:
            result = None
            continue
        if match is False:
            return False
    return result


def _version_matches_pattern(version: str, pattern: str) -> bool | None:
    parsed = _parse_version(version)
    pattern_text = str(pattern or "").strip()
    if not pattern_text or parsed is None:
        return None
    if pattern_text.startswith("^"):
        base = _parse_version(pattern_text[1:])
        if base is None:
            return None
        major = base[0]
        return _compare_versions(parsed, base) >= 0 and parsed[0] == major
    if pattern_text.startswith("~"):
        base = _parse_version(pattern_text[1:])
        if base is None:
            return None
        return _compare_versions(parsed, base) >= 0 and parsed[:2] == base[:2]
    if "x" in pattern_text.casefold() or "*" in pattern_text:
        parts = re.split(r"[._-]", pattern_text.casefold())
        version_parts = list(parsed)
        for index, part in enumerate(parts):
            if part in {"x", "*", ""}:
                return True
            if not part.isdigit() or index >= len(version_parts):
                return None
            if version_parts[index] != int(part):
                return False
        return True
    operator_match = re.match(
        r"^(>=|<=|>|<|==|=)?\s*v?(\d+(?:\.\d+){0,3})",
        pattern_text,
    )
    if not operator_match:
        return None
    operator = operator_match.group(1) or "="
    target = _parse_version(operator_match.group(2))
    if target is None:
        return None
    comparison = _compare_versions(parsed, target)
    if operator == ">=":
        return comparison >= 0
    if operator == "<=":
        return comparison <= 0
    if operator == ">":
        return comparison > 0
    if operator == "<":
        return comparison < 0
    if "." not in operator_match.group(2) and operator in {"=", "=="}:
        return parsed[0] == target[0]
    return comparison == 0


def _parse_version(value: str) -> tuple[int, ...] | None:
    match = re.search(r"v?(\d+(?:\.\d+){0,3})", str(value or ""))
    if not match:
        return None
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (3 - len(parts))


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    max_len = max(len(left), len(right))
    left_padded = left + (0,) * (max_len - len(left))
    right_padded = right + (0,) * (max_len - len(right))
    return (left_padded > right_padded) - (left_padded < right_padded)


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            tzinfo=timezone.utc,
        )
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_value(value: Any) -> str:
    return str(value or "").strip().casefold()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _get(entry: Any, key: str) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key)
    return getattr(entry, key, None)


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(
            f"{key}: {_flatten_text(value[key])}"
            for key in sorted(value, key=lambda item: str(item))
        )
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_flatten_text(item) for item in value)
    return "" if value is None else str(value)
