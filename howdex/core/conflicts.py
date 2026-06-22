"""Deterministic semantic-conflict detection scaffolding."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from howdex.core.types import Memory, MemoryLayer

_PREFERENCE_RE = re.compile(
    r"^\s*(?P<subject>[a-z][a-z0-9 _.-]{0,80}?)\s+"
    r"(?P<predicate>prefers?|likes?|wants?|uses?)\s+"
    r"(?P<value>.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticAssertion:
    subject: str
    predicate: str
    value: str

    @property
    def key(self) -> str:
        return f"{self.subject}:{self.predicate}"


def parse_semantic_assertion(content: str) -> SemanticAssertion | None:
    """Parse a narrow, reviewable preference/fact assertion shape."""
    match = _PREFERENCE_RE.match(content or "")
    if not match:
        return None
    predicate = match.group("predicate").lower()
    if predicate.endswith("s"):
        predicate = predicate[:-1]
    return SemanticAssertion(
        subject=_normalise(match.group("subject")),
        predicate=predicate,
        value=_normalise(match.group("value")),
    )


def semantic_conflict_metadata(
    content: str,
    existing_memories: Iterable[Memory],
) -> dict:
    """Return review metadata for obvious contradictory semantic assertions."""
    candidate = parse_semantic_assertion(content)
    if candidate is None:
        return {}

    conflicts: list[Memory] = []
    conflicting_values: set[str] = set()
    for memory in existing_memories:
        if memory.layer != MemoryLayer.SEMANTIC:
            continue
        assertion = parse_semantic_assertion(memory.content)
        if assertion is None or assertion.key != candidate.key:
            continue
        if assertion.value == candidate.value:
            continue
        conflicts.append(memory)
        conflicting_values.add(assertion.value)

    if not conflicts:
        return {}

    return {
        "semantic_conflict_detected": True,
        "requires_review": True,
        "conflict_key": candidate.key,
        "asserted_value": candidate.value,
        "conflicting_values": sorted(conflicting_values),
        "conflicts_with": sorted(memory.id for memory in conflicts),
    }


def _normalise(value: str) -> str:
    return " ".join(str(value or "").lower().split()).strip(" .!?:;,")
