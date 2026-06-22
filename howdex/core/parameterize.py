"""Deterministic parameterisation of canonical agent actions."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from howdex.core.actions import CanonicalAction
from howdex.core.tool_calls import redact_secrets

REDACTED = "[REDACTED]"

_SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:api_?key|access_?key|secret|password|passwd|token|"
    r"authorization|credential|cookie|private_?key|client_?secret)(?:$|_)"
)
_SECRET_FLAG_RE = re.compile(
    r"(?i)(--?(?:api[-_]?key|password|secret|token|authorization)"
    r"(?:=|\s+))([^\s]+)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z][A-Z0-9_]*(?:KEY|SECRET|PASSWORD|TOKEN|CREDENTIAL)"
    r"[A-Z0-9_]*)=([^\s]+)"
)
_SECRET_LABEL_RE = re.compile(
    r"(?i)\b(api[-_ ]?key|password|secret|token|authorization)"
    r"(\s*[:=]\s*)([^\s]+)"
)
_AUTH_BEARER_RE = re.compile(
    r"(?i)(--?authorization\s+bearer\s+)([^\s]+)"
)
_ENV_ASSIGNMENT_RE = re.compile(r"\b([A-Z][A-Z0-9_]*=)([^\s]+)")
_URI_CREDENTIAL_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
_URL_RE = re.compile(r"\b(?:https?|ftp)://[^\s'\"<>]+", re.IGNORECASE)
_EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_HASH_RE = re.compile(r"\b(?:sha(?:1|256|512):)?[0-9a-f]{32,128}\b", re.IGNORECASE)
_PATH_RE = re.compile(
    r"(?<![\w<>])(?:\.{0,2}/|/)?(?:[\w@.-]+/)+[\w@.+-]+"
    r"|(?<![\w<>])[\w@.-]+\.(?:py|js|jsx|ts|tsx|json|yaml|yml|toml|md|sh|sql)"
)
_ISSUE_RE = re.compile(r"(?i)\b(issue\s*#?\s*)(\d+)\b")
_PR_RE = re.compile(r"(?i)\b((?:pr|pull request)\s*#?\s*)(\d+)\b")
_PORT_RE = re.compile(r"(?i)\b(port\s+)(\d{2,5})\b")
_ID_RE = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9][a-z0-9_-]*\b", re.IGNORECASE)

_PACKAGE_COMMANDS = {
    ("npm", "install"),
    ("npm", "i"),
    ("pnpm", "add"),
    ("yarn", "add"),
    ("pip", "install"),
    ("pip3", "install"),
}
_PATH_COMMANDS = {"pytest", "node"}
_URL_COMMANDS = {"curl", "wget"}
_BRANCH_COMMANDS = {
    ("git", "checkout"),
    ("git", "switch"),
}

_KEY_TYPES = {
    "path": "PATH",
    "file": "PATH",
    "filename": "PATH",
    "url": "URL",
    "uri": "URL",
    "endpoint": "URL",
    "port": "PORT",
    "package": "PKG",
    "packages": "PKG",
    "package_name": "PKG",
    "dependency": "PKG",
    "dependencies": "PKG",
    "module": "PKG",
    "repo": "REPO",
    "repository": "REPO",
    "email": "EMAIL",
    "issue": "ISSUE",
    "issue_number": "ISSUE",
    "pr": "PR",
    "pr_number": "PR",
    "pull_request": "PR",
    "branch": "BRANCH",
    "branch_name": "BRANCH",
    "payment_intent": "ID",
    "charge": "ID",
    "id": "ID",
    "uuid": "UUID",
    "hash": "HASH",
    "digest": "HASH",
    "sha": "HASH",
    "sha256": "HASH",
}
_ENV_CONTAINER_KEYS = {
    "env",
    "environment",
    "environment_variables",
    "env_vars",
}


@dataclass(frozen=True)
class ParameterizedAction:
    """A reusable template layered on top of a canonical action."""

    canonical_name: str
    parameterized_action: str
    parameterized_args: dict[str, Any] = field(default_factory=dict)
    parameterized_target: str | None = None
    parameter_map: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _PlaceholderRegistry:
    def __init__(self) -> None:
        self._placeholders: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def placeholder(self, kind: str, value: Any) -> str:
        normalized = _stable_value(value)
        key = (kind, normalized)
        existing = self._placeholders.get(key)
        if existing is not None:
            return existing
        count = self._counts.get(kind, 0) + 1
        self._counts[kind] = count
        placeholder = f"<{kind}_{count}>"
        self._placeholders[key] = placeholder
        return placeholder


def parameterize_action(
    action: CanonicalAction,
    *,
    _registry: _PlaceholderRegistry | None = None,
) -> ParameterizedAction:
    """Parameterise one canonical action with deterministic placeholders."""
    registry = _registry or _PlaceholderRegistry()
    safe_args, redacted_paths = redact_secrets(action.raw_args)
    safe_action = _redact_text(action.raw_action)
    safe_target = _redact_text(action.target)
    parameter_map: dict[str, Any] = {}

    parameterized_action = _parameterize_command(
        safe_action or action.canonical_name,
        registry,
        parameter_map,
    )
    parameterized_args = _parameterize_value(
        safe_args,
        registry,
        parameter_map,
    )
    parameterized_target = _parameterize_target(
        safe_target,
        registry,
        parameter_map,
    )
    if parameterized_target is not None:
        parameterized_target = str(parameterized_target)

    return ParameterizedAction(
        canonical_name=action.canonical_name,
        parameterized_action=parameterized_action,
        parameterized_args=parameterized_args,
        parameterized_target=parameterized_target,
        parameter_map=dict(sorted(parameter_map.items())),
        provenance={
            "source": "deterministic_parameterization",
            "raw_action": safe_action,
            "raw_args": safe_args,
            "target": safe_target,
            "redacted_argument_paths": redacted_paths,
        },
    )


def parameterize_steps(
    steps: list[CanonicalAction],
) -> list[ParameterizedAction]:
    """Parameterise a canonical sequence using one stable placeholder registry."""
    registry = _PlaceholderRegistry()
    return [
        parameterize_action(step, _registry=registry)
        for step in steps
    ]


def parameter_bindings(
    steps: list[ParameterizedAction],
) -> dict[str, Any]:
    """Collect safe example bindings from a parameterised sequence."""
    bindings: dict[str, Any] = {}
    for step in steps:
        bindings.update(step.parameter_map)
    return {key: bindings[key] for key in sorted(bindings)}


def redact_parameter_evidence(value: Any) -> Any:
    """Redact secret keys and shell-like secret literals without templating."""
    redacted, _ = redact_secrets(value)
    if isinstance(redacted, Mapping):
        return {
            str(key): redact_parameter_evidence(redacted[key])
            for key in sorted(redacted, key=lambda item: str(item))
        }
    if isinstance(redacted, list):
        return [redact_parameter_evidence(item) for item in redacted]
    if isinstance(redacted, tuple):
        return [redact_parameter_evidence(item) for item in redacted]
    if isinstance(redacted, str):
        return _redact_text(redacted)
    return redacted


def _parameterize_command(
    command: str,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
) -> str:
    command = _redact_text(command) or ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return command

    lowered = [token.lower() for token in tokens]
    pair = tuple(lowered[:2]) if len(lowered) >= 2 else ()
    if pair in _PACKAGE_COMMANDS:
        for index in range(2, len(tokens)):
            if tokens[index].startswith("-") or tokens[index] == REDACTED:
                continue
            tokens[index] = _bind("PKG", tokens[index], registry, parameter_map)
        return " ".join(tokens)

    executable = lowered[0]
    if executable in _PATH_COMMANDS:
        for index in range(1, len(tokens)):
            if tokens[index].startswith("-") or tokens[index] == REDACTED:
                continue
            tokens[index] = _bind("PATH", tokens[index], registry, parameter_map)
            break
        return " ".join(tokens)

    if executable in _URL_COMMANDS:
        for index in range(1, len(tokens)):
            if tokens[index].startswith("-") or tokens[index] == REDACTED:
                continue
            tokens[index] = _bind("URL", tokens[index], registry, parameter_map)
            break
        return " ".join(tokens)

    if pair in _BRANCH_COMMANDS:
        for index in range(2, len(tokens)):
            if tokens[index].startswith("-") or tokens[index] == REDACTED:
                continue
            tokens[index] = _bind("BRANCH", tokens[index], registry, parameter_map)
            break
        return " ".join(tokens)

    return _parameterize_text(command, registry, parameter_map)


def _parameterize_value(
    value: Any,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
    *,
    parent_key: str | None = None,
) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            key_text = str(key)
            item = value[key]
            if _is_secret_key(key_text):
                output[key_text] = REDACTED
                continue
            if str(parent_key or "").lower() in _ENV_CONTAINER_KEYS:
                output[key_text] = _parameterize_scalar(
                    item,
                    key="env_value",
                    registry=registry,
                    parameter_map=parameter_map,
                )
                continue
            output[key_text] = _parameterize_value(
                item,
                registry,
                parameter_map,
                parent_key=key_text,
            )
        return output
    if isinstance(value, (list, tuple)):
        return [
            _parameterize_value(
                item,
                registry,
                parameter_map,
                parent_key=parent_key,
            )
            for item in value
        ]
    return _parameterize_scalar(
        value,
        key=parent_key,
        registry=registry,
        parameter_map=parameter_map,
    )


def _parameterize_target(
    value: str | None,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
) -> str | None:
    if value is None:
        return None
    parts = value.split(";")
    if all("=" in part for part in parts):
        output = []
        for part in parts:
            key, raw_value = part.split("=", 1)
            parameterized = _parameterize_scalar(
                raw_value,
                key=key.rsplit(".", 1)[-1],
                registry=registry,
                parameter_map=parameter_map,
            )
            output.append(f"{key}={parameterized}")
        return ";".join(output)
    parameterized = _parameterize_scalar(
        value,
        key=None,
        registry=registry,
        parameter_map=parameter_map,
    )
    return None if parameterized is None else str(parameterized)


def _parameterize_scalar(
    value: Any,
    *,
    key: str | None,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
) -> Any:
    if value is None or isinstance(value, bool):
        return value
    key_text = str(key or "")
    key_normalized = key_text.lower()
    kind = (
        "ENV_VALUE"
        if key_text and key_text == key_text.upper() and "_" in key_text
        else _kind_for_key(key_normalized)
    )
    if kind is None and isinstance(value, str):
        kind = _kind_for_value(value)
    if kind is not None:
        return _bind(kind, value, registry, parameter_map)
    if isinstance(value, str):
        return _parameterize_text(value, registry, parameter_map)
    return value


def _parameterize_text(
    value: str,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
) -> str:
    text = _redact_text(value) or ""
    text = _replace_matches(text, _URL_RE, "URL", registry, parameter_map)
    text = _replace_matches(text, _EMAIL_RE, "EMAIL", registry, parameter_map)
    text = _replace_matches(text, _UUID_RE, "UUID", registry, parameter_map)
    text = _replace_matches(text, _HASH_RE, "HASH", registry, parameter_map)
    text = _replace_group(text, _PR_RE, "PR", registry, parameter_map)
    text = _replace_group(text, _ISSUE_RE, "ISSUE", registry, parameter_map)
    text = _replace_group(text, _PORT_RE, "PORT", registry, parameter_map)
    text = _replace_matches(text, _PATH_RE, "PATH", registry, parameter_map)
    text = _ENV_ASSIGNMENT_RE.sub(
        lambda match: (
            match.group(0)
            if match.group(2) == REDACTED
            else match.group(1)
            + _bind(
                "ENV_VALUE",
                match.group(2),
                registry,
                parameter_map,
            )
        ),
        text,
    )
    return text


def _replace_matches(
    text: str,
    pattern: re.Pattern[str],
    kind: str,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
) -> str:
    return pattern.sub(
        lambda match: _bind(
            kind,
            match.group(0),
            registry,
            parameter_map,
        ),
        text,
    )


def _replace_group(
    text: str,
    pattern: re.Pattern[str],
    kind: str,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
) -> str:
    return pattern.sub(
        lambda match: (
            match.group(1)
            + _bind(
                kind,
                match.group(2),
                registry,
                parameter_map,
            )
        ),
        text,
    )


def _bind(
    kind: str,
    value: Any,
    registry: _PlaceholderRegistry,
    parameter_map: dict[str, Any],
) -> str:
    placeholder = registry.placeholder(kind, value)
    parameter_map.setdefault(placeholder, value)
    return placeholder


def _kind_for_key(key: str) -> str | None:
    if _is_secret_key(key):
        return None
    if key in _KEY_TYPES:
        return _KEY_TYPES[key]
    if key == "env_value" or key.endswith("_value"):
        return "ENV_VALUE"
    if key.endswith("_path") or key.endswith("_file"):
        return "PATH"
    if key.endswith("_url") or key.endswith("_uri"):
        return "URL"
    if key.endswith("_port"):
        return "PORT"
    if key.endswith("_uuid"):
        return "UUID"
    if key.endswith("_hash") or key.endswith("_digest"):
        return "HASH"
    if key.endswith("_email"):
        return "EMAIL"
    if key.endswith("_id"):
        return "ID"
    return None


def _kind_for_value(value: str) -> str | None:
    if _URL_RE.fullmatch(value):
        return "URL"
    if _EMAIL_RE.fullmatch(value):
        return "EMAIL"
    if _UUID_RE.fullmatch(value):
        return "UUID"
    if _HASH_RE.fullmatch(value):
        return "HASH"
    if _PATH_RE.fullmatch(value):
        return "PATH"
    if _ID_RE.fullmatch(value):
        return "ID"
    return None


def _redact_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    text = _AUTH_BEARER_RE.sub(r"\1" + REDACTED, text)
    text = _SECRET_FLAG_RE.sub(r"\1" + REDACTED, text)
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1=" + REDACTED, text)
    text = _SECRET_LABEL_RE.sub(
        lambda match: match.group(1) + match.group(2) + REDACTED,
        text,
    )
    return _URI_CREDENTIAL_RE.sub(r"\1" + REDACTED + r"\3", text)


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key.replace("-", "_")))


def _stable_value(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
