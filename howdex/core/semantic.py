"""Deterministic semantic records derived from structured tool calls."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from howdex.core.actions import CanonicalAction
from howdex.core.tool_calls import redact_secrets
from howdex.core.types import MemoryType

_SEMANTIC_NAMESPACE = uuid.UUID("71096902-c876-5fb6-bcfa-3eea9158c637")
_ENTITY_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,80}$")


@dataclass(frozen=True)
class SemanticRecord:
    """One deterministic semantic memory specification."""

    semantic_key: str
    content: str
    type: MemoryType
    metadata: dict[str, Any]
    relations: list[dict[str, str]] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(uuid.uuid5(_SEMANTIC_NAMESPACE, self.semantic_key))


class SemanticExtractor(Protocol):
    """Optional extractor interface.

    Implementations may be non-deterministic. Howdex never invokes one unless
    an application explicitly chooses to integrate it.
    """

    deterministic: bool

    def extract(
        self,
        content: str,
        *,
        provenance: dict[str, Any] | None = None,
    ) -> list[SemanticRecord]:
        """Extract application-defined semantic records."""


def derive_tool_semantics(
    action: CanonicalAction,
    *,
    outcome: str | None = None,
    session_id: str | None = None,
) -> list[SemanticRecord]:
    """Derive conservative entities and action-target relations."""
    canonical_name = str(action.canonical_name or "").strip().lower()
    if not canonical_name or canonical_name in {"unknown_tool", "unknown_action"}:
        return []

    safe_provenance = redact_secrets(action.provenance or {})[0]
    common_metadata = {
        "semantic_origin": "structured_tool_call",
        "confidence": round(max(0.0, min(1.0, action.confidence)), 4),
        "provenance": safe_provenance,
    }
    if session_id:
        common_metadata["source_session_id"] = session_id
    normalized_outcome = _normalise_outcome(outcome)

    namespace = canonical_name.split(".", 1)[0]
    action_key = f"action:{canonical_name}"
    system_key = f"system:{namespace}"
    action_record = _entity_record(
        action_key,
        entity_kind="action",
        value=canonical_name,
        metadata={
            **common_metadata,
            "system": namespace,
            "intent": action.intent,
            "side_effect_class": action.side_effect_class,
        },
    )
    system_record = _entity_record(
        system_key,
        entity_kind="system",
        value=namespace,
        metadata=common_metadata,
    )
    records = [system_record, action_record]

    for entity_key, entity_kind, value in _target_entities(action.target):
        target_record = _entity_record(
            entity_key,
            entity_kind=entity_kind,
            value=value,
            metadata=common_metadata,
        )
        relation_key = f"relation:{action_key}:targets:{entity_key}"
        relation_metadata = {
            **common_metadata,
            "relation": "targets",
            "subject": action_key,
            "object": entity_key,
        }
        if normalized_outcome:
            relation_metadata["observed_outcome"] = normalized_outcome
        records.extend(
            [
                target_record,
                SemanticRecord(
                    semantic_key=relation_key,
                    content=f"{action_key} -> {entity_key}",
                    type=MemoryType.RELATION,
                    metadata=relation_metadata,
                    relations=[
                        {"type": "subject", "target": action_record.id},
                        {"type": "object", "target": target_record.id},
                    ],
                ),
            ]
        )

    return _deduplicate(records)


def _entity_record(
    semantic_key: str,
    *,
    entity_kind: str,
    value: str,
    metadata: dict[str, Any],
) -> SemanticRecord:
    return SemanticRecord(
        semantic_key=f"entity:{semantic_key}",
        content=semantic_key,
        type=MemoryType.ENTITY,
        metadata={
            **metadata,
            "entity_kind": entity_kind,
            "entity_value": value,
        },
    )


def _target_entities(target: str | None) -> list[tuple[str, str, str]]:
    if not target or target.startswith("args:sha256:"):
        return []
    entities: list[tuple[str, str, str]] = []
    for part in target.split(";"):
        key, separator, value = part.partition("=")
        normalized_key = key.rsplit(".", 1)[-1].strip().lower()
        normalized_value = " ".join(value.split())
        if (
            not separator
            or not _ENTITY_KEY_RE.match(normalized_key)
            or not normalized_value
            or normalized_value == "[REDACTED]"
        ):
            continue
        entities.append(
            (
                f"{normalized_key}:{normalized_value}",
                normalized_key,
                normalized_value,
            )
        )
    return entities


def _normalise_outcome(outcome: str | None) -> str | None:
    normalized = " ".join(str(outcome or "").lower().split())
    return normalized[:80] or None


def _deduplicate(records: list[SemanticRecord]) -> list[SemanticRecord]:
    by_key = {record.semantic_key: record for record in records}
    return [by_key[key] for key in sorted(by_key)]
