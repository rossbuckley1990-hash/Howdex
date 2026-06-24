"""Auditable optional abstraction proposals for semantic procedure equivalence.

The deterministic Howdex learning path remains the source of trusted procedure
memory. This module lets an LLM or deterministic dry-run provider propose that
multiple procedures may represent the same reusable workflow, while keeping the
proposal reversible, inspectable, and unverified until independent evidence
exists.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

PROPOSAL_STATUSES = {"proposed", "accepted", "rejected", "superseded"}
SOURCE_ARTIFACT_KEYS = {
    "artifact",
    "artifacts",
    "content",
    "file_content",
    "raw",
    "raw_example",
    "raw_examples",
    "raw_payload",
    "raw_source",
    "source_artifact",
    "source_artifacts",
    "source_code",
}
SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:api_?key|access_?key|secret|password|passwd|token|"
    r"authorization|credential|cookie|private_?key|client_?secret)(?:$|_)",
    re.IGNORECASE,
)
SECRET_TEXT_RE = re.compile(
    r"(bearer\s+)[a-z0-9._~+/=-]+|"
    r"((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+",
    re.IGNORECASE,
)
SOURCE_MARKER_RE = re.compile(
    r"(?ims)(```|^\s*def\s+\w+\s*\(|^\s*class\s+\w+|"
    r"^\s*import\s+\w+|^\s*from\s+\w+.*\s+import\s+|#!/usr/bin/env)"
)

_PROPOSALS: dict[str, "AbstractionProposal"] = {}
_CANDIDATE_ABSTRACTIONS: dict[str, dict[str, Any]] = {}


@dataclass
class AbstractionProposal:
    """One reversible proposal for semantic equivalence across procedures."""

    proposal_id: str
    source_procedure_ids: list[str]
    proposed_canonical_task: str
    proposed_equivalence_reason: str
    proposed_parameter_mapping: dict[str, Any] = field(default_factory=dict)
    proposed_shared_preconditions: list[str] = field(default_factory=list)
    proposed_shared_verifier: dict[str, Any] = field(default_factory=dict)
    model_name: str = "deterministic-dry-run"
    prompt_hash: str = ""
    response_hash: str = ""
    created_at: str = field(default_factory=lambda: _now_iso())
    status: str = "proposed"
    reviewer: str | None = None
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        status = str(self.status or "proposed").strip().lower()
        if status not in PROPOSAL_STATUSES:
            raise ValueError(f"invalid abstraction proposal status: {self.status!r}")
        self.status = status
        self.source_procedure_ids = _unique_strings(self.source_procedure_ids)
        self.proposed_parameter_mapping = _safe_object(self.proposed_parameter_mapping)
        self.proposed_shared_preconditions = _unique_strings(
            self.proposed_shared_preconditions
        )
        self.proposed_shared_verifier = _safe_object(self.proposed_shared_verifier)
        self.model_name = _safe_text(self.model_name) or "unknown"
        self.prompt_hash = _safe_text(self.prompt_hash)
        self.response_hash = _safe_text(self.response_hash)
        self.reviewer = _safe_text(self.reviewer) or None
        self.audit_log = [_safe_object(event) for event in self.audit_log]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AbstractionProposal":
        if not isinstance(payload, Mapping):
            raise ValueError("abstraction proposal must be an object")
        return cls(
            proposal_id=str(payload.get("proposal_id") or ""),
            source_procedure_ids=list(payload.get("source_procedure_ids") or []),
            proposed_canonical_task=str(payload.get("proposed_canonical_task") or ""),
            proposed_equivalence_reason=str(
                payload.get("proposed_equivalence_reason") or ""
            ),
            proposed_parameter_mapping=dict(
                payload.get("proposed_parameter_mapping") or {}
            ),
            proposed_shared_preconditions=list(
                payload.get("proposed_shared_preconditions") or []
            ),
            proposed_shared_verifier=dict(payload.get("proposed_shared_verifier") or {}),
            model_name=str(payload.get("model_name") or "unknown"),
            prompt_hash=str(payload.get("prompt_hash") or ""),
            response_hash=str(payload.get("response_hash") or ""),
            created_at=str(payload.get("created_at") or _now_iso()),
            status=str(payload.get("status") or "proposed"),
            reviewer=payload.get("reviewer"),
            audit_log=list(payload.get("audit_log") or []),
        )


def propose_abstraction(
    procedures: Sequence[Any],
    llm_provider: Any = None,
    dry_run: bool = False,
) -> AbstractionProposal:
    """Create an auditable proposal that procedures may be equivalent.

    If ``llm_provider`` is omitted, a deterministic dry-run proposal is created.
    A provider may propose fields, but provider output cannot mark procedures
    verified, attach receipts, delete sources, or publish Codex entries.
    """

    summaries = [_procedure_summary(procedure) for procedure in procedures]
    prompt_payload = {
        "task": "propose semantic equivalence between procedure summaries",
        "trust_boundary": [
            "LLM output is a proposal only.",
            "Do not mark procedures verified.",
            "Do not include source artifacts.",
            "Do not delete source procedures.",
        ],
        "procedures": summaries,
    }
    prompt_text = _canonical_json(prompt_payload)
    prompt_hash = _hash_text(prompt_text)

    if llm_provider is None:
        response_payload = _dry_run_response(summaries)
        model_name = "deterministic-dry-run"
    else:
        response_payload = _normalize_provider_response(
            _call_provider(llm_provider, prompt_text),
        )
        model_name = _provider_model_name(llm_provider)

    response_payload = _safe_object(response_payload)
    response_text = _canonical_json(response_payload)
    response_hash = _hash_text(response_text)
    created_at = _now_iso()
    proposal_id = "abp_" + _hash_text(
        _canonical_json(
            {
                "created_at": created_at,
                "prompt_hash": prompt_hash,
                "response_hash": response_hash,
                "source_ids": [summary["id"] for summary in summaries],
            }
        )
    )[:16]

    proposal = AbstractionProposal(
        proposal_id=proposal_id,
        source_procedure_ids=[summary["id"] for summary in summaries],
        proposed_canonical_task=str(
            response_payload.get("proposed_canonical_task")
            or _derive_canonical_task(summaries)
        ),
        proposed_equivalence_reason=str(
            response_payload.get("proposed_equivalence_reason")
            or "Candidate equivalence requires deterministic review."
        ),
        proposed_parameter_mapping=dict(
            response_payload.get("proposed_parameter_mapping") or {}
        ),
        proposed_shared_preconditions=list(
            response_payload.get("proposed_shared_preconditions") or []
        ),
        proposed_shared_verifier=dict(
            response_payload.get("proposed_shared_verifier") or {}
        ),
        model_name=model_name,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        created_at=created_at,
        status="proposed",
        audit_log=[
            _audit_event(
                "proposal_created",
                status="proposed",
                details={
                    "dry_run": bool(dry_run or llm_provider is None),
                    "source_procedure_count": len(summaries),
                    "prompt_hash": prompt_hash,
                    "response_hash": response_hash,
                    "source_artifacts_excluded": True,
                    "provider_status_ignored": response_payload.get("status"),
                    "provider_receipts_ignored": bool(response_payload.get("receipts")),
                },
            )
        ],
    )
    _PROPOSALS[proposal.proposal_id] = proposal
    return proposal


def accept_abstraction(
    proposal_id: str,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Accept a proposal and create an unverified candidate abstraction."""

    proposal = _require_proposal(proposal_id)
    if proposal.status == "rejected":
        raise ValueError("cannot accept a rejected abstraction proposal")
    if proposal.status == "superseded":
        raise ValueError("cannot accept a superseded abstraction proposal")

    proposal.status = "accepted"
    proposal.reviewer = _safe_text(reviewer) or proposal.reviewer
    candidate = {
        "id": f"candidate_{proposal.proposal_id}",
        "title": proposal.proposed_canonical_task,
        "task_signature": proposal.proposed_canonical_task,
        "status": "candidate",
        "procedure_status": "unverified",
        "verified": False,
        "source": "abstraction_proposal",
        "source_procedure_ids": list(proposal.source_procedure_ids),
        "learned_facts": [
            proposal.proposed_equivalence_reason,
            *proposal.proposed_shared_preconditions,
        ],
        "parameter_mapping": copy.deepcopy(proposal.proposed_parameter_mapping),
        "verification": {
            "status": "unverified",
            "reason": (
                "Accepted abstraction proposals remain candidate memory until "
                "independent verification receipts are attached."
            ),
            "proposed_shared_verifier": copy.deepcopy(
                proposal.proposed_shared_verifier
            ),
        },
        "receipts": [],
        "abstraction_proposal_id": proposal.proposal_id,
    }
    _CANDIDATE_ABSTRACTIONS[candidate["id"]] = candidate
    proposal.audit_log.append(
        _audit_event(
            "proposal_accepted",
            status="accepted",
            reviewer=proposal.reviewer,
            details={
                "candidate_id": candidate["id"],
                "candidate_status": "candidate",
                "verified": False,
            },
        )
    )
    return copy.deepcopy(candidate)


