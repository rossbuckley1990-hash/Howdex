"""Deterministic operational-fact and verification extraction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from howdex.core.guidance_artifacts import (
    extract_observation,
    raw_examples,
)
from howdex.core.guidance_utils import get_value, unique_strings


@dataclass(frozen=True)
class OperationalDataFlow:
    """Binding-aware operational dependencies inferred from trace evidence."""

    steps: list[str] = field(default_factory=list)
    execution_hints: list[str] = field(default_factory=list)


def learned_facts(procedure: Any) -> list[str]:
    facts: list[str] = []
    for key in (
        "learned_facts",
        "operational_facts",
        "semantic_facts",
        "facts",
        "preconditions",
    ):
        facts.extend(unique_strings(get_value(procedure, key)))

    lower = _trace_text(procedure).lower()
    facts.extend(_file_read_facts(lower))
    if any(
        token in lower
        for token in ("[::-1]", "reverse", "reversed", " rev ")
    ):
        facts.append("reverse the input before hashing or decoding")
    if any(
        token in lower
        for token in (
            "hashlib.sha256",
            "sha256",
            "shasum -a 256",
            "sha256sum",
        )
    ):
        facts.append("calculate the SHA256 hex digest of the transformed input")
    if any(
        token in lower
        for token in (
            "read_text",
            ".encode",
            "printf %s",
            "echo -n",
            "no trailing newline",
            "without adding a newline",
        )
    ):
        facts.append(
            "hash bytes exactly; do not add a trailing newline"
        )
    if "openssl enc -d" in lower or "aes-256-cbc" in lower:
        facts.append("decrypt with OpenSSL AES-256-CBC")
    if "pbkdf2" in lower:
        facts.append("include -pbkdf2")
    if "-pass pass:" in lower or (
        "-pass" in lower and "pass:" in lower
    ):
        facts.append(
            "use the derived digest as the OpenSSL password via -pass pass:<hash>"
        )
    if "zb2!" in lower:
        facts.append("check the file magic marker before decoding")
    if "xor" in lower or "data[4]" in lower:
        facts.append("use the dynamic key from the encoded file header")
    if "offset" in lower or "data[5]" in lower:
        facts.append("use the payload offset from the encoded file header")
    if "length" in lower or "data[6]" in lower:
        facts.append("use the payload length from the encoded file header")
    if "target:" in lower:
        facts.append("success requires revealing the expected TARGET string")
    return unique_strings(facts)


def operational_data_flow(procedure: Any) -> OperationalDataFlow:
    """Infer a reusable input-to-output dependency chain from trace evidence."""
    trace_text = _trace_text(procedure)
    lower = trace_text.lower()
    read_paths = _read_paths(trace_text)
    password_seed = next(
        (
            path
            for path in read_paths
            if path.lower().endswith((".txt", ".env", ".json"))
        ),
        None,
    )
    encrypted_target = _encrypted_target(trace_text)
    has_reverse = any(
        token in lower
        for token in ("[::-1]", "reverse", "reversed", " rev ")
    )
    has_sha256 = any(
        token in lower
        for token in (
            "hashlib.sha256",
            "sha256",
            "shasum -a 256",
            "sha256sum",
        )
    )
    has_decrypt = (
        "openssl enc -d" in lower
        or (
            "aes-256-cbc" in lower
            and any(token in lower for token in ("decrypt", " -d "))
        )
    )
    has_pbkdf2 = "pbkdf2" in lower
    has_password_binding = "-pass pass:" in lower or (
        "-pass" in lower and "pass:" in lower
    )

    if not all(
        (
            password_seed,
            encrypted_target,
            has_reverse,
            has_sha256,
            has_decrypt,
            has_pbkdf2,
            has_password_binding,
        )
    ):
        return OperationalDataFlow()

    steps = [
        f"Use the contents of {password_seed} as the password seed.",
        f"Reverse the contents of {password_seed} before hashing.",
        (
            f"Hash the reversed {password_seed} contents exactly, without "
            "a trailing newline."
        ),
        "Use that SHA256 hex digest as the OpenSSL password.",
        (
            f"Decrypt {encrypted_target} with AES-256-CBC and PBKDF2."
        ),
    ]
    execution_hints = [
        "Prefer command substitution for derived values:",
        (
            f'printf %s "$(cat {password_seed} | rev)" | '
            "sha256sum | awk '{print $1}'"
        ),
        f"Do not hash the literal filename {encrypted_target}.",
        (
            f"Do not hash the encrypted {encrypted_target} bytes as the "
            "password seed."
        ),
    ]
    return OperationalDataFlow(
        steps=steps,
        execution_hints=execution_hints,
    )


def verification_requirements(procedure: Any) -> list[str]:
    verification = unique_strings(get_value(procedure, "verification"))
    for example in raw_examples(procedure):
        if not isinstance(example, dict):
            continue
        for step in example.get("steps", []) or []:
            observation = extract_observation(step)
            if "SUCCESS:" in observation:
                verification.append(
                    "repeat the real verifier command and require SUCCESS before marking done"
                )
            if "TARGET:" in observation:
                verification.append(
                    "success requires revealing the expected TARGET string"
                )
    if not verification:
        verification.extend(
            [
                "run a real verifier command before marking the task complete",
                "do not claim success from memory alone",
            ]
        )
    return unique_strings(verification)


def _trace_text(procedure: Any) -> str:
    """Flatten inspectable procedure evidence in deterministic key order."""
    values = [
        get_value(procedure, "task_signature"),
        get_value(procedure, "steps"),
        get_value(procedure, "canonical_steps"),
        get_value(procedure, "preconditions"),
        get_value(procedure, "metadata"),
        raw_examples(procedure),
    ]
    return "\n".join(_flatten_text(value) for value in values if value)


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(
            f"{key}: {_flatten_text(value[key])}"
            for key in sorted(value, key=lambda item: str(item))
        )
    if isinstance(value, (list, tuple, set)):
        items = (
            sorted(value, key=str)
            if isinstance(value, set)
            else value
        )
        return "\n".join(_flatten_text(item) for item in items)
    return "" if value is None else str(value)


def _file_read_facts(trace_text: str) -> list[str]:
    return [f"read {path}" for path in _read_paths(trace_text)]


def _read_paths(trace_text: str) -> list[str]:
    read_signals = (
        "cat ",
        "read ",
        "read_text",
        "read_bytes",
        "open(",
        "inspect_file",
        "filesystem.read",
    )
    path_pattern = re.compile(
        r"(?<![\w.-])(?:[\w@.-]+/)*[\w@.-]+"
        r"\.(?:txt|json|ya?ml|toml|env|md|csv|log|bin|dat|enc)"
        r"(?![\w.-])"
    )
    paths: set[str] = set()
    for line in trace_text.splitlines():
        lower_line = line.lower()
        if any(signal in lower_line for signal in read_signals):
            paths.update(path_pattern.findall(line))
    return sorted(paths)


def _encrypted_target(trace_text: str) -> str | None:
    command_target = re.search(
        r"(?:^|\s)-in\s+([^\s'\"<>]+)",
        trace_text,
        re.IGNORECASE,
    )
    if command_target:
        return command_target.group(1)
    encrypted_paths = re.findall(
        r"(?<![\w.-])(?:[\w@.-]+/)*[\w@.-]+\.enc(?![\w.-])",
        trace_text,
        re.IGNORECASE,
    )
    return sorted(set(encrypted_paths))[0] if encrypted_paths else None
