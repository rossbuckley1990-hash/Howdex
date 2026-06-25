from __future__ import annotations

import json
from pathlib import Path

import pytest

from howdex import Howdex
from howdex.attestation import (
    EVIDENCE_OBSERVED,
    SIGNED_VERIFIED,
    SignedReceiptAttestation,
    create_signed_attestation,
    is_signed_verified_receipt,
    load_attestation_file,
    verify_attestation,
)
from howdex.core.types import Procedure

HMAC_MATERIAL = "public-test-hmac-material"
SIGNER_ID = "local-verifier"
CREATED_AT = "2026-06-24T12:00:00Z"


def _seed(memory: Howdex, procedure_id: str = "deploy-api") -> Procedure:
    procedure = Procedure(
        id=procedure_id,
        task_signature="deploy api",
        steps=[{"action": "run verifier"}],
        success_rate=1.0,
        sample_count=1,
        support_count=1,
        success_count=1,
        confidence=0.8,
        source_episode_ids=["episode-1"],
    )
    memory.store.put_procedure(dict(procedure.__dict__))
    return procedure


def _signed_attestation(procedure_id: str) -> SignedReceiptAttestation:
    return create_signed_attestation(
        procedure_id=procedure_id,
        verifier_command="pytest -q",
        expected_signal="passed",
        observed_signal="12 passed in 0.31s",
        exit_code=0,
        environment_fingerprint={"python": "3.12", "os": "linux"},
        artifact_hashes={"dist/howdex.whl": "sha256:abc123"},
        created_at=CREATED_AT,
        key_material=HMAC_MATERIAL,
        signer_id=SIGNER_ID,
        attestation_id=f"att-{procedure_id}",
    )


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_create_signed_attestation():
    attestation = _signed_attestation("procedure-1")

    assert attestation.status == SIGNED_VERIFIED
    assert attestation.payload_hash and attestation.payload_hash.startswith("sha256:")
    assert attestation.signature and attestation.signature.startswith("hmac-sha256:")
    assert attestation.signer_id == SIGNER_ID


def test_verify_valid_signature():
    attestation = _signed_attestation("procedure-1")

    result = verify_attestation(attestation, key_material=HMAC_MATERIAL)

    assert result.status == SIGNED_VERIFIED
    assert result.evidence_valid is True
    assert result.payload_hash_valid is True
    assert result.signature_valid is True
    assert result.receipt_status == "verified"


def test_reject_tampered_payload():
    attestation = _signed_attestation("procedure-1").to_dict()
    attestation["observed_signal"] = "12 passed in 0.31s with changed evidence"

    result = verify_attestation(
        SignedReceiptAttestation.from_dict(attestation),
        key_material=HMAC_MATERIAL,
    )

    assert result.status == "invalid"
    assert result.evidence_valid is True
    assert result.payload_hash_valid is False
    assert result.signature_valid is False


def test_reject_wrong_observed_signal():
    attestation = create_signed_attestation(
        procedure_id="procedure-1",
        verifier_command="pytest -q",
        expected_signal="passed",
        observed_signal="1 failed",
        exit_code=0,
        key_material=HMAC_MATERIAL,
        signer_id=SIGNER_ID,
        created_at=CREATED_AT,
    )

    result = verify_attestation(attestation, key_material=HMAC_MATERIAL)

    assert result.status == "failed"
    assert result.evidence_valid is False
    assert "observed_signal did not contain expected_signal" in result.reasons


def test_reject_nonzero_exit_code():
    attestation = create_signed_attestation(
        procedure_id="procedure-1",
        verifier_command="pytest -q",
        expected_signal="passed",
        observed_signal="12 passed but process returned a failure code",
        exit_code=1,
        key_material=HMAC_MATERIAL,
        signer_id=SIGNER_ID,
        created_at=CREATED_AT,
    )

    result = verify_attestation(attestation, key_material=HMAC_MATERIAL)

    assert result.status == "failed"
    assert result.evidence_valid is False
    assert "exit_code was nonzero" in result.reasons


