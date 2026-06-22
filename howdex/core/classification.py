"""Deterministic intent and side-effect classification for canonical actions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

INTENTS = frozenset(
    {
        "read",
        "search",
        "list",
        "create",
        "update",
        "write",
        "delete",
        "execute",
        "transfer",
        "notify",
        "approve",
        "reject",
        "authenticate",
        "unknown",
    }
)

SIDE_EFFECT_CLASSES = frozenset(
    {
        "read_only",
        "local_write",
        "external_write",
        "destructive",
        "financial",
        "security_sensitive",
        "unknown",
    }
)

_LEGACY_INTENT_ALIASES = {
    "inspect": "read",
    "introspect": "search",
    "repair": "update",
    "install": "execute",
    "deploy": "execute",
    "build": "execute",
}
_MUTATING_INTENTS = {
    "create",
    "update",
    "write",
    "notify",
    "approve",
    "reject",
}
_FINANCIAL_TOKENS = {
    "billing",
    "charge",
    "disburse",
    "funds",
    "invoice",
    "pay",
    "payment",
    "refund",
    "transfer",
    "withdraw",
}
_FINANCIAL_ARGUMENTS = {
    "amount",
    "balance",
    "charge",
    "currency",
    "invoice",
    "payment_intent",
    "price",
}
_DESTRUCTIVE_TOKENS = {
    "delete",
    "destroy",
    "drop",
    "erase",
    "purge",
    "remove",
    "truncate",
    "wipe",
}
_SECURITY_TOKENS = {
    "auth",
    "authenticate",
    "credential",
    "login",
    "permission",
    "role",
    "secret",
    "signin",
    "token",
}
_SECURITY_ARGUMENTS = {
    "api_key",
    "authorization",
    "credential",
    "password",
    "permission",
    "private_key",
    "role",
    "secret",
    "token",
}
_LOCAL_TOKENS = {
    "file",
    "filesystem",
    "fs",
    "local",
    "shell",
    "subprocess",
    "terminal",
}
_LOCAL_ARGUMENTS = {
    "cwd",
    "directory",
    "file",
    "filename",
    "path",
}
_EXTERNAL_ARGUMENTS = {
    "account",
    "channel",
    "customer",
    "email",
    "endpoint",
    "issue",
    "pr",
    "pull_request",
    "repo",
    "repository",
    "url",
    "user",
}


def normalize_intent(intent: str) -> str:
    """Return a value from the public intent ontology."""
    normalized = str(intent or "").strip().lower()
    normalized = _LEGACY_INTENT_ALIASES.get(normalized, normalized)
    return normalized if normalized in INTENTS else "unknown"


def infer_side_effect_class(
    canonical_name: str,
    intent: str,
    arguments: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Classify consequences and return ``(class, matched_rule)``."""
    arguments = arguments or {}
    metadata = metadata or {}
    normalized_intent = normalize_intent(intent)
    hints = _metadata_hints(metadata)

    explicit = str(
        hints.get("side_effect_class")
        or hints.get("side_effect")
        or hints.get("effect_class")
        or ""
    ).strip().lower()
    if explicit in SIDE_EFFECT_CLASSES:
        return explicit, "metadata_side_effect_class"

    if _truthy(hints.get("financial")):
        return "financial", "metadata_financial"
    if _truthy(hints.get("destructive")) or _truthy(
        hints.get("destructive_hint")
    ):
        return "destructive", "metadata_destructive"
    if _truthy(hints.get("security_sensitive")):
        return "security_sensitive", "metadata_security_sensitive"
    if _truthy(hints.get("read_only")) or _truthy(
        hints.get("read_only_hint")
    ) or hints.get("side_effecting") is False:
        return "read_only", "metadata_read_only"

    name_tokens = _tokens(canonical_name)
    argument_names = _argument_names(arguments)
    schema_names = _schema_argument_names(metadata)
    signal_names = argument_names | schema_names

    if (
        normalized_intent == "transfer"
        or name_tokens & _FINANCIAL_TOKENS
        or signal_names & _FINANCIAL_ARGUMENTS
    ):
        return "financial", "financial_intent_or_signal"
    if (
        normalized_intent == "delete"
        or name_tokens & _DESTRUCTIVE_TOKENS
    ):
        return "destructive", "destructive_intent_or_verb"
    if (
        normalized_intent == "authenticate"
        or name_tokens & _SECURITY_TOKENS
        or signal_names & _SECURITY_ARGUMENTS
    ):
        return "security_sensitive", "security_intent_or_signal"
    if normalized_intent in {"read", "search", "list"}:
        return "read_only", "read_intent"

    scope = str(hints.get("scope") or "").strip().lower()
    local_signal = (
        scope == "local"
        or bool(name_tokens & _LOCAL_TOKENS)
        or bool(signal_names & _LOCAL_ARGUMENTS)
    )
    external_signal = (
        scope in {"external", "remote"}
        or bool(signal_names & _EXTERNAL_ARGUMENTS)
    )
    if normalized_intent in _MUTATING_INTENTS:
        if local_signal and not external_signal:
            return "local_write", "local_mutation_signal"
        return "external_write", "mutating_intent"
    if normalized_intent == "execute":
        if local_signal and not external_signal:
            return "local_write", "local_execute_signal"
        if external_signal or hints.get("side_effecting") is True:
            return "external_write", "external_execute_signal"

    return "unknown", "no_side_effect_rule"


def side_effecting_value(side_effect_class: str) -> bool | None:
    """Preserve the legacy nullable side-effect boolean."""
    if side_effect_class == "read_only":
        return False
    if side_effect_class == "unknown":
        return None
    return True


def _metadata_hints(metadata: Mapping[str, Any]) -> dict[str, Any]:
    hints = {
        _camel_to_snake(str(key)): value
        for key, value in metadata.items()
    }
    for container_key in ("annotations", "hints"):
        nested = metadata.get(container_key)
        if isinstance(nested, Mapping):
            for key, value in nested.items():
                normalized = _camel_to_snake(str(key))
                hints.setdefault(normalized, value)
    return hints


def _argument_names(arguments: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for key, value in arguments.items():
        names.add(_camel_to_snake(str(key)).rsplit(".", 1)[-1])
        if isinstance(value, Mapping):
            names.update(_argument_names(value))
    return names


def _schema_argument_names(metadata: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("schema", "input_schema", "parameters"):
        schema = metadata.get(key)
        if isinstance(schema, Mapping):
            names.update(_schema_names(schema))
    return names


def _schema_names(schema: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for key, value in properties.items():
            names.add(_camel_to_snake(str(key)))
            if isinstance(value, Mapping):
                names.update(_schema_names(value))
    for key in ("items", "anyOf", "oneOf", "allOf"):
        child = schema.get(key)
        if isinstance(child, Mapping):
            names.update(_schema_names(child))
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, Mapping):
                    names.update(_schema_names(item))
    return names


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if token
    }


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value is True
