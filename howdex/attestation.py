"""Signed verification attestations for Howdex procedures.

This module deliberately uses only the Python standard library. The initial
signature format is HMAC-SHA256 over a canonical JSON payload hash. That gives
Howdex deterministic, inspectable tamper evidence without making any external
cryptography package mandatory.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from howdex.core.receipts import VerificationReceipt

SIGNATURE_ALGORITHM = "hmac-sha256"
SIGNED_VERIFIED = "signed_verified"
EVIDENCE_OBSERVED = "evidence_observed"
ATTESTATION_FAILED = "failed"
ATTESTATION_INVALID = "invalid"
ATTESTATION_UNKNOWN = "unknown"

_SIGNABLE_FIELDS = (
    "attestation_id",
    "receipt_id",
    "procedure_id",
    "verifier_command",
    "expected_signal",
    "observed_signal",
    "exit_code",
    "environment_fingerprint",
    "artifact_hashes",
    "created_at",
    "signer_id",
    "signature_algorithm",
)


@dataclass(frozen=True)
class SignedReceiptAttestation:
    """Portable signed evidence that a verifier observed a procedure working."""

    attestation_id: str
    receipt_id: str
    procedure_id: str | None
    verifier_command: str
    expected_signal: str
    observed_signal: str
    exit_code: int
    environment_fingerprint: dict[str, Any] = field(default_factory=dict)
    artifact_hashes: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    signer_id: str | None = None
    signature_algorithm: str = SIGNATURE_ALGORITHM
    signature: str | None = None
    payload_hash: str | None = None
    status: str = ATTESTATION_UNKNOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "attestation_id", _text(self.attestation_id) or _stable_id())
        object.__setattr__(self, "receipt_id", _text(self.receipt_id) or self.attestation_id)
        object.__setattr__(self, "procedure_id", _text(self.procedure_id))
        object.__setattr__(self, "verifier_command", _text(self.verifier_command) or "")
        object.__setattr__(self, "expected_signal", _text(self.expected_signal) or "")
        object.__setattr__(self, "observed_signal", _text(self.observed_signal) or "")
        object.__setattr__(self, "exit_code", int(self.exit_code))
        object.__setattr__(
            self,
            "environment_fingerprint",
            _safe_mapping(self.environment_fingerprint),
        )
        object.__setattr__(self, "artifact_hashes", _safe_mapping(self.artifact_hashes))
        object.__setattr__(self, "created_at", _text(self.created_at) or _iso_now())
        object.__setattr__(self, "signer_id", _text(self.signer_id))
        object.__setattr__(
            self,
            "signature_algorithm",
            (_text(self.signature_algorithm) or SIGNATURE_ALGORITHM).lower(),
        )
        object.__setattr__(self, "signature", _text(self.signature))
        object.__setattr__(self, "payload_hash", _text(self.payload_hash))
        object.__setattr__(self, "status", _text(self.status) or ATTESTATION_UNKNOWN)

    def signable_payload(self) -> dict[str, Any]:
        """Return the canonical payload covered by payload_hash/signature."""
        payload = self.to_dict(include_signature=False)
        return {field: payload.get(field) for field in _SIGNABLE_FIELDS}

    def to_dict(self, *, include_signature: bool = True) -> dict[str, Any]:
        payload = {
            "artifact_hashes": self.artifact_hashes,
            "attestation_id": self.attestation_id,
            "created_at": self.created_at,
            "environment_fingerprint": self.environment_fingerprint,
            "exit_code": self.exit_code,
            "expected_signal": self.expected_signal,
            "observed_signal": self.observed_signal,
            "payload_hash": self.payload_hash,
            "procedure_id": self.procedure_id,
            "receipt_id": self.receipt_id,
            "signature_algorithm": self.signature_algorithm,
            "signer_id": self.signer_id,
            "status": self.status,
            "verifier_command": self.verifier_command,
        }
        if include_signature:
            payload["signature"] = self.signature
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SignedReceiptAttestation:
        if not isinstance(payload, Mapping):
            raise ValueError("signed attestation must be a JSON object")
        return cls(
            attestation_id=str(payload.get("attestation_id") or payload.get("id") or _stable_id()),
            receipt_id=str(payload.get("receipt_id") or payload.get("attestation_id") or ""),
            procedure_id=payload.get("procedure_id"),
            verifier_command=str(
                payload.get("verifier_command")
                or payload.get("verification_command")
                or payload.get("command")
                or ""
            ),
            expected_signal=str(payload.get("expected_signal") or ""),
            observed_signal=str(payload.get("observed_signal") or ""),
            exit_code=int(payload.get("exit_code") or 0),
            environment_fingerprint=dict(
                payload.get("environment_fingerprint")
                or payload.get("environment")
                or {}
            ),
            artifact_hashes=dict(payload.get("artifact_hashes") or {}),
            created_at=payload.get("created_at") or payload.get("verified_at"),
            signer_id=payload.get("signer_id"),
            signature_algorithm=str(payload.get("signature_algorithm") or SIGNATURE_ALGORITHM),
            signature=payload.get("signature"),
            payload_hash=payload.get("payload_hash"),
            status=str(payload.get("status") or ATTESTATION_UNKNOWN),
        )


@dataclass(frozen=True)
class AttestationVerification:
    """Inspectable result of attestation evidence and signature checks."""

    status: str
    evidence_valid: bool
    payload_hash_valid: bool
    signature_valid: bool | None
    reasons: list[str]
    receipt_status: str


def create_signed_attestation(
    *,
    procedure_id: str,
    verifier_command: str,
    expected_signal: str,
    observed_signal: str,
    exit_code: int,
    key_material: str | bytes,
    signer_id: str,
    environment_fingerprint: Mapping[str, Any] | None = None,
    artifact_hashes: Mapping[str, Any] | None = None,
    created_at: str | None = None,
    attestation_id: str | None = None,
    receipt_id: str | None = None,
) -> SignedReceiptAttestation:
    """Create a deterministic HMAC-signed receipt attestation."""
    base = SignedReceiptAttestation(
        attestation_id=attestation_id or _stable_id(),
        receipt_id=receipt_id or attestation_id or "",
        procedure_id=procedure_id,
        verifier_command=verifier_command,
        expected_signal=expected_signal,
        observed_signal=observed_signal,
        exit_code=exit_code,
        environment_fingerprint=dict(environment_fingerprint or {}),
        artifact_hashes=dict(artifact_hashes or {}),
        created_at=created_at,
        signer_id=signer_id,
        signature_algorithm=SIGNATURE_ALGORITHM,
    )
    payload_hash = compute_payload_hash(base)
    signature = sign_payload_hash(payload_hash, key_material)
    verification = verify_attestation(
        SignedReceiptAttestation(
            **{
                **base.to_dict(include_signature=False),
                "payload_hash": payload_hash,
                "signature": signature,
            }
        ),
        key_material=key_material,
    )
    return SignedReceiptAttestation(
        **{
            **base.to_dict(include_signature=False),
            "payload_hash": payload_hash,
            "signature": signature,
            "status": verification.status,
        }
    )


def load_attestation_file(path: str | Path) -> SignedReceiptAttestation:
    """Load a Howdex or BootProof-like attestation JSON file."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed attestation JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"attestation JSON must be an object: {source}")
    if _looks_like_bootproof(payload):
        return _bootproof_like_to_attestation(payload)
    return SignedReceiptAttestation.from_dict(payload)


