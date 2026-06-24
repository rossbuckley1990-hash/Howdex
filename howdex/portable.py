"""Portable procedure documents and the local Howdex Codex registry."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import howdex.telemetry as telemetry
from howdex.attestation import is_signed_verified_receipt
from howdex.core.feedback import procedure_feedback_confidence
from howdex.core.receipts import (
    VerificationReceipt,
    procedure_verification_status,
)
from howdex.core.types import Procedure
from howdex.storage import Store

PROCEDURE_FORMAT = "howdex.procedure"
PROCEDURE_FORMAT_VERSION = 2
CODEX_FORMAT = "howdex.codex"
CODEX_FORMAT_VERSION = 1
CODEX_ENTRY_REQUIRED_FIELDS = {
    "avoid",
    "category",
    "id",
    "learned_facts",
    "policy",
    "provenance",
    "risk_level",
    "source",
    "status",
    "tags",
    "title",
    "verification",
    "version",
}


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
    """Export every stored procedure as one versioned JSON document.

    If ``output`` ends with ``.json`` it is treated as a single output file
    path; the document is written there (an error is raised if more than one
    procedure would be exported, since a single file cannot hold multiple
    independent documents). Otherwise ``output`` is treated as a directory
    and one JSON file is written per procedure.
    """
    output_path = Path(output) if output is not None else default_procedure_directory()
    single_file = output_path.suffix == ".json"

    exported: list[Path] = []
    all_payloads = list(store.all_procedures())
    if single_file:
        if len(all_payloads) > 1:
            raise ValueError(
                f"output path {output_path!s} is a single file but "
                f"{len(all_payloads)} procedures would be exported; "
                "pass a directory path instead"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for payload in all_payloads:
            procedure = _procedure_from_store(payload)
            document = procedure_document(procedure, store=store)
            _write_json(output_path, document)
            exported.append(output_path)
    else:
        output_path.mkdir(parents=True, exist_ok=True)
        for payload in all_payloads:
            procedure = _procedure_from_store(payload)
            document = procedure_document(procedure, store=store)
            destination = output_path / _procedure_filename(procedure)
            _write_json(destination, document)
            exported.append(destination)

    return {
        "output": output_path,
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
            _store_receipts(store, procedure)
            counts["imported"] += 1
            continue

        merged = _merge_with_existing(procedure, existing)
        if _stored_procedure_equal(existing, merged):
            counts["unchanged"] += 1
            continue

        store.put_procedure(dict(merged.__dict__))
        _store_receipts(store, merged)
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
    *,
    require_signed_receipt: bool = False,
) -> dict[str, Any]:
    """Publish local learned procedures into a local Codex folder."""
    with telemetry.span("howdex.codex.publish") as publish_span:
        codex = init_codex(path)
        output_dir = codex["procedures"]
        output_dir.mkdir(parents=True, exist_ok=True)

        procedures = [
            _procedure_from_store(payload)
            for payload in store.all_procedures()
        ]
        if require_signed_receipt:
            missing = [
                procedure.id
                for procedure in procedures
                if not _signed_verified_receipts(procedure)
            ]
            if missing:
                raise ValueError(
                    "codex publish requires a signed verified receipt for "
                    f"procedure {missing[0]}"
                )

        exported_files: list[Path] = []
        for procedure in procedures:
            document = codex_entry_document(
                procedure,
                store=store,
                require_signed_receipt=require_signed_receipt,
            )
            destination = output_dir / _procedure_filename(procedure)
            _write_json(destination, document)
            exported_files.append(destination)
            telemetry.emit_event(
                "howdex.codex.publish.entry",
                {
                    "howdex.codex_entry_id": document.get("id"),
                    "howdex.procedure_id": procedure.id,
                    "howdex.procedure_status": document.get("status"),
                    "howdex.source_episode_count": len(
                        procedure.source_episode_ids
                    ),
                },
            )

        manifest = json.loads(codex["manifest"].read_text(encoding="utf-8"))
        manifest["procedure_count"] = len(exported_files)
        manifest["updated_at"] = _iso_timestamp(time.time())
        _write_json(codex["manifest"], manifest)
        telemetry.set_attribute(
            publish_span,
            "howdex.selected_count",
            len(exported_files),
        )

        return {
            **codex,
            "output": output_dir,
            "exported": len(exported_files),
            "files": exported_files,
        }


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
            "extraction_method": procedure.extraction_method,
            "steps": procedure.steps,
            "canonical_steps": procedure.canonical_steps,
            "parameterized_steps": procedure.parameterized_steps,
            "preconditions": procedure.preconditions,
            "expected_outcome": procedure.expected_outcome,
            "raw_supporting_examples": procedure.raw_supporting_examples,
            "parameter_bindings": procedure.parameter_bindings,
            "example_bindings": procedure.example_bindings,
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
        "verification": {
            "status": procedure_verification_status(procedure.receipts),
            "receipts": procedure.receipts,
        },
    }


def codex_entry_document(
    procedure: Procedure,
    *,
    store: Store,
    require_signed_receipt: bool = False,
) -> dict[str, Any]:
    """Build a public Howdex Codex entry for one learned procedure."""
    verification = _codex_verification(
        procedure,
        require_signed_receipt=require_signed_receipt,
    )
    return {
        "avoid": _codex_avoid(procedure),
        "category": "learned_procedure",
        "id": _codex_entry_id(procedure),
        "learned_facts": _codex_learned_facts(procedure),
        "policy": {
            "allowed": [
                "Use this entry as operational guidance for owned, in-scope agent work.",
                "Adapt placeholders and verifier commands to the current environment.",
                "Run an independent verifier before treating the procedure as proven.",
            ],
            "forbidden": [
                "Treating operational memory as executable authority.",
                "Running side-effecting steps without policy approval.",
                "Claiming production safety from a local learned procedure alone.",
            ],
            "requires_human_review": _codex_requires_review(procedure),
            "source_artifacts": "excluded_by_default",
        },
        "provenance": {
            "evidence": _codex_provenance_evidence(procedure),
            "learned_from": _codex_learned_from(procedure, store=store),
            "limitations": [
                "Generated from local Howdex procedure memory.",
                "Environment-specific commands, permissions, and policies may differ.",
                "A candidate entry is not independently verified.",
            ],
        },
        "risk_level": _codex_risk_level(procedure),
        "source": {
            "kind": "howdex-local-procedure",
            "name": "Howdex local procedure memory",
            "reference": procedure.id,
        },
        "status": resolve_codex_status(
            procedure,
            require_signed_receipt=require_signed_receipt,
        ),
        "tags": _codex_tags(procedure),
        "title": _codex_title(procedure),
        "verification": verification,
        "version": "1.0.0",
    }


def resolve_codex_status(
    procedure: Procedure,
    *,
    require_signed_receipt: bool = False,
) -> str:
    """Return the public Codex status without overclaiming verification."""
    if require_signed_receipt:
        if _signed_verified_receipts(procedure):
            return "verified"
        return "candidate"
    if _verified_receipts(procedure):
        return "verified"
    return "candidate"


def procedure_from_document(
    document: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> Procedure:
    """Validate and decode a v1 portable procedure document."""
    label = str(source_path) if source_path is not None else "procedure document"
    if document.get("format") != PROCEDURE_FORMAT:
        if _is_codex_entry(document):
            return _procedure_from_codex_entry(document)
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
    verification = document.get("verification") or {}
    if not isinstance(verification, dict):
        raise ValueError(f"{label} verification must be an object")
    receipts = [
        VerificationReceipt.from_dict(receipt).to_dict()
        for receipt in _list_value(
            verification.get("receipts"),
            "verification.receipts",
            label,
        )
    ]
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
        extraction_method=str(
            payload.get("extraction_method") or "parameterized_lcs"
        ),
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
        parameter_bindings=_list_value(
            payload.get("parameter_bindings"),
            "parameter_bindings",
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
        receipts=receipts,
        created_at=_parse_timestamp(timestamps.get("created_at")) or time.time(),
        last_used_at=_parse_timestamp(timestamps.get("last_used_at")),
        use_count=int(usage.get("use_count", 0)),
    )


def _procedure_from_codex_entry(entry: dict[str, Any]) -> Procedure:
    title = str(entry.get("title") or entry.get("id") or "").strip()
    if not title:
        raise ValueError("Codex entry has no title")
    learned_facts = [
        str(fact).strip()
        for fact in entry.get("learned_facts", [])
        if str(fact).strip()
    ]
    if not learned_facts:
        raise ValueError("Codex entry has no learned_facts")
    verification = entry.get("verification") or {}
    status = str(entry.get("status") or "").strip().lower()
    confidence = 0.8 if status == "verified" else 0.6
    if status == "deprecated":
        confidence = 0.0
    return Procedure(
        id=str(entry.get("id") or Procedure().id),
        task_signature=title,
        extraction_method="parameterized_lcs",
        steps=[
            {
                "action": fact,
                "parameterized_action": fact,
                "canonical_name": "codex_entry_step",
                "confidence": confidence,
            }
            for fact in learned_facts
        ],
        preconditions=[],
        expected_outcome=str(verification.get("expected_signal") or ""),
        success_rate=1.0 if status == "verified" else 0.0,
        sample_count=0,
        support_count=0,
        success_count=0,
        failure_count=0,
        confidence=confidence,
        base_confidence=confidence,
        raw_supporting_examples=[],
        parameter_bindings=[],
        source_episode_ids=[],
        receipts=[],
        created_at=0.0,
        last_used_at=None,
        use_count=0,
    )


def _procedure_from_store(payload: dict[str, Any]) -> Procedure:
    data = dict(payload)
    for key in (
        "steps",
        "preconditions",
        "raw_supporting_examples",
        "parameter_bindings",
        "source_episode_ids",
        "receipts",
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
    receipts = _merge_receipts(
        existing_proc.receipts,
        incoming.receipts,
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
        extraction_method=incoming.extraction_method,
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
        parameter_bindings=incoming.parameter_bindings,
        source_episode_ids=source_episode_ids,
        receipts=receipts,
        created_at=created_at,
        last_used_at=max(last_used_candidates) if last_used_candidates else None,
        use_count=max(existing_proc.use_count, incoming.use_count),
    )


def _stored_procedure_equal(existing: dict[str, Any], candidate: Procedure) -> bool:
    current = _procedure_from_store(existing)
    return current == candidate


def _store_receipts(store: Store, procedure: Procedure) -> None:
    for payload in procedure.receipts:
        receipt = VerificationReceipt.from_dict(payload)
        store.attach_receipt(
            procedure.id,
            receipt.receipt_id,
            receipt.to_dict(),
        )


def _merge_receipts(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    receipts = {
        receipt.receipt_id: receipt.to_dict()
        for payload in [*existing, *incoming]
        for receipt in [VerificationReceipt.from_dict(payload)]
    }
    return [receipts[key] for key in sorted(receipts)]


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


def _is_codex_entry(document: dict[str, Any]) -> bool:
    return CODEX_ENTRY_REQUIRED_FIELDS <= document.keys()


def _codex_entry_id(procedure: Procedure) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", procedure.task_signature.lower()).strip("_")
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "_", procedure.id.lower()).strip("_")
    digest = hashlib.sha256(procedure.id.encode("utf-8")).hexdigest()[:10]
    return f"howdex.{slug[:64] or 'procedure'}.{digest}"


def _codex_title(procedure: Procedure) -> str:
    return str(procedure.task_signature or procedure.id or "Learned procedure").strip()


def _codex_learned_facts(procedure: Procedure) -> list[str]:
    facts: list[str] = []
    for step in procedure.parameterized_steps or procedure.canonical_steps or procedure.steps:
        if not isinstance(step, dict):
            continue
        action = _step_action_text(step)
        if action:
            facts.append(action)
    if not facts and procedure.preconditions:
        facts.extend(str(value).strip() for value in procedure.preconditions if str(value).strip())
    if not facts:
        facts.append(f"Apply the learned procedure for: {_codex_title(procedure)}.")
    return _unique_preserving_order(facts)


def _step_action_text(step: dict[str, Any]) -> str:
    args = step.get("arguments") or step.get("parameterized_args") or {}
    if isinstance(args, dict):
        command = args.get("cmd") or args.get("command")
        if command:
            return f"Run command template: {command}"
    action = (
        step.get("action")
        or step.get("parameterized_action")
        or step.get("canonical_name")
    )
    if not action:
        return ""
    target = step.get("target") or step.get("parameterized_target")
    if target:
        return f"Apply {action} to {target}"
    return f"Apply {action}"


def _codex_avoid(procedure: Procedure) -> list[str]:
    avoid = [
        "Do not treat this Codex entry as executable authority.",
        "Do not claim success until an independent verifier observes the expected signal.",
    ]
    if resolve_codex_status(procedure) != "verified":
        avoid.append("Do not describe this candidate procedure as independently verified.")
    return avoid


def _codex_verification(
    procedure: Procedure,
    *,
    require_signed_receipt: bool = False,
) -> dict[str, str]:
    verified = _first_receipt(
        _signed_verified_receipts(procedure)
        if require_signed_receipt
        else _verified_receipts(procedure)
    )
    if verified is not None:
        payload = {
            "expected_signal": verified.expected_signal
            or "Independent verifier produced the expected success signal.",
            "status": "verified",
            "verifier_command": verified.verifier_command
            or "inspect attached verification receipt",
            "verifier_type": verified.verifier_type or verified.receipt_type,
            "receipt_id": verified.receipt_id,
            "receipts": [verified.to_dict()],
        }
        if require_signed_receipt:
            payload["signature_status"] = "signed_verified"
        return payload

    receipt_status = procedure_verification_status(procedure.receipts)
    failed = _first_receipt(_receipts_with_status(procedure, "failed"))
    if receipt_status == "failed_verification" and failed is not None:
        return {
            "expected_signal": failed.expected_signal
            or "Independent verifier should produce the expected success signal.",
            "status": "failed",
            "verifier_command": failed.verifier_command
            or "inspect attached verification receipt",
            "verifier_type": failed.verifier_type or failed.receipt_type,
        }

    return {
        "expected_signal": procedure.expected_outcome
        or "Independent verifier confirms the procedure works in the target environment.",
        "status": "required",
        "verifier_command": "external verifier required",
        "verifier_type": "manual_or_automated_verifier",
    }


def _codex_provenance_evidence(procedure: Procedure) -> list[str]:
    evidence = [
        f"support_count={procedure.support_count}",
        f"success_count={procedure.success_count}",
        f"confidence={procedure.confidence:.4f}",
    ]
    if procedure.source_episode_ids:
        evidence.append(f"source_episodes={len(procedure.source_episode_ids)}")
    return evidence


def _codex_learned_from(procedure: Procedure, *, store: Store) -> list[str]:
    learned_from = [f"howdex:{store.node_id}:{procedure.id}"]
    learned_from.extend(f"episode:{episode_id}" for episode_id in procedure.source_episode_ids)
    return learned_from


def _codex_risk_level(procedure: Procedure) -> str:
    classes = {
        str(step.get("side_effect_class") or "")
        for step in procedure.steps
        if isinstance(step, dict)
    }
    if {"destructive", "financial", "security_sensitive"} & classes:
        return "high"
    if {"external_write", "local_write", "write"} & classes:
        return "medium"
    if {"unknown"} & classes:
        return "unknown"
    return "low"


def _codex_requires_review(procedure: Procedure) -> bool:
    return _codex_risk_level(procedure) in {"medium", "high", "critical", "unknown"}


def _codex_tags(procedure: Procedure) -> list[str]:
    tags = {"howdex", "procedure"}
    for step in procedure.canonical_steps:
        name = str(step.get("canonical_name") or "").strip().lower()
        if name:
            tags.add(re.sub(r"[^a-z0-9_-]+", "-", name).strip("-"))
    return sorted(tag for tag in tags if tag)


def _verified_receipts(procedure: Procedure) -> list[VerificationReceipt]:
    return [
        receipt
        for receipt in _procedure_receipts(procedure)
        if (
            receipt.status == "verified"
            and bool(receipt.verifier_command)
            and bool(receipt.expected_signal)
            and bool(receipt.observed_signal)
            and receipt.exit_code == 0
        )
    ]


def _signed_verified_receipts(procedure: Procedure) -> list[VerificationReceipt]:
    return [
        receipt
        for receipt in _verified_receipts(procedure)
        if is_signed_verified_receipt(receipt)
    ]


def _receipts_with_status(procedure: Procedure, status: str) -> list[VerificationReceipt]:
    return [
        receipt
        for receipt in _procedure_receipts(procedure)
        if receipt.status == status
    ]


def _procedure_receipts(procedure: Procedure) -> list[VerificationReceipt]:
    receipts: list[VerificationReceipt] = []
    for payload in procedure.receipts:
        try:
            receipts.append(VerificationReceipt.from_dict(payload))
        except ValueError:
            continue
    return receipts


def _first_receipt(receipts: list[VerificationReceipt]) -> VerificationReceipt | None:
    return receipts[0] if receipts else None


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = value.strip()
        if text and text not in seen:
            seen.add(text)
            unique.append(text)
    return unique


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
