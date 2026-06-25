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
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationalFact:
    """One trace-derived guidance fact with lightweight relevance metadata."""

    text: str
    categories: tuple[str, ...] = ("unknown",)
    provenance: str = "procedure"


CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "docker/config/health",
        (
            "docker",
            "compose",
            "docker-compose",
            "dockerfile",
            "container",
            "/health",
            "health endpoint",
            "health verifier",
            "health_mode",
            "health-policy",
            "runtime.env",
            "app_port",
            "http 200",
            "curl",
            "localhost",
            "127.0.0.1",
        ),
    ),
    (
        "crypto/hash/openssl",
        (
            "sha256",
            "sha256sum",
            "shasum -a 256",
            "hashlib",
            "openssl",
            "aes-256-cbc",
            "pbkdf2",
            "vault.enc",
            "seed.txt",
            "digest",
            "trailing newline",
            "-pass pass",
            "password seed",
            "decrypt",
            "encrypted",
        ),
    ),
    (
        "binary/decode/target",
        (
            "zb2",
            "challenge.zb2",
            "binary",
            "decoder",
            "decode",
            "checksum",
            "xor",
            "payload",
            "magic",
            "header",
            "offset",
            "decoy",
        ),
    ),
    (
        "git",
        (
            "git ",
            "branch",
            "commit",
            "checkout",
            "merge",
            "pull request",
            "github",
        ),
    ),
    (
        "filesystem",
        (
            "file",
            "path",
            "read ",
            "write ",
            "cat ",
            "fs.write",
            "filesystem",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".env",
            ".py",
            ".js",
        ),
    ),
    (
        "package-manager",
        (
            "npm ",
            "npm install",
            "pnpm ",
            "yarn ",
            "pip install",
            "poetry add",
            "cargo add",
            "go get",
            "package.json",
            "missing module",
            "dependency",
        ),
    ),
)

GENERIC_CATEGORIES = {"unknown", "filesystem"}
STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "use",
    "with",
}


def learned_facts(procedure: Any) -> list[str]:
    """Return relevant facts without objective filtering.

    This compatibility helper preserves the historical behavior for direct
    callers. Agent rendering uses ``relevant_learned_facts`` so facts from an
    irrelevant procedure do not contaminate another task's prompt.
    """
    return [fact.text for fact in operational_facts(procedure)]


def relevant_learned_facts(
    procedure: Any,
    *,
    objective: str | None = None,
) -> list[str]:
    """Return facts that are relevant to both procedure evidence and objective."""
    return [
        fact.text
        for fact in operational_facts(procedure)
        if _fact_is_relevant(fact, procedure, objective)
    ]


