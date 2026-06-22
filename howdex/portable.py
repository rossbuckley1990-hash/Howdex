"""Portable procedure documents and the local Howdex Codex registry."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from howdex.core.feedback import procedure_feedback_confidence
from howdex.core.types import Procedure
from howdex.storage import Store

PROCEDURE_FORMAT = "howdex.procedure"
PROCEDURE_FORMAT_VERSION = 2
CODEX_FORMAT = "howdex.codex"
CODEX_FORMAT_VERSION = 1


def default_procedure_directory() -> Path:
    """Return the project-local default export directory."""
    return Path.cwd() / ".howdex" / "procedures"


def default_codex_directory() -> Path:
    """Return the project-local default Codex directory."""
    return Path.cwd() / ".howdex" / "codex"


def export_procedures(
    store: Store,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Export every stored procedure as one versioned JSON document."""
    output_dir = Path(output) if output is not None else default_procedure_directory()
    output_dir.mkdir(parents=True, exist_ok=True)

    exported: list[Path] = []
    for payload in store.all_procedures():
        procedure = _procedure_from_store(payload)
        document = procedure_document(procedure, store=store)
        destination = output_dir / _procedure_filename(procedure)
        _write_json(destination, document)
        exported.append(destination)

    return {
        "output": output_dir,
        "exported": len(exported),
        "files": exported,
    }


def import_procedures(store: Store, source: str | Path) -> dict[str, int]:
    """Import a procedure JSON file or a directory of procedure documents.

    Procedures are deduplicated by canonical task signature. Re-importing the
    same document does not create another row.
    """
    files = _procedure_files(Path(source))
    counts = {"files": len(files), "imported": 0, "updated": 0, "unchanged": 0}

    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        procedure = procedure_from_document(document, source_path=path)
        existing = store.get_procedure(procedure.task_signature)

        if existing is None:
            store.put_procedure(dict(procedure.__dict__))
            counts["imported"] += 1
            continue

        merged = _merge_with_existing(procedure, existing)
        if _stored_procedure_equal(existing, merged):
            counts["unchanged"] += 1
            continue

        store.put_procedure(dict(merged.__dict__))
        counts["updated"] += 1

    return counts


def init_codex(path: str | Path | None = None) -> dict[str, Any]:
    """Create or safely reopen a local Codex folder."""
    root = Path(path) if path is not None else default_codex_directory()
    procedures_dir = root / "procedures"
    procedures_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = root / "manifest.json"
    now = _iso_timestamp(time.time())
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != CODEX_FORMAT:
            raise ValueError(f"{manifest_path} is not a Howdex Codex manifest")
        manifest.setdefault("created_at", now)
    else:
        manifest = {
            "format": CODEX_FORMAT,
            "format_version": CODEX_FORMAT_VERSION,
            "name": Path.cwd().name or "local",
            "description": "Local portable registry for Howdex procedures.",
            "created_at": now,
        }

    manifest.update(
        {
            "format": CODEX_FORMAT,
            "format_version": CODEX_FORMAT_VERSION,
            "procedures": "procedures",
            "updated_at": now,
        }
    )
    _write_json(manifest_path, manifest)
    return {
        "root": root,
        "manifest": manifest_path,
        "procedures": procedures_dir,
    }


