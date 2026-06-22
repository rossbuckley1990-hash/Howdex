"""Deterministic canonicalisation for structured agent tool calls."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from howdex.core.actions import CanonicalAction
from howdex.core.classification import (
    INTENTS,
    SIDE_EFFECT_CLASSES,
    infer_side_effect_class,
    normalize_intent,
    side_effecting_value,
)

_SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:api_?key|access_?key|secret|password|passwd|token|"
    r"authorization|credential|cookie|private_?key|client_?secret)(?:$|_)",
    re.IGNORECASE,
)
_NAMESPACE_SEPARATOR_RE = re.compile(r"(?:::|/|\\)+")
_INVALID_NAME_RE = re.compile(r"[^a-z0-9._]+")
_REPEATED_UNDERSCORE_RE = re.compile(r"_+")
_REPEATED_DOT_RE = re.compile(r"\.+")

_TARGET_KEY_PRIORITY = (
    "repository",
    "repo",
    "pull_request",
    "pr",
    "issue",
    "path",
    "file",
    "filename",
    "url",
    "resource",
    "object",
    "table",
    "key",
    "customer",
    "account",
    "user",
    "email",
    "patient",
    "medication",
    "project",
    "dataset",
    "payment_intent",
    "charge",
    "id",
    "name",
)
_TEXT_PAYLOAD_KEYS = {
    "body",
    "content",
    "description",
    "message",
    "prompt",
    "query",
    "text",
    "title",
}

_INTENT_VERBS = {
    "read": {
        "read",
        "get",
        "fetch",
        "retrieve",
        "inspect",
        "view",
        "download",
        "show",
    },
    "search": {"search", "find", "query", "lookup", "locate", "grep"},
    "list": {"list", "enumerate", "browse"},
    "create": {"create", "add", "new", "provision", "open"},
    "update": {"update", "edit", "patch", "modify", "change", "set"},
    "write": {"write", "save", "put", "upsert", "upload", "store"},
    "delete": {
        "delete",
        "remove",
        "destroy",
        "drop",
        "purge",
        "revoke",
        "cancel",
    },
    "execute": {
        "run",
        "execute",
        "invoke",
        "call",
        "apply",
        "administer",
        "deploy",
        "build",
        "test",
    },
    "transfer": {
        "transfer",
        "refund",
        "pay",
        "charge",
        "disburse",
        "withdraw",
        "deposit",
    },
    "notify": {
        "notify",
        "send",
        "email",
        "message",
        "alert",
        "publish",
        "announce",
    },
    "approve": {"approve", "accept", "confirm", "authorize"},
    "reject": {"reject", "deny", "decline", "disapprove"},
    "authenticate": {
        "authenticate",
        "login",
        "signin",
        "verify",
        "validate",
    },
}


def canonicalize_tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> CanonicalAction:
    """Canonicalise a typed tool/function call without domain-specific mappings."""
    raw_name = str(name or "").strip()
    raw_arguments = dict(arguments or {})
    raw_metadata = dict(metadata or {})
    canonical_name = normalize_tool_name(raw_name)
    redacted_args, redacted_paths = redact_secrets(raw_arguments)
    intent, intent_rule = infer_intent(
        canonical_name,
        raw_metadata,
        redacted_args,
    )
    target, target_rule = project_target(redacted_args, raw_metadata)
    source = str(
        raw_metadata.get("source")
        or raw_metadata.get("framework")
        or raw_metadata.get("provider")
        or "structured_tool_call"
    )
    side_effect_class, side_effect_rule = infer_side_effect_class(
        canonical_name,
        intent,
        redacted_args,
        raw_metadata,
    )
    side_effecting = side_effecting_value(side_effect_class)
    confidence = _structured_confidence(
        canonical_name=canonical_name,
        intent=intent,
        target_rule=target_rule,
        metadata=raw_metadata,
    )

    return CanonicalAction(
        raw_action=raw_name,
        canonical_name=canonical_name or "unknown_tool",
        intent=intent,
        target=target,
        confidence=confidence,
        evidence={
            "intent_rule": intent_rule,
            "target_rule": target_rule,
            "side_effect_rule": side_effect_rule,
            "side_effecting": side_effecting,
            "redacted_argument_paths": redacted_paths,
        },
        raw_name=raw_name,
        raw_args=redacted_args,
        provenance={
            "source": source,
            "call_id": raw_metadata.get("call_id")
            or raw_metadata.get("tool_call_id")
            or raw_metadata.get("id"),
            "schema_name": raw_metadata.get("schema_name"),
        },
        matched_by="structured_tool_call",
        side_effect_class=side_effect_class,
    )


def normalize_tool_name(name: str) -> str:
    """Normalize tool names while retaining useful dotted namespaces."""
    normalized = str(name or "").strip().lower()
    normalized = _NAMESPACE_SEPARATOR_RE.sub(".", normalized)
    normalized = normalized.replace("-", "_")
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = _INVALID_NAME_RE.sub("_", normalized)
    normalized = _REPEATED_UNDERSCORE_RE.sub("_", normalized)
    normalized = _REPEATED_DOT_RE.sub(".", normalized)
    return normalized.strip("._")


def project_target(
    arguments: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Project a stable, redacted target from typed arguments."""
    metadata = metadata or {}
    explicit_keys = _metadata_target_keys(metadata)
    flattened = _flatten_scalars(arguments)

    if explicit_keys:
        selected = [
            (key, flattened[key])
            for key in explicit_keys
            if key in flattened and not _is_secret_key(key)
        ]
        if selected:
            return _format_target(selected[:3]), "metadata_primary_argument"

    selected = _select_salient_arguments(flattened)
    if selected:
        return _format_target(selected[:3]), "salient_argument"

    canonical_json = json.dumps(
        arguments,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:16]
    return f"args:sha256:{digest}", "canonical_arguments_hash"