def operational_facts(procedure: Any) -> list[OperationalFact]:
    """Extract deterministic operational facts with category provenance."""
    categorized: list[OperationalFact] = []
    for key in (
        "learned_facts",
        "operational_facts",
        "semantic_facts",
        "facts",
        "preconditions",
    ):
        for fact in unique_strings(get_value(procedure, key)):
            categorized.append(
                OperationalFact(
                    fact,
                    categories=_categories_for_text(fact),
                    provenance=key,
                )
            )

    trace = _trace_text(procedure)
    lower = trace.lower()
    context_categories = _categories_for_text(trace)
    for fact in _file_read_facts(trace):
        categorized.append(
            OperationalFact(
                fact,
                categories=_categories_for_text(fact),
                provenance="trace:file_read",
            )
        )
    if any(
        token in lower
        for token in ("[::-1]", "reverse", "reversed", " rev ")
    ):
        categorized.append(
            OperationalFact(
                "reverse the input before hashing or decoding",
                categories=_contextual_categories(
                    context_categories,
                    fallback=("unknown",),
                ),
                provenance="trace:transform",
            )
        )
    if any(
        token in lower
        for token in (
            "hashlib.sha256",
            "sha256",
            "shasum -a 256",
            "sha256sum",
        )
    ):
        categorized.append(
            OperationalFact(
                "calculate the SHA256 hex digest of the transformed input",
                categories=("crypto/hash/openssl",),
                provenance="trace:hash",
            )
        )
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
        categorized.append(
            OperationalFact(
                "hash bytes exactly; do not add a trailing newline",
                categories=("crypto/hash/openssl",),
                provenance="trace:hash_bytes",
            )
        )
    if "openssl enc -d" in lower or "aes-256-cbc" in lower:
        categorized.append(
            OperationalFact(
                "decrypt with OpenSSL AES-256-CBC",
                categories=("crypto/hash/openssl",),
                provenance="trace:openssl",
            )
        )
    if "pbkdf2" in lower:
        categorized.append(
            OperationalFact(
                "include -pbkdf2",
                categories=("crypto/hash/openssl",),
                provenance="trace:openssl",
            )
        )
    if "-pass pass:" in lower or (
        "-pass" in lower and "pass:" in lower
    ):
        categorized.append(
            OperationalFact(
                "use the derived digest as the OpenSSL password via -pass pass:<hash>",
                categories=("crypto/hash/openssl",),
                provenance="trace:openssl",
            )
        )
    if "zb2!" in lower:
        categorized.append(
            OperationalFact(
                "check the file magic marker before decoding",
                categories=("binary/decode/target",),
                provenance="trace:binary",
            )
        )
    if "xor" in lower or "data[4]" in lower:
        categorized.append(
            OperationalFact(
                "use the dynamic key from the encoded file header",
                categories=("binary/decode/target",),
                provenance="trace:binary",
            )
        )
    if "offset" in lower or "data[5]" in lower:
        categorized.append(
            OperationalFact(
                "use the payload offset from the encoded file header",
                categories=("binary/decode/target",),
                provenance="trace:binary",
            )
        )
    if "length" in lower or "data[6]" in lower:
        categorized.append(
            OperationalFact(
                "use the payload length from the encoded file header",
                categories=("binary/decode/target",),
                provenance="trace:binary",
            )
        )
    if _contains_target_signal(trace):
        categorized.append(
            OperationalFact(
                "success requires revealing the expected TARGET string",
                categories=_contextual_categories(
                    context_categories,
                    fallback=("binary/decode/target",),
                ),
                provenance="trace:verification",
            )
        )
    if "docker compose" in lower or "docker-compose.yml" in lower:
        categorized.append(
            OperationalFact(
                "inspect the Docker Compose service configuration",
                categories=("docker/config/health",),
                provenance="trace:docker",
            )
        )
    if any(token in lower for token in ("runtime.env", "health_mode", "health-policy")):
        categorized.append(
            OperationalFact(
                "align runtime health configuration with the required health policy",
                categories=("docker/config/health",),
                provenance="trace:docker_config",
            )
        )
    if "docker compose up" in lower or "docker compose down" in lower:
        categorized.append(
            OperationalFact(
                "recreate the Docker Compose service before verifying health",
                categories=("docker/config/health",),
                provenance="trace:docker_runtime",
            )
        )
    if "/health" in lower or "http 200" in lower:
        categorized.append(
            OperationalFact(
                "verify the local /health endpoint with the real HTTP verifier",
                categories=("docker/config/health",),
                provenance="trace:health_verifier",
            )
        )
    return _unique_facts(categorized)


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
        categories=("crypto/hash/openssl",),
    )


def relevant_operational_data_flow(
    procedure: Any,
    *,
    objective: str | None = None,
) -> OperationalDataFlow:
    """Return binding-aware flow only when relevant to the current task."""
    flow = operational_data_flow(procedure)
    if not flow.steps:
        return flow
    fact = OperationalFact(
        "\n".join([*flow.steps, *flow.execution_hints]),
        categories=flow.categories or _categories_for_text(
            "\n".join([*flow.steps, *flow.execution_hints])
        ),
        provenance="trace:data_flow",
    )
    if _fact_is_relevant(fact, procedure, objective):
        return flow
    return OperationalDataFlow()


def verification_requirements(procedure: Any) -> list[str]:
    return [
        fact.text
        for fact in verification_requirement_facts(procedure)
    ]


def relevant_verification_requirements(
    procedure: Any,
    *,
    objective: str | None = None,
) -> list[str]:
    return [
        fact.text
        for fact in verification_requirement_facts(procedure)
        if _fact_is_relevant(fact, procedure, objective)
    ]


def verification_requirement_facts(procedure: Any) -> list[OperationalFact]:
    verification = [
        OperationalFact(
            item,
            categories=_categories_for_text(item),
            provenance="verification",
        )
        for item in unique_strings(get_value(procedure, "verification"))
    ]
    for example in raw_examples(procedure):
        if not isinstance(example, dict):
            continue
        for step in example.get("steps", []) or []:
            observation = extract_observation(step)
            if "SUCCESS:" in observation:
                verification.append(
                    OperationalFact(
                        "repeat the real verifier command and require SUCCESS before marking done",
                        categories=_categories_for_text(observation) or ("unknown",),
                        provenance="trace:verification",
                    )
                )
            if "TARGET:" in observation:
                verification.append(
                    OperationalFact(
                        "success requires revealing the expected TARGET string",
                        categories=_contextual_categories(
                            _categories_for_text(_trace_text(procedure)),
                            fallback=("binary/decode/target",),
                        ),
                        provenance="trace:verification",
                    )
                )
    if not verification:
        verification.extend(
            [
                OperationalFact(
                    "run a real verifier command before marking the task complete",
                    categories=("unknown",),
                    provenance="verification:fallback",
                ),
                OperationalFact(
                    "do not claim success from memory alone",
                    categories=("unknown",),
                    provenance="verification:fallback",
                ),
            ]
        )
    return _unique_facts(verification)