def reject_abstraction(
    proposal_id: str,
    reason: str,
    reviewer: str | None = None,
) -> AbstractionProposal:
    """Reject a proposal while preserving the proposal and audit trail."""

    proposal = _require_proposal(proposal_id)
    if proposal.status == "accepted":
        raise ValueError("accepted abstraction proposals cannot be rejected")
    proposal.status = "rejected"
    proposal.reviewer = _safe_text(reviewer) or proposal.reviewer
    proposal.audit_log.append(
        _audit_event(
            "proposal_rejected",
            status="rejected",
            reviewer=proposal.reviewer,
            details={"reason": _safe_text(reason)},
        )
    )
    return proposal


def list_abstraction_proposals(status: str | None = None) -> list[AbstractionProposal]:
    """Return known abstraction proposals in deterministic order."""

    expected = str(status).strip().lower() if status else None
    proposals = sorted(_PROPOSALS.values(), key=lambda item: item.created_at)
    if expected:
        proposals = [proposal for proposal in proposals if proposal.status == expected]
    return list(proposals)


def export_abstraction_audit_log() -> list[dict[str, Any]]:
    """Export proposal audit logs without raw source artifacts."""

    exported: list[dict[str, Any]] = []
    for proposal in list_abstraction_proposals():
        exported.append(
            {
                "proposal_id": proposal.proposal_id,
                "status": proposal.status,
                "source_procedure_ids": list(proposal.source_procedure_ids),
                "prompt_hash": proposal.prompt_hash,
                "response_hash": proposal.response_hash,
                "created_at": proposal.created_at,
                "reviewer": proposal.reviewer,
                "source_procedures_preserved": True,
                "events": copy.deepcopy(proposal.audit_log),
            }
        )
    return exported


