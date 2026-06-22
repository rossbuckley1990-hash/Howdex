"""Optional, deterministic verification receipts for learned procedures."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from howdex.core.tool_calls import redact_secrets

VERIFICATION_STATUSES = {
    "unverified",
    "verified",
    "failed_verification",
    "mixed",
}

_PASS_STATUSES = {
    "ok",
    "pass",
    "passed",
    "success",
    "succeeded",
    "valid",
    "verified",
}
_FAIL_STATUSES = {
    "error",
    "fail",
    "failed",
    "failure",
    "invalid",
}
_UNKNOWN_STATUSES = {
    "",
    "none",
    "partial",
    "pending",
    "skipped",
    "unknown",
    "unverified",
}
_SECRET_TEXT_RE = re.compile(
    r"(?i)(--?(?:api[-_]?key|password|secret|token|authorization)"
    r"(?:=|\s+))([^\s]+)"
)
_URI_CREDENTIAL_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")


@dataclass(frozen=True)
class VerificationReceipt:
    """One optional piece of evidence that a procedure worked."""

    receipt_type: str
    status: str
    command: str | None = None
    target: str | None = None
    timestamp: float | None = None
    digest: str | None = None
    signature: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        receipt_type = str(self.receipt_type or "").strip().lower()
        if not receipt_type:
            raise ValueError("verification receipt requires receipt_type")
        status = normalize_receipt_status(self.status)
        object.__setattr__(self, "receipt_type", receipt_type)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "command", _safe_text(self.command))
        object.__setattr__(self, "target", _safe_text(self.target))
        object.__setattr__(self, "timestamp", _parse_timestamp(self.timestamp))
        object.__setattr__(self, "digest", _safe_text(self.digest))
        object.__setattr__(self, "signature", _safe_text(self.signature))
        object.__setattr__(self, "source", _safe_text(self.source))
        object.__setattr__(self, "metadata", _safe_mapping(self.metadata))
        if self.raw_payload is not None:
            object.__setattr__(
                self,
                "raw_payload",
                _safe_mapping(self.raw_payload),
            )

    @property
    def receipt_id(self) -> str:
        """Return a stable content identity for idempotent attachment."""
        encoded = json.dumps(
            self._payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, **self._payload()}

    def _payload(self) -> dict[str, Any]:
        return {
            "receipt_type": self.receipt_type,
            "status": self.status,
            "command": self.command,
            "target": self.target,
            "timestamp": self.timestamp,
            "digest": self.digest,
            "signature": self.signature,
            "source": self.source,
            "metadata": self.metadata,
            "raw_payload": self.raw_payload,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> VerificationReceipt:
        if not isinstance(payload, Mapping):
            raise ValueError("verification receipt must be an object")
        status = payload.get("status")
        if status is None:
            status = payload.get("passed", payload.get("success"))
        return cls(
            receipt_type=str(payload.get("receipt_type") or ""),
            status=status,
            command=_first(payload, "command", "verification_command"),
            target=_first(
                payload,
                "target",
                "verification_target",
                "artifact",
            ),
            timestamp=_first(
                payload,
                "timestamp",
                "created_at",
                "verified_at",
            ),
            digest=_first(payload, "digest", "hash", "sha256"),
            signature=payload.get("signature"),
            source=_first(payload, "source", "source_path", "source_uri"),
            metadata=payload.get("metadata") or {},
            raw_payload=payload.get("raw_payload"),
        )


def normalize_receipt_status(value: Any) -> str:
    """Normalize provider-specific results to pass, fail, or unknown."""
    if isinstance(value, bool):
        return "pass" if value else "fail"
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in _PASS_STATUSES:
        return "pass"
    if normalized in _FAIL_STATUSES:
        return "fail"
    if normalized in _UNKNOWN_STATUSES:
        return "unknown"
    raise ValueError(f"unsupported verification receipt status: {value!r}")


def procedure_verification_status(
    receipts: list[VerificationReceipt | Mapping[str, Any]],
) -> str:
    """Summarize attached receipt results without overclaiming."""
    statuses = {
        (
            receipt.status
            if isinstance(receipt, VerificationReceipt)
            else VerificationReceipt.from_dict(receipt).status
        )
        for receipt in receipts
    }
    has_pass = "pass" in statuses
    has_fail = "fail" in statuses
    if has_pass and has_fail:
        return "mixed"
    if has_fail:
        return "failed_verification"
    if has_pass:
        return "verified"
    return "unverified"


def parse_bootproof_attestation(
    path: str | Path = ".bootproof/attestation.json",
) -> VerificationReceipt | None:
    """Parse a BootProof-like attestation without importing BootProof."""
    source = Path(path)
    if not source.is_file():
        return None
    try:
        raw_bytes = source.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed BootProof attestation: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"BootProof attestation must be an object: {source}")

    verification = payload.get("verification")
    if not isinstance(verification, dict):
        verification = {}
    repository = payload.get("repo")
    if not isinstance(repository, dict):
        repository = {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = {
        **metadata,
        "schema": payload.get("schema"),
        "trust": payload.get("trust"),
    }

    return VerificationReceipt(
        receipt_type="bootproof",
        status=_bootproof_status(payload, verification),
        command=_first(verification, "command")
        or _first(payload, "command"),
        target=_first(
            verification,
            "target",
            "artifact",
            "repository",
        )
        or _first(payload, "target", "artifact")
        or _first(repository, "path", "remote", "commit"),
        timestamp=_first(
            verification,
            "timestamp",
            "verified_at",
            "created_at",
        )
        or _first(
            payload,
            "timestamp",
            "verified_at",
            "finishedAt",
            "created_at",
            "startedAt",
        ),
        digest=_first(verification, "digest", "hash", "sha256")
        or _first(payload, "digest", "hash", "sha256")
        or f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
        signature=_first(verification, "signature")
        or _first(payload, "signature"),
        source=str(source),
        metadata=metadata,
        raw_payload=payload,
    )


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _bootproof_status(
    payload: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> Any:
    for candidate in (verification, payload):
        explicit = _first(candidate, "status", "passed", "success")
        if explicit is not None:
            return explicit
        result = candidate.get("result")
        if not isinstance(result, Mapping) and result not in (None, ""):
            return result

    for candidate in (
        verification.get("result"),
        payload.get("result"),
    ):
        if not isinstance(candidate, Mapping):
            continue
        explicit = _first(candidate, "status", "passed", "success", "verified")
        if explicit is not None:
            return explicit
        if "booted" in candidate or "healthVerified" in candidate:
            return bool(candidate.get("booted")) and bool(
                candidate.get("healthVerified")
            )
    return "unknown"


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("receipt metadata and raw_payload must be objects")
    redacted, _ = redact_secrets(dict(value))
    encoded = json.dumps(redacted, sort_keys=True, default=str)
    decoded = json.loads(encoded)
    return decoded if isinstance(decoded, dict) else {}


def _safe_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    text = _SECRET_TEXT_RE.sub(r"\1[REDACTED]", text)
    return _URI_CREDENTIAL_RE.sub(r"\1[REDACTED]\3", text)


def _parse_timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("verification receipt timestamp must be numeric or ISO-8601")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError as exc:
        raise ValueError(
            "verification receipt timestamp must be numeric or ISO-8601"
        ) from exc