def text_relevant_to_objective(
    text: str,
    procedure: Any,
    *,
    objective: str | None = None,
) -> bool:
    """Return whether one guidance line belongs in the current task."""
    fact = OperationalFact(
        text,
        categories=_categories_for_text(text),
        provenance="text",
    )
    return _fact_is_relevant(fact, procedure, objective)


def procedure_relevant_to_objective(
    procedure: Any,
    *,
    objective: str | None = None,
) -> bool:
    """Return whether a procedure has a deterministic relevance signal."""
    objective_text = str(objective or "").strip()
    if not objective_text:
        return True
    objective_categories = set(_categories_for_text(objective_text))
    procedure_text = _procedure_context_text(procedure)
    procedure_categories = set(_categories_for_text(procedure_text))
    if not objective_categories or objective_categories == {"unknown"}:
        return True
    if procedure_categories & objective_categories:
        return True
    return bool(_tokens(objective_text) & _tokens(procedure_text))


def _trace_text(procedure: Any) -> str:
    """Flatten inspectable procedure evidence in deterministic key order.

    Strips ``args:sha256:...`` fallback targets produced by the parameterizer
    when no salient argument can be extracted. Without this stripping, the
    fact extractor's pattern matcher sees the literal string "sha256" in
    the fallback target and emits a bogus "calculate the SHA256 hex digest"
    fact for procedures that have nothing to do with cryptography. This was
    the root cause of the SHA256 contaminant in guidance for unrelated
    (e.g. Node.js) tasks.
    """
    import re
    values = [
        get_value(procedure, "task_signature"),
        get_value(procedure, "steps"),
        get_value(procedure, "canonical_steps"),
        get_value(procedure, "preconditions"),
        get_value(procedure, "metadata"),
        raw_examples(procedure),
    ]
    text = "\n".join(_flatten_text(value) for value in values if value)
    # Strip parameterizer fallback targets like "args:sha256:abc123" —
    # these are hash-labels, not real crypto operations.
    text = re.sub(r"args:sha256:[a-f0-9]+", "args:<fallback>", text, flags=re.IGNORECASE)
    return text


def _procedure_context_text(procedure: Any) -> str:
    values = [
        get_value(procedure, "task_signature"),
        get_value(procedure, "name"),
        get_value(procedure, "category"),
        get_value(procedure, "tags"),
        get_value(procedure, "learned_facts"),
        get_value(procedure, "operational_facts"),
        get_value(procedure, "semantic_facts"),
        get_value(procedure, "facts"),
        get_value(procedure, "steps"),
        get_value(procedure, "canonical_steps"),
        get_value(procedure, "preconditions"),
        get_value(procedure, "verification"),
        get_value(procedure, "match_explanation"),
        _trace_text(procedure),
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


def _categories_for_text(text: Any) -> tuple[str, ...]:
    lowered = str(text or "").casefold()
    categories: list[str] = []
    for category, tokens in CATEGORY_KEYWORDS:
        if any(token in lowered for token in tokens):
            categories.append(category)
    if not categories:
        categories.append("unknown")
    return tuple(categories)


def _contains_target_signal(text: str) -> bool:
    return bool(
        re.search(
            r"\bTARGET\s*(?::|=|\s+\d)",
            text,
        )
    )


def _contextual_categories(
    categories: tuple[str, ...],
    *,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    domain_categories = tuple(
        category
        for category in categories
        if category not in GENERIC_CATEGORIES
    )
    return domain_categories or fallback


def _fact_is_relevant(
    fact: OperationalFact,
    procedure: Any,
    objective: str | None,
) -> bool:
    objective_text = str(objective or "").strip()
    if not objective_text:
        return True

    objective_categories = set(_categories_for_text(objective_text))
    fact_categories = set(fact.categories or ("unknown",))
    if not objective_categories or objective_categories == {"unknown"}:
        return True

    if fact_categories & objective_categories:
        return True

    procedure_relevant = procedure_relevant_to_objective(
        procedure,
        objective=objective,
    )
    if not procedure_relevant:
        return False

    procedure_categories = set(
        _categories_for_text(_procedure_context_text(procedure))
    )
    if fact_categories <= GENERIC_CATEGORIES:
        return True
    if fact_categories & procedure_categories & objective_categories:
        return True
    return bool(_tokens(fact.text) & _tokens(objective_text))


def _tokens(text: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", str(text).casefold())
        if token not in STOPWORDS
    }


def _unique_facts(facts: list[OperationalFact]) -> list[OperationalFact]:
    seen: set[str] = set()
    unique: list[OperationalFact] = []
    for fact in facts:
        text = str(fact.text).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            OperationalFact(
                text,
                categories=fact.categories or ("unknown",),
                provenance=fact.provenance,
            )
        )
    return unique


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