def publish_codex(
    store: Store,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Publish local learned procedures into a local Codex folder."""
    codex = init_codex(path)
    exported = export_procedures(store, codex["procedures"])

    manifest = json.loads(codex["manifest"].read_text(encoding="utf-8"))
    manifest["procedure_count"] = exported["exported"]
    manifest["updated_at"] = _iso_timestamp(time.time())
    _write_json(codex["manifest"], manifest)

    return {**codex, **exported}


def pull_codex(store: Store, path: str | Path) -> dict[str, int]:
    """Import procedures from another local Codex folder."""
    root = Path(path)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing Codex manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != CODEX_FORMAT:
        raise ValueError(f"{manifest_path} is not a Howdex Codex manifest")

    procedures_dir = root / manifest.get("procedures", "procedures")
    return import_procedures(store, procedures_dir)


def procedure_document(procedure: Procedure, *, store: Store) -> dict[str, Any]:
    """Build the v1 portable JSON representation for a procedure."""
    return {
        "format": PROCEDURE_FORMAT,
        "format_version": PROCEDURE_FORMAT_VERSION,
        "procedure": {
            "id": procedure.id,
            "task_signature": procedure.task_signature,
            "steps": procedure.steps,
            "preconditions": procedure.preconditions,
            "expected_outcome": procedure.expected_outcome,
            "raw_supporting_examples": procedure.raw_supporting_examples,
        },
        "success_evidence": {
            "success_rate": procedure.success_rate,
            "sample_count": procedure.sample_count,
            "support_count": procedure.support_count,
            "success_count": procedure.success_count,
            "failure_count": procedure.failure_count,
            "confidence": procedure.confidence,
            "base_confidence": procedure.base_confidence,
            "feedback_success_count": procedure.feedback_success_count,
            "feedback_failure_count": procedure.feedback_failure_count,
            "source_episode_ids": procedure.source_episode_ids,
        },
        "source": {
            "system": "howdex",
            "node_id": store.node_id,
            "database": store.path.name,
            "exported_at": _iso_timestamp(time.time()),
        },
        "timestamps": {
            "created_at": _iso_timestamp(procedure.created_at),
            "updated_at": None,
            "last_used_at": _iso_timestamp(procedure.last_used_at),
        },
        "usage": {
            "use_count": procedure.use_count,
            "suggestion_count": procedure.suggestion_count,
            "unverified_use_count": procedure.unverified_use_count,
        },
    }


def procedure_from_document(
    document: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> Procedure:
    """Validate and decode a v1 portable procedure document."""
    label = str(source_path) if source_path is not None else "procedure document"
    if document.get("format") != PROCEDURE_FORMAT:
        raise ValueError(f"{label} is not a Howdex procedure document")
    format_version = document.get("format_version")
    if format_version not in {1, PROCEDURE_FORMAT_VERSION}:
        raise ValueError(
            f"{label} uses unsupported procedure format version "
            f"{document.get('format_version')!r}"
        )

    payload = document.get("procedure")
    if not isinstance(payload, dict):
        raise ValueError(f"{label} has no procedure object")

    task_signature = _canonical_task(payload.get("task_signature", ""))
    if not task_signature:
        raise ValueError(f"{label} has no task signature")

    evidence = document.get("success_evidence") or {}
    timestamps = document.get("timestamps") or {}
    usage = document.get("usage") or {}
    success_rate = float(evidence.get("success_rate", 0.0))
    sample_count = int(evidence.get("sample_count", 0))
    support_count = int(evidence.get("support_count", sample_count))
    success_count = int(
        evidence.get("success_count", round(success_rate * support_count))
    )
    confidence = float(evidence.get("confidence", success_rate))
    base_confidence = float(
        evidence.get("base_confidence", confidence)
    )
    failure_count = int(
        evidence.get(
            "failure_count",
            max(0, support_count - success_count),
        )
    )
    feedback_success_count = int(
        evidence.get("feedback_success_count", 0)
    )
    feedback_failure_count = int(
        evidence.get("feedback_failure_count", 0)
    )
    if not 0.0 <= success_rate <= 1.0:
        raise ValueError(f"{label} success_rate must be between 0 and 1")
    if sample_count < 0:
        raise ValueError(f"{label} sample_count must be non-negative")
    if support_count < 0 or success_count < 0 or failure_count < 0:
        raise ValueError(f"{label} support counts must be non-negative")
    if feedback_success_count < 0 or feedback_failure_count < 0:
        raise ValueError(f"{label} feedback counts must be non-negative")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{label} confidence must be between 0 and 1")
    if not 0.0 <= base_confidence <= 1.0:
        raise ValueError(f"{label} base_confidence must be between 0 and 1")

    return Procedure(
        id=str(payload.get("id") or "").strip() or Procedure().id,
        task_signature=task_signature,
        steps=_list_value(payload.get("steps"), "steps", label),
        preconditions=_list_value(payload.get("preconditions"), "preconditions", label),
        expected_outcome=str(payload.get("expected_outcome") or ""),
        success_rate=success_rate,
        sample_count=sample_count,
        support_count=support_count,
        success_count=success_count,
        failure_count=failure_count,
        confidence=confidence,
        base_confidence=base_confidence,
        feedback_success_count=feedback_success_count,
        feedback_failure_count=feedback_failure_count,
        suggestion_count=int(usage.get("suggestion_count", 0)),
        unverified_use_count=int(usage.get("unverified_use_count", 0)),
        raw_supporting_examples=_list_value(
            payload.get("raw_supporting_examples"),
            "raw_supporting_examples",
            label,
        ),
        source_episode_ids=[
            str(value)
            for value in _list_value(
                evidence.get("source_episode_ids"),
                "source_episode_ids",
                label,
            )
        ],
        created_at=_parse_timestamp(timestamps.get("created_at")) or time.time(),
        last_used_at=_parse_timestamp(timestamps.get("last_used_at")),
        use_count=int(usage.get("use_count", 0)),
    )


def _procedure_from_store(payload: dict[str, Any]) -> Procedure:
    data = dict(payload)
    for key in (
        "steps",
        "preconditions",
        "raw_supporting_examples",
        "source_episode_ids",
    ):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = json.loads(value)
    return Procedure(**data)


def _merge_with_existing(
    incoming: Procedure,
    existing: dict[str, Any],
) -> Procedure:
    existing_proc = _procedure_from_store(existing)
    created_at = min(existing_proc.created_at, incoming.created_at)
    last_used_candidates = [
        value
        for value in (existing_proc.last_used_at, incoming.last_used_at)
        if value is not None
    ]
    feedback_success_count = max(
        existing_proc.feedback_success_count,
        incoming.feedback_success_count,
    )
    feedback_failure_count = max(
        existing_proc.feedback_failure_count,
        incoming.feedback_failure_count,
    )
    success_count = max(
        existing_proc.success_count,
        incoming.success_count,
    )
    failure_count = max(
        existing_proc.failure_count,
        incoming.failure_count,
    )
    support_count = max(
        existing_proc.support_count,
        incoming.support_count,
        success_count + failure_count,
    )
    source_episode_ids = sorted(
        {
            *map(str, existing_proc.source_episode_ids),
            *map(str, incoming.source_episode_ids),
        }
    )
    base_confidence = (
        incoming.base_confidence
        or existing_proc.base_confidence
        or incoming.confidence
    )
    if feedback_success_count or feedback_failure_count:
        confidence = procedure_feedback_confidence(
            base_confidence=base_confidence,
            success_count=success_count,
            support_count=support_count,
        )
    else:
        confidence = incoming.confidence
    return Procedure(
        id=existing_proc.id,
        task_signature=existing_proc.task_signature,
        steps=incoming.steps,
        preconditions=incoming.preconditions,
        expected_outcome=incoming.expected_outcome,
        success_rate=(
            round(success_count / support_count, 4)
            if support_count
            else incoming.success_rate
        ),
        sample_count=incoming.sample_count,
        support_count=support_count,
        success_count=success_count,
        failure_count=failure_count,
        confidence=confidence,
        base_confidence=base_confidence,
        feedback_success_count=feedback_success_count,
        feedback_failure_count=feedback_failure_count,
        suggestion_count=max(
            existing_proc.suggestion_count,
            incoming.suggestion_count,
        ),
        unverified_use_count=max(
            existing_proc.unverified_use_count,
            incoming.unverified_use_count,
        ),
        raw_supporting_examples=incoming.raw_supporting_examples,
        source_episode_ids=source_episode_ids,
        created_at=created_at,
        last_used_at=max(last_used_candidates) if last_used_candidates else None,
        use_count=max(existing_proc.use_count, incoming.use_count),
    )


def _stored_procedure_equal(existing: dict[str, Any], candidate: Procedure) -> bool:
    current = _procedure_from_store(existing)
    return current == candidate


def _procedure_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    if not source.exists():
        raise FileNotFoundError(f"procedure path does not exist: {source}")
    if not source.is_dir():
        raise ValueError(f"procedure path is not a file or directory: {source}")
    return sorted(path for path in source.glob("*.json") if path.is_file())


def _procedure_filename(procedure: Procedure) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", procedure.task_signature.lower()).strip("-")
    slug = slug[:80] or "procedure"
    identity = hashlib.sha256(procedure.task_signature.encode("utf-8")).hexdigest()[:10]
    return f"{slug}--{identity}.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _canonical_task(task: Any) -> str:
    return " ".join(str(task or "").lower().split())[:200]


def _list_value(value: Any, field: str, label: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} field {field!r} must be a list")
    return value


def _iso_timestamp(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
