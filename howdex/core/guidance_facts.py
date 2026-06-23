"""Deterministic operational-fact and verification extraction."""

from __future__ import annotations

from typing import Any

from howdex.core.guidance_artifacts import (
    extract_observation,
    raw_examples,
)
from howdex.core.guidance_utils import as_list, get_value, unique_strings


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

    trace_parts: list[str] = []
    for step in as_list(get_value(procedure, "steps")):
        if isinstance(step, dict):
            trace_parts.append(str(step))
    for example in raw_examples(procedure):
        if isinstance(example, dict):
            trace_parts.append(str(example))

    lower = "\n".join(trace_parts).lower()
    if "seed.txt" in lower:
        facts.append("read the raw contents of seed.txt")
    if any(token in lower for token in ("[::-1]", "reverse", "reversed", " rev")):
        facts.append("reverse the input string before hashing it")
    if any(token in lower for token in ("hashlib.sha256", "sha256", "shasum -a 256")):
        facts.append("calculate the SHA256 hex digest of the transformed input")
    if any(token in lower for token in ("read_text", ".encode", "printf %s")):
        facts.append(
            "hash the transformed bytes exactly, without adding a trailing newline"
        )
    if "aes-256-cbc" in lower:
        facts.append("decrypt with OpenSSL AES-256-CBC")
    if "pbkdf2" in lower:
        facts.append("include PBKDF2 when decrypting")
    if "-pass" in lower or "pass:" in lower:
        facts.append(
            "use the derived hex digest as the OpenSSL password via -pass pass:<hash>"
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
        facts.append("extract the integer or token after TARGET:")
    return unique_strings(facts)


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
            elif "TARGET:" in observation:
                verification.append("success requires the expected TARGET output")
    if not verification:
        verification.extend(
            [
                "run a real verifier command before marking the task complete",
                "do not claim success from memory alone",
            ]
        )
    return unique_strings(verification)