def infer_intent(
    canonical_name: str,
    metadata: dict[str, Any] | None = None,
    arguments: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Infer a small open intent ontology from metadata and tool-name verbs."""
    metadata = metadata or {}
    arguments = arguments or {}
    explicit = str(
        metadata.get("intent")
        or metadata.get("operation")
        or metadata.get("verb")
        or ""
    ).strip().lower()
    if explicit in INTENTS:
        return explicit, "metadata_intent"
    if explicit:
        for intent, verbs in _INTENT_VERBS.items():
            if explicit in verbs:
                return intent, f"metadata_verb:{explicit}"

    tokens = [
        token
        for segment in canonical_name.split(".")
        for token in segment.split("_")
        if token
    ]
    for token in reversed(tokens):
        for intent, verbs in _INTENT_VERBS.items():
            if token in verbs:
                return intent, f"tool_name_verb:{token}"

    if metadata.get("read_only") is True or metadata.get("side_effecting") is False:
        return "read", "metadata_read_only"
    annotations = metadata.get("annotations")
    if isinstance(annotations, Mapping) and (
        annotations.get("readOnlyHint") is True
        or annotations.get("read_only_hint") is True
    ):
        return "read", "metadata_read_only_annotation"
    schema_names = _schema_argument_names(metadata)
    argument_names = {
        path.rsplit(".", 1)[-1].lower()
        for path in _flatten_scalars(arguments)
    }
    signal_names = schema_names | argument_names
    if signal_names & {"query", "search", "search_query"}:
        return "search", "argument_or_schema_query"
    if signal_names & {"message", "channel", "recipient"}:
        return "notify", "argument_or_schema_notification"
    return "unknown", "no_intent_rule"


def redact_secrets(value: Any) -> tuple[Any, list[str]]:
    """Return a JSON-safe structure with obvious secret values redacted."""
    redacted_paths: list[str] = []

    def visit(item: Any, path: str) -> Any:
        if isinstance(item, Mapping):
            output: dict[str, Any] = {}
            for key in sorted(item, key=lambda candidate: str(candidate)):
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _is_secret_key(key_text):
                    output[key_text] = "[REDACTED]"
                    redacted_paths.append(child_path)
                else:
                    output[key_text] = visit(item[key], child_path)
            return output
        if isinstance(item, (list, tuple)):
            return [
                visit(child, f"{path}[{index}]")
                for index, child in enumerate(item)
            ]
        if item is None or isinstance(item, (bool, int, float, str)):
            return item
        return str(item)

    return visit(value, ""), redacted_paths


def tool_call_from_step(step: Any) -> CanonicalAction | None:
    """Extract common OpenAI/Anthropic/LangChain/MCP call shapes from a step."""
    if not isinstance(step, Mapping):
        return None

    stored_canonical_name = step.get("canonical_action")
    stored_tool_name = step.get("tool_name")
    if stored_canonical_name and stored_tool_name:
        arguments = _arguments_dict(
            step.get("tool_args", step.get("arguments"))
        ) or {}
        evidence_value = step.get("canonical_evidence")
        evidence = (
            dict(evidence_value)
            if isinstance(evidence_value, Mapping)
            else {}
        )
        observation = step.get("observation")
        if observation:
            evidence.setdefault("observation", str(observation))
        provenance_value = step.get("provenance")
        provenance = (
            dict(provenance_value)
            if isinstance(provenance_value, Mapping)
            else {}
        )
        if not provenance:
            metadata = _step_metadata(step)
            provenance = {
                "source": metadata.get("source")
                or metadata.get("framework")
                or metadata.get("provider")
                or "structured_tool_call",
                "call_id": metadata.get("call_id")
                or metadata.get("tool_call_id")
                or metadata.get("id"),
                "schema_name": metadata.get("schema_name"),
            }
        try:
            confidence = float(step.get("canonical_confidence", 0.9))
        except (TypeError, ValueError):
            confidence = 0.9
        metadata = _step_metadata(step)
        stored_intent = normalize_intent(str(step.get("intent") or "unknown"))
        stored_side_effect = str(step.get("side_effect_class") or "")
        if stored_side_effect in SIDE_EFFECT_CLASSES:
            side_effect_class = stored_side_effect
            side_effect_rule = "stored_side_effect_class"
        else:
            side_effect_class, side_effect_rule = infer_side_effect_class(
                str(stored_canonical_name),
                stored_intent,
                arguments,
                metadata,
            )
        evidence.setdefault("side_effect_rule", side_effect_rule)
        evidence.setdefault(
            "side_effecting",
            side_effecting_value(side_effect_class),
        )
        return CanonicalAction(
            raw_action=str(step.get("action") or stored_tool_name),
            canonical_name=normalize_tool_name(str(stored_canonical_name))
            or "unknown_tool",
            intent=stored_intent,
            target=(
                str(step["target"])
                if step.get("target") is not None
                else None
            ),
            confidence=max(0.0, min(1.0, confidence)),
            evidence=evidence,
            raw_name=str(stored_tool_name),
            raw_args=arguments,
            provenance=provenance,
            matched_by="structured_tool_call",
            side_effect_class=side_effect_class,
        )

    function = step.get("function")
    if isinstance(function, Mapping):
        name = function.get("name")
        arguments = _arguments_dict(function.get("arguments"))
        if name and arguments is not None:
            return canonicalize_tool_call(
                str(name),
                arguments,
                _step_metadata(step, framework_default="openai"),
            )

    tool_call = step.get("tool_call")
    if isinstance(tool_call, Mapping):
        name = tool_call.get("name") or tool_call.get("tool_name")
        arguments = _arguments_dict(
            tool_call.get("arguments")
            or tool_call.get("args")
            or tool_call.get("input")
        )
        if name and arguments is not None:
            metadata = _step_metadata(step)
            metadata.setdefault("call_id", tool_call.get("id"))
            return canonicalize_tool_call(str(name), arguments, metadata)

    name = step.get("tool_name") or step.get("tool")
    arguments_value = (
        step.get("arguments")
        if "arguments" in step
        else step.get(
            "tool_args",
            step.get("tool_input", step.get("args", step.get("input"))),
        )
    )
    if name is None and arguments_value is not None:
        name = step.get("name")
    arguments = _arguments_dict(arguments_value)
    if name and arguments is not None:
        return canonicalize_tool_call(
            str(name),
            arguments,
            _step_metadata(step),
        )

    if "arguments" in step and step.get("action"):
        arguments = _arguments_dict(step.get("arguments"))
        if arguments is not None:
            return canonicalize_tool_call(
                str(step["action"]),
                arguments,
                _step_metadata(step),
            )

    return None


def _arguments_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return dict(decoded) if isinstance(decoded, Mapping) else None
    return None


def _step_metadata(
    step: Mapping[str, Any],
    *,
    framework_default: str | None = None,
) -> dict[str, Any]:
    metadata_value = step.get("tool_metadata", step.get("metadata"))
    metadata = (
        dict(metadata_value)
        if isinstance(metadata_value, Mapping)
        else {}
    )
    for key in (
        "source",
        "framework",
        "provider",
        "intent",
        "operation",
        "verb",
        "read_only",
        "side_effecting",
        "side_effect_class",
        "schema",
        "input_schema",
        "parameters",
        "annotations",
        "hints",
        "call_id",
        "tool_call_id",
        "id",
        "primary_argument",
        "target_argument",
        "resource_argument",
    ):
        if key in step and key not in metadata:
            metadata[key] = step[key]
    if framework_default and not any(
        key in metadata for key in ("source", "framework", "provider")
    ):
        metadata["framework"] = framework_default
    return metadata


def _metadata_target_keys(metadata: Mapping[str, Any]) -> list[str]:
    value = (
        metadata.get("primary_argument")
        or metadata.get("target_argument")
        or metadata.get("resource_argument")
    )
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _flatten_scalars(
    value: Any,
    *,
    prefix: str = "",
) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if not isinstance(value, Mapping):
        return flattened
    for key in sorted(value, key=lambda candidate: str(candidate)):
        key_text = str(key)
        path = f"{prefix}.{key_text}" if prefix else key_text
        child = value[key]
        if isinstance(child, Mapping):
            flattened.update(_flatten_scalars(child, prefix=path))
        elif child is None or isinstance(child, (bool, int, float, str)):
            flattened[path] = child
    return flattened


def _select_salient_arguments(
    flattened: dict[str, Any],
) -> list[tuple[str, Any]]:
    scored: list[tuple[int, str, Any]] = []
    priority = {
        key: index
        for index, key in enumerate(_TARGET_KEY_PRIORITY)
    }
    for path, value in flattened.items():
        leaf = path.rsplit(".", 1)[-1].lower()
        if _is_secret_key(leaf) or leaf in _TEXT_PAYLOAD_KEYS:
            continue
        if value in (None, "", "[REDACTED]"):
            continue
        if leaf in priority:
            scored.append((priority[leaf], path, value))
        elif leaf.endswith("_id") or leaf.endswith("id"):
            scored.append((len(priority) + 1, path, value))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [(path, value) for _, path, value in scored]


def _format_target(selected: list[tuple[str, Any]]) -> str:
    return ";".join(
        f"{path}={_target_value(value)}"
        for path, value in selected
    )


def _target_value(value: Any) -> str:
    if isinstance(value, str):
        normalized = " ".join(value.split())
    else:
        normalized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return normalized[:160]


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
    return bool(_SECRET_KEY_RE.search(normalized))


def _schema_argument_names(metadata: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for schema_key in ("schema", "input_schema", "parameters"):
        schema = metadata.get(schema_key)
        if not isinstance(schema, Mapping):
            continue
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            names.update(str(key).lower() for key in properties)
    return names


def _structured_confidence(
    *,
    canonical_name: str,
    intent: str,
    target_rule: str,
    metadata: Mapping[str, Any],
) -> float:
    confidence = 0.72
    if canonical_name and canonical_name != "unknown_tool":
        confidence += 0.10
    if intent != "unknown":
        confidence += 0.10
    if target_rule != "canonical_arguments_hash":
        confidence += 0.05
    if any(key in metadata for key in ("intent", "operation", "verb")):
        confidence += 0.03
    return round(min(0.99, confidence), 4)