def verify_attestation(
    attestation: SignedReceiptAttestation | Mapping[str, Any],
    *,
    key_material: str | bytes | None = None,
) -> AttestationVerification:
    """Verify evidence, payload hash, and signature when key material exists."""
    att = (
        attestation
        if isinstance(attestation, SignedReceiptAttestation)
        else SignedReceiptAttestation.from_dict(attestation)
    )
    reasons: list[str] = []
    evidence_valid = True
    if att.exit_code != 0:
        evidence_valid = False
        reasons.append("exit_code was nonzero")
    if not att.expected_signal:
        evidence_valid = False
        reasons.append("expected_signal is missing")
    elif att.expected_signal.casefold() not in att.observed_signal.casefold():
        evidence_valid = False
        reasons.append("observed_signal did not contain expected_signal")

    expected_hash = compute_payload_hash(att)
    if att.payload_hash:
        payload_hash_valid = hmac.compare_digest(att.payload_hash, expected_hash)
        if not payload_hash_valid:
            reasons.append("payload_hash did not match canonical payload")
    else:
        payload_hash_valid = not bool(att.signature)
        if att.signature:
            reasons.append("signed attestation is missing payload_hash")

    signature_valid: bool | None
    if not att.signature:
        signature_valid = None
        if evidence_valid and payload_hash_valid:
            reasons.append("unsigned evidence observed")
    elif key_material is None:
        signature_valid = None
        reasons.append("signature key material was not supplied")
    elif att.signature_algorithm != SIGNATURE_ALGORITHM:
        signature_valid = False
        reasons.append(f"unsupported signature algorithm: {att.signature_algorithm}")
    else:
        expected_signature = sign_payload_hash(expected_hash, key_material)
        signature_valid = hmac.compare_digest(att.signature, expected_signature)
        if not signature_valid:
            reasons.append("signature did not validate")

    if evidence_valid and payload_hash_valid and signature_valid is True:
        return AttestationVerification(
            status=SIGNED_VERIFIED,
            evidence_valid=True,
            payload_hash_valid=True,
            signature_valid=True,
            reasons=reasons,
            receipt_status="verified",
        )
    if not evidence_valid:
        return AttestationVerification(
            status=ATTESTATION_FAILED,
            evidence_valid=False,
            payload_hash_valid=payload_hash_valid,
            signature_valid=signature_valid,
            reasons=reasons,
            receipt_status="failed",
        )
    if att.signature and (not payload_hash_valid or signature_valid is False):
        return AttestationVerification(
            status=ATTESTATION_INVALID,
            evidence_valid=True,
            payload_hash_valid=payload_hash_valid,
            signature_valid=signature_valid,
            reasons=reasons,
            receipt_status="failed",
        )
    if not att.signature and evidence_valid and payload_hash_valid:
        return AttestationVerification(
            status=EVIDENCE_OBSERVED,
            evidence_valid=True,
            payload_hash_valid=payload_hash_valid,
            signature_valid=None,
            reasons=reasons,
            receipt_status="verified",
        )
    return AttestationVerification(
        status=ATTESTATION_UNKNOWN,
        evidence_valid=evidence_valid,
        payload_hash_valid=payload_hash_valid,
        signature_valid=signature_valid,
        reasons=reasons,
        receipt_status="unknown",
    )