def test_import_bootproof_like_attestation(tmp_path):
    memory = Howdex(path=tmp_path / "bootproof.db", embedder="hashing")
    procedure = _seed(memory)
    path = _write(
        tmp_path / "attestation.json",
        {
            "schema": "bootproof/attestation/v1",
            "procedure_id": procedure.id,
            "verification": {
                "command": "python -m pytest",
                "expected_signal": "passed",
                "observed_signal": "443 passed",
                "exit_code": 0,
            },
            "environment": {"python": "3.12"},
            "artifact_hashes": {"pytest.log": "sha256:def456"},
        },
    )

    loaded = load_attestation_file(path)
    receipt = memory.import_signed_attestation(path)

    assert loaded.procedure_id == procedure.id
    assert receipt.status == "verified"
    assert receipt.metadata["attestation_status"] == EVIDENCE_OBSERVED
    assert receipt.metadata["signed"] is False
    assert is_signed_verified_receipt(receipt) is False


def test_codex_publish_require_signed_refuses_unsigned_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "unsigned.db", embedder="hashing")
    procedure = _seed(memory)
    memory.verify_procedure(
        procedure.id,
        verifier_type="test",
        verifier_command="pytest -q",
        expected_signal="passed",
        observed_signal="443 passed",
        exit_code=0,
    )

    with pytest.raises(ValueError, match="requires a signed verified receipt"):
        memory.publish_codex(tmp_path / "codex", require_signed_receipt=True)


def test_codex_publish_require_signed_with_valid_receipt_emits_verified(tmp_path):
    memory = Howdex(path=tmp_path / "signed.db", embedder="hashing")
    procedure = _seed(memory)
    attestation = _signed_attestation(procedure.id)
    path = _write(tmp_path / "signed-attestation.json", attestation.to_dict())

    receipt = memory.import_signed_attestation(path, key_material=HMAC_MATERIAL)
    published = memory.publish_codex(
        tmp_path / "codex",
        require_signed_receipt=True,
    )

    entry = json.loads(published["files"][0].read_text(encoding="utf-8"))
    assert is_signed_verified_receipt(receipt) is True
    assert entry["status"] == "verified"
    assert entry["verification"]["status"] == "verified"
    assert entry["verification"]["signature_status"] == "signed_verified"


def test_unsigned_receipt_does_not_pretend_to_be_signed(tmp_path):
    memory = Howdex(path=tmp_path / "receipt.db", embedder="hashing")
    procedure = _seed(memory)

    receipt = memory.verify_procedure(
        procedure.id,
        verifier_type="test",
        verifier_command="pytest -q",
        expected_signal="passed",
        observed_signal="443 passed",
        exit_code=0,
    )

    assert receipt.status == "verified"
    assert receipt.signature is None
    assert receipt.metadata.get("attestation_status") is None
    assert is_signed_verified_receipt(receipt) is False


def test_signed_attestation_schema_exists():
    schema_path = Path("codex/schemas/signed_receipt_attestation.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["title"] == "Howdex Signed Receipt Attestation"
    assert set(schema["required"]) == {
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
        "signature",
        "payload_hash",
        "status",
    }
    assert schema["properties"]["status"]["enum"] == [
        "signed_verified",
        "evidence_observed",
        "failed",
        "invalid",
        "unknown",
    ]


def test_cli_receipt_verify_and_procedure_status(tmp_path, capsys):
    from howdex.cli import main

    db = tmp_path / "cli.db"
    memory = Howdex(path=db, embedder="hashing")
    procedure = _seed(memory)
    attestation = _signed_attestation(procedure.id)
    path = _write(tmp_path / "signed-attestation.json", attestation.to_dict())
    memory.import_signed_attestation(path, key_material=HMAC_MATERIAL)
    memory.close()

    verify_code = main(
        [
            "--path",
            str(db),
            "--embedder",
            "hashing",
            "receipt",
            "verify",
            str(path),
            "--hmac-key",
            HMAC_MATERIAL,
        ]
    )
    status_code = main(
        [
            "--path",
            str(db),
            "--embedder",
            "hashing",
            "procedure",
            "status",
            procedure.id,
        ]
    )
    output = capsys.readouterr().out

    assert verify_code == 0
    assert status_code == 0
    assert '"status": "signed_verified"' in output
    assert '"signed_verified_receipt_count": 1' in output