def _reset_abstraction_state() -> None:
    """Clear in-memory abstraction state for tests."""

    _PROPOSALS.clear()
    _CANDIDATE_ABSTRACTIONS.clear()


def _procedure_summary(procedure: Any) -> dict[str, Any]:
    if hasattr(procedure, "to_dict"):
        raw = procedure.to_dict()
    elif isinstance(procedure, Mapping):
        raw = dict(procedure)
    else:
        raw = {
            "id": getattr(procedure, "id", ""),
            "task_signature": getattr(procedure, "task_signature", ""),
            "steps": getattr(procedure, "steps", []),
            "canonical_steps": getattr(procedure, "canonical_steps", []),
            "parameterized_steps": getattr(procedure, "parameterized_steps", []),
            "metadata": getattr(procedure, "metadata", {}),
        }

    safe = _safe_object(raw)
    procedure_id = str(
        safe.get("id")
        or safe.get("procedure_id")
        or safe.get("task_signature")
        or safe.get("title")
        or _hash_text(_canonical_json(safe))[:12]
    )
    return {
        "id": procedure_id,
        "title": safe.get("title"),
        "task_signature": safe.get("task_signature") or safe.get("signature"),
        "category": safe.get("category"),
        "tags": safe.get("tags", []),
        "status": safe.get("status") or safe.get("procedure_status"),
        "canonical_steps": safe.get("canonical_steps", safe.get("steps", [])),
        "parameterized_steps": safe.get("parameterized_steps", []),
        "parameterized_args": safe.get("parameterized_args", {}),
        "verification": safe.get("verification", {}),
    }


def _dry_run_response(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "proposed_canonical_task": _derive_canonical_task(summaries),
        "proposed_equivalence_reason": (
            "Deterministic dry-run proposal: these procedures share enough "
            "visible task and step structure to request human or policy review."
        ),
        "proposed_parameter_mapping": _derive_parameter_mapping(summaries),
        "proposed_shared_preconditions": _derive_shared_preconditions(summaries),
        "proposed_shared_verifier": _derive_shared_verifier(summaries),
    }


def _derive_canonical_task(summaries: list[dict[str, Any]]) -> str:
    labels = [
        str(summary.get("task_signature") or summary.get("title") or summary["id"])
        for summary in summaries
    ]
    tokens: list[str] = []
    for label in labels:
        tokens.extend(re.findall(r"[a-z0-9_./-]+", label.casefold()))
    common = _common_tokens(labels)
    if common:
        return " ".join(common[:8])
    return "candidate shared procedure" if summaries else "empty abstraction proposal"