def attestation_to_receipt(
    attestation: SignedReceiptAttestation | Mapping[str, Any],
    verification: AttestationVerification | None = None,
) -> "VerificationReceipt":
    """Convert one attestation into Howdex's existing receipt representation."""
    from howdex.core.receipts import VerificationReceipt

    att = (
        attestation
        if isinstance(attestation, SignedReceiptAttestation)
        else SignedReceiptAttestation.from_dict(attestation)
    )
    verification = verification or verify_attestation(att)
    return VerificationReceipt(
        receipt_id=att.receipt_id,
        procedure_id=att.procedure_id,
        verifier_type="signed_attestation"
        if verification.status == SIGNED_VERIFIED
        else "attestation",
        verifier_command=att.verifier_command,
        expected_signal=att.expected_signal,
        observed_signal=att.observed_signal,
        exit_code=att.exit_code,
        verified_at=att.created_at,
        environment_fingerprint=att.environment_fingerprint,
        artifact_hashes=att.artifact_hashes,
        status=verification.receipt_status,
        digest=att.payload_hash,
        signature=att.signature,
        metadata={
            "attestation_id": att.attestation_id,
            "attestation_status": verification.status,
            "payload_hash": att.payload_hash,
            "signature_algorithm": att.signature_algorithm,
            "signature_valid": verification.signature_valid,
            "signed": verification.status == SIGNED_VERIFIED,
            "signer_id": att.signer_id,
            "verification_reasons": list(verification.reasons),
        },
        raw_payload=None,
    )


def is_signed_verified_receipt(
    receipt: "VerificationReceipt" | Mapping[str, Any],
) -> bool:
    """Return whether a stored receipt represents validated signed evidence."""
    from howdex.core.receipts import VerificationReceipt

    normalized = (
        receipt if isinstance(receipt, VerificationReceipt) else VerificationReceipt.from_dict(receipt)
    )
    metadata = normalized.metadata or {}
    return (
        normalized.status == "verified"
        and bool(normalized.signature)
        and bool(normalized.digest)
        and metadata.get("attestation_status") == SIGNED_VERIFIED
        and metadata.get("signature_valid") is True
        and metadata.get("signed") is True
    )


