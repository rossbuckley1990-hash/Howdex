"""Deterministic canonicalisation for messy software-agent action traces."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from howdex.core.classification import infer_side_effect_class, normalize_intent

_SPACE_RE = re.compile(r"\s+")
_PATH_RE = re.compile(
    r"(?:^|\s)(?P<path>(?:\.{0,2}/)?[\w@.-]+(?:/[\w@.-]+)*\.[a-z0-9]+)(?:\s|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CanonicalAction:
    """An inspectable deterministic interpretation of one raw action."""

    raw_action: str
    canonical_name: str
    intent: str
    target: str | None
    confidence: float
    evidence: dict[str, Any]
    raw_name: str | None = None
    raw_args: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    matched_by: str = "legacy_prose"
    side_effect_class: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonicalize_action(
    action: str,
    observation: str | None = None,
) -> CanonicalAction:
    """Map a raw software-agent action to a stable local action vocabulary."""
    raw_action = str(action or "").strip()
    raw_observation = str(observation or "").strip()
    normalized = _normalize(raw_action)
    combined = f"{normalized} {_normalize(raw_observation)}".strip()

    if _is_internal_memory_action(normalized):
        return _canonical(
            raw_action,
            "internal_memory_action",
            "introspect",
            "agent_memory",
            1.0,
            "internal_memory_action",
            observation=raw_observation,
        )

    if _mentions_package_manifest(combined) and _has_any(
        normalized,
        "fix",
        "update",
        "patch",
        "edit",
        "repair",
        "restore",
    ) and _has_any(combined, "test", "script", "command"):
        return _canonical(
            raw_action,
            "repair_test_command",
            "repair",
            "package.json:test",
            0.99,
            "repair_package_test_command",
            observation=raw_observation,
        )

    if _mentions_package_manifest(combined) and _has_any(
        normalized,
        "inspect",
        "read",
        "open",
        "check",
        "view",
        "cat",
    ):
        return _canonical(
            raw_action,
            "inspect_package_manifest",
            "inspect",
            "package.json",
            0.99,
            "inspect_package_manifest",
            observation=raw_observation,
        )

    if _is_test_action(combined):
        return _canonical(
            raw_action,
            "run_test_suite",
            "execute",
            _test_target(combined),
            0.98,
            "run_test_suite",
            observation=raw_observation,
        )

    if _is_dependency_install(combined):
        return _canonical(
            raw_action,
            "install_dependencies",
            "install",
            _dependency_target(combined),
            0.98,
            "install_dependencies",
            observation=raw_observation,
        )

    if _has_any(normalized, "inspect", "read", "open", "check", "view", "tail") and _has_any(
        combined,
        "error",
        "errors",
        "log",
        "logs",
        "traceback",
        "stack trace",
        "failure output",
    ):
        return _canonical(
            raw_action,
            "inspect_error",
            "inspect",
            "error_output",
            0.96,
            "inspect_error",
            observation=raw_observation,
        )

    if _has_any(normalized, "migrate", "migration") and _has_any(
        normalized,
        "run",
        "apply",
        "execute",
    ):
        return _canonical(
            raw_action,
            "run_database_migration",
            "execute",
            "database_migration",
            0.94,
            "run_database_migration",
            observation=raw_observation,
        )

    if _has_any(normalized, "deploy", "ship", "release") and not _has_any(
        normalized,
        "inspect",
        "check",
        "read",
    ):
        return _canonical(
            raw_action,
            "deploy_service",
            "deploy",
            _target_after_verb(normalized, ("deploy", "ship", "release")) or "service",
            0.92,
            "deploy_service",
            observation=raw_observation,
        )

    if _has_any(normalized, "build", "compile", "package") and _has_any(
        combined,
        "image",
        "artifact",
        "binary",
        "package",
        "build",
    ):
        return _canonical(
            raw_action,
            "build_artifact",
            "build",
            _target_after_verb(normalized, ("build", "compile", "package")) or "artifact",
            0.90,
            "build_artifact",
            observation=raw_observation,
        )

    if _has_any(normalized, "fix", "update", "patch", "edit", "repair", "restore") and (
        _mentions_file(combined) or "config" in combined or "syntax" in combined
    ):
        return _canonical(
            raw_action,
            "repair_file",
            "repair",
            _extract_target(raw_action, fallback="file"),
            0.88,
            "repair_file",
            observation=raw_observation,
        )

    if _has_any(normalized, "inspect", "read", "open", "check", "view", "cat") and (
        _mentions_file(combined)
        or "config" in combined
        or "manifest" in combined
        or "database url" in combined
        or "database_url" in combined
    ):
        target = _extract_target(raw_action, fallback="file")
        if "database url" in combined or "database_url" in combined:
            target = "DATABASE_URL"
        return _canonical(
            raw_action,
            "inspect_file",
            "inspect",
            target,
            0.88,
            "inspect_file",
            observation=raw_observation,
        )

    return _canonical(
        raw_action,
        "unknown_action",
        "unknown",
        None,
        0.15,
        "no_rule_matched",
        observation=raw_observation,
    )


def canonicalize_steps(steps: list[Any]) -> list[CanonicalAction]:
    """Canonicalise trace steps, preferring structured tool-call fields."""
    from howdex.core.tool_calls import tool_call_from_step

    canonical: list[CanonicalAction] = []
    for step in steps:
        structured = tool_call_from_step(step)
        if structured is not None:
            canonical.append(structured)
            continue
        action, observation = _step_parts(step)
        canonical.append(canonicalize_action(action, observation))
    return canonical


def canonical_sequence_similarity(
    left: list[str],
    right: list[str],
) -> float:
    """Return deterministic sequence similarity in ``[0, 1]``.

    Exact canonical sequences score 1. Otherwise the score combines ordered
    subsequence overlap and Jaccard overlap over canonical action names.
    """
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    lcs = _lcs_length(left, right)
    subsequence_overlap = lcs / min(len(left), len(right))
    union = set(left) | set(right)
    jaccard = len(set(left) & set(right)) / len(union) if union else 0.0
    return round((0.65 * subsequence_overlap) + (0.35 * jaccard), 6)


def _canonical(
    raw_action: str,
    canonical_name: str,
    intent: str,
    target: str | None,
    confidence: float,
    rule: str,
    *,
    observation: str,
) -> CanonicalAction:
    normalized_intent = normalize_intent(intent)
    side_effect_arguments: dict[str, Any] = {}
    if target and canonical_name in {
        "inspect_file",
        "inspect_package_manifest",
        "repair_file",
        "repair_test_command",
    }:
        side_effect_arguments["path"] = target
    side_effect_class, side_effect_rule = infer_side_effect_class(
        canonical_name,
        normalized_intent,
        side_effect_arguments,
    )
    evidence: dict[str, Any] = {
        "rule": rule,
        "normalized_action": _normalize(raw_action),
        "side_effect_rule": side_effect_rule,
    }
    if observation:
        evidence["observation"] = observation
    return CanonicalAction(
        raw_action=raw_action,
        canonical_name=canonical_name,
        intent=normalized_intent,
        target=target,
        confidence=confidence,
        evidence=evidence,
        raw_name=raw_action,
        provenance={"source": "legacy_prose"},
        matched_by="legacy_prose",
        side_effect_class=side_effect_class,
    )


def _normalize(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("_", " ").replace("-", " ")
    return _SPACE_RE.sub(" ", normalized)


def _step_parts(step: Any) -> tuple[str, str | None]:
    if isinstance(step, str):
        return step, None
    if isinstance(step, dict):
        action = (
            step.get("action")
            or step.get("name")
            or step.get("tool")
            or step.get("tool_name")
            or ""
        )
        observation = (
            step.get("observation")
            or step.get("output")
            or step.get("result")
            or step.get("content")
        )
        return str(action), None if observation is None else str(observation)
    action = (
        getattr(step, "action", None)
        or getattr(step, "name", None)
        or getattr(step, "tool", None)
        or getattr(step, "tool_name", None)
        or ""
    )
    observation = (
        getattr(step, "observation", None)
        or getattr(step, "output", None)
        or getattr(step, "result", None)
        or getattr(step, "content", None)
    )
    return str(action), None if observation is None else str(observation)


def _is_internal_memory_action(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    if compact in {
        "recall",
        "searchmemory",
        "recallmemory",
        "inspecthowdex",
        "howdexsearch",
        "howdexremember",
        "howdexlearn",
        "memorylookup",
        "lookupmemory",
        "retrievememory",
        "loadprocedure",
    }:
        return True
    return (
        ("memory" in normalized or "howdex" in normalized)
        and _has_any(normalized, "inspect", "lookup", "search", "retrieve", "recall")
    )


def _mentions_package_manifest(value: str) -> bool:
    return "package.json" in value or "package json" in value or "package manifest" in value


def _is_test_action(value: str) -> bool:
    compact = value.replace(" ", "")
    return (
        "npm test" in value
        or "npmtest" in compact
        or "pytest" in compact
        or "run tests" in value
        or "run test suite" in value
        or "execute tests" in value
        or "test suite" in value
        or compact in {"runtests", "test"}
    )


def _test_target(value: str) -> str:
    compact = value.replace(" ", "")
    if "pytest" in compact:
        return "pytest"
    if "npm test" in value or "npmtest" in compact:
        return "npm test"
    return "test_suite"


def _is_dependency_install(value: str) -> bool:
    compact = value.replace(" ", "")
    return (
        "npm install" in value
        or "npminstall" in compact
        or "pip install" in value
        or "pipinstall" in compact
        or "install dependencies" in value
        or compact in {"installdeps", "installdependencies"}
    )


def _dependency_target(value: str) -> str:
    compact = value.replace(" ", "")
    if "npm install" in value or "npminstall" in compact:
        return "npm"
    if "pip install" in value or "pipinstall" in compact:
        return "pip"
    return "dependencies"


def _mentions_file(value: str) -> bool:
    normalized = _normalize(value)
    return (
        "file" in normalized
        or bool(_PATH_RE.search(f" {value} "))
        or any(
            token in normalized
            for token in ("json config", "yaml", "yml", "toml", "dockerfile")
        )
    )


def _extract_target(value: str, *, fallback: str) -> str:
    match = _PATH_RE.search(f" {value.strip()} ")
    if match:
        return match.group("path")
    normalized = _normalize(value)
    for token in (
        "target file",
        "migration file",
        "json config",
        "config",
        "manifest",
        "file",
    ):
        if token in normalized:
            return token.replace(" ", "_")
    return fallback


def _target_after_verb(value: str, verbs: tuple[str, ...]) -> str | None:
    words = value.split()
    for verb in verbs:
        if verb in words:
            index = words.index(verb)
            target = " ".join(words[index + 1 :]).strip()
            return target or None
    return None


def _has_any(value: str, *terms: str) -> bool:
    return any(term in value for term in terms)


def _lcs_length(left: list[str], right: list[str]) -> int:
    previous = [0] * (len(right) + 1)
    for left_item in left:
        current = [0]
        for index, right_item in enumerate(right, start=1):
            if left_item == right_item:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]