def _derive_parameter_mapping(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    placeholders: dict[str, set[str]] = {}
    for summary in summaries:
        encoded = _canonical_json(summary)
        for placeholder in sorted(set(re.findall(r"<[A-Z][A-Z0-9_]*_\d+>", encoded))):
            placeholders.setdefault(placeholder, set()).add(summary["id"])
    return {
        placeholder: sorted(source_ids)
        for placeholder, source_ids in sorted(placeholders.items())
    }


def _derive_shared_preconditions(summaries: list[dict[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for summary in summaries:
        verification = summary.get("verification")
        if isinstance(verification, Mapping):
            expected = verification.get("expected_signal")
            if expected:
                candidates.append(f"verify signal: {expected}")
    return _unique_strings(candidates)


def _derive_shared_verifier(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    commands = []
    for summary in summaries:
        verification = summary.get("verification")
        if isinstance(verification, Mapping):
            command = verification.get("verifier_command")
            if command:
                commands.append(str(command))
    unique = _unique_strings(commands)
    if len(unique) == 1:
        return {"verifier_command": unique[0], "status": "proposed"}
    return {"status": "proposed"}


def _common_tokens(labels: list[str]) -> list[str]:
    token_sets = [
        set(re.findall(r"[a-z0-9]+", label.casefold()))
        for label in labels
        if label
    ]
    if not token_sets:
        return []
    common = set.intersection(*token_sets)
    return sorted(token for token in common if len(token) > 2)


def _call_provider(provider: Any, prompt_text: str) -> Any:
    if callable(provider):
        return provider(prompt_text)
    for method_name in ("propose_abstraction", "complete", "generate"):
        method = getattr(provider, method_name, None)
        if callable(method):
            return method(prompt_text)
    raise TypeError(
        "llm_provider must be callable or expose propose_abstraction/complete/generate"
    )


def _provider_model_name(provider: Any) -> str:
    for attribute in ("model_name", "model", "name"):
        value = getattr(provider, attribute, None)
        if value:
            return _safe_text(value)
    return type(provider).__name__


def _normalize_provider_response(response: Any) -> dict[str, Any]:
    if isinstance(response, Mapping):
        return dict(response)
    if hasattr(response, "to_dict"):
        return dict(response.to_dict())
    text = str(response or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"proposed_equivalence_reason": text}
    return dict(parsed) if isinstance(parsed, Mapping) else {"response": parsed}


def _require_proposal(proposal_id: str) -> AbstractionProposal:
    try:
        return _PROPOSALS[str(proposal_id)]
    except KeyError as exc:
        raise KeyError(f"unknown abstraction proposal: {proposal_id}") from exc


def _audit_event(
    event: str,
    *,
    status: str,
    reviewer: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event": _safe_text(event),
        "at": _now_iso(),
        "status": _safe_text(status),
        "reviewer": _safe_text(reviewer) or None,
        "details": _safe_object(dict(details or {})),
    }


def _safe_object(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, raw_item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key_text = str(key)
            key_folded = key_text.casefold()
            if key_folded in SOURCE_ARTIFACT_KEYS:
                safe[key_text] = "[source artifact omitted]"
                continue
            if SECRET_KEY_RE.search(key_text):
                safe[key_text] = "[secret redacted]"
                continue
            safe[key_text] = _safe_object(raw_item)
        return safe
    if isinstance(value, (list, tuple, set)):
        return [_safe_object(item) for item in list(value)[:50]]
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value)


def _safe_text(value: Any) -> str:
    text = str(value or "")
    text = SECRET_TEXT_RE.sub(_redacted_secret_text, text)
    if SOURCE_MARKER_RE.search(text):
        return "[source artifact omitted]"
    if len(text) > 1_000:
        return text[:500] + "\n[... omitted for abstraction audit ...]\n" + text[-200:]
    return text


def _redacted_secret_text(match: re.Match[str]) -> str:
    prefix = next((group for group in match.groups() if group), "")
    return f"{prefix}[secret redacted]" if prefix else "[secret redacted]"


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values or []:
        text = _safe_text(value)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "AbstractionProposal",
    "accept_abstraction",
    "export_abstraction_audit_log",
    "list_abstraction_proposals",
    "propose_abstraction",
    "reject_abstraction",
]