def compute_payload_hash(
    attestation: SignedReceiptAttestation | Mapping[str, Any],
) -> str:
    att = (
        attestation
        if isinstance(attestation, SignedReceiptAttestation)
        else SignedReceiptAttestation.from_dict(attestation)
    )
    encoded = canonical_json(att.signable_payload()).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def sign_payload_hash(payload_hash: str, key_material: str | bytes) -> str:
    key = key_material if isinstance(key_material, bytes) else str(key_material).encode("utf-8")
    digest = hmac.new(key, payload_hash.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{SIGNATURE_ALGORITHM}:{digest}"


def canonical_json(payload: Any) -> str:
    """Return deterministic JSON for attestation hashing."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _looks_like_bootproof(payload: Mapping[str, Any]) -> bool:
    return (
        "verification" in payload
        or str(payload.get("schema") or "").casefold().startswith("bootproof")
    )


def _bootproof_like_to_attestation(payload: Mapping[str, Any]) -> SignedReceiptAttestation:
    verification = payload.get("verification")
    if not isinstance(verification, Mapping):
        verification = {}
    environment = (
        payload.get("environment_fingerprint")
        or payload.get("environment")
        or verification.get("environment")
        or payload.get("environment_metadata")
        or {}
    )
    artifact_hashes = payload.get("artifact_hashes") or verification.get("artifact_hashes") or {}
    result = verification.get("result")
    if not isinstance(result, Mapping):
        result = {}
    return SignedReceiptAttestation(
        attestation_id=str(
            payload.get("attestation_id")
            or payload.get("id")
            or verification.get("attestation_id")
            or _stable_id()
        ),
        receipt_id=str(
            payload.get("receipt_id")
            or verification.get("receipt_id")
            or payload.get("attestation_id")
            or ""
        ),
        procedure_id=payload.get("procedure_id") or verification.get("procedure_id"),
        verifier_command=str(
            verification.get("verifier_command")
            or verification.get("command")
            or payload.get("verifier_command")
            or payload.get("command")
            or ""
        ),
        expected_signal=str(
            verification.get("expected_signal")
            or payload.get("expected_signal")
            or ""
        ),
        observed_signal=str(
            verification.get("observed_signal")
            or verification.get("observed")
            or result.get("observed_signal")
            or payload.get("observed_signal")
            or ""
        ),
        exit_code=int(
            verification.get("exit_code")
            if verification.get("exit_code") is not None
            else payload.get("exit_code", 0)
        ),
        environment_fingerprint=dict(environment or {}),
        artifact_hashes=dict(artifact_hashes or {}),
        created_at=(
            verification.get("created_at")
            or verification.get("verified_at")
            or payload.get("created_at")
            or payload.get("verified_at")
        ),
        signer_id=payload.get("signer_id") or verification.get("signer_id"),
        signature_algorithm=str(
            payload.get("signature_algorithm")
            or verification.get("signature_algorithm")
            or SIGNATURE_ALGORITHM
        ),
        signature=payload.get("signature") or verification.get("signature"),
        payload_hash=payload.get("payload_hash") or verification.get("payload_hash"),
        status=str(payload.get("status") or verification.get("status") or ATTESTATION_UNKNOWN),
    )


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("attestation environment and artifact hashes must be objects")
    from howdex.core.tool_calls import redact_secrets

    redacted, _ = redact_secrets(dict(value))
    encoded = json.dumps(redacted, sort_keys=True, default=str)
    decoded = json.loads(encoded)
    return decoded if isinstance(decoded, dict) else {}


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stable_id() -> str:
    return str(uuid.uuid4())


__all__ = [
    "ATTESTATION_FAILED",
    "ATTESTATION_INVALID",
    "ATTESTATION_UNKNOWN",
    "AttestationVerification",
    "EVIDENCE_OBSERVED",
    "SIGNED_VERIFIED",
    "SIGNATURE_ALGORITHM",
    "SignedReceiptAttestation",
    "attestation_to_receipt",
    "canonical_json",
    "compute_payload_hash",
    "create_signed_attestation",
    "is_signed_verified_receipt",
    "load_attestation_file",
    "sign_payload_hash",
    "verify_attestation",
]
