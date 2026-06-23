"""Tests for optional, provider-neutral procedure verification receipts."""

from __future__ import annotations

import json
import sqlite3

import pytest

from howdex import Howdex, VerificationReceipt
from howdex.core.guidance import render_agent_guidance
from howdex.core.receipts import parse_bootproof_attestation
from howdex.core.types import Procedure


def _seed(memory: Howdex, procedure_id: str = "verified-deploy") -> Procedure:
    procedure = Procedure(
        id=procedure_id,
        task_signature="deploy api",
        steps=[{"action": "deploy_service"}],
        success_rate=1.0,
        sample_count=3,
        support_count=3,
        success_count=3,
        confidence=0.9,
        source_episode_ids=["episode-1"],
    )
    memory.store.put_procedure(dict(procedure.__dict__))
    return procedure


def test_attach_generic_receipt_is_idempotent(tmp_path):
    memory = Howdex(path=tmp_path / "receipts.db", embedder="hashing")
    procedure = _seed(memory)
    receipt = VerificationReceipt(
        receipt_type="test",
        command="pytest -q",
        status="passed",
        timestamp="2026-06-22T12:00:00Z",
        digest="sha256:abc123",
        metadata={"suite": "unit"},
    )

    first = memory.attach_receipt(procedure.id, receipt)
    second = memory.attach_receipt(procedure.id, receipt.to_dict())
    attached = memory.list_receipts(procedure.id)
    stored = memory.get_procedure("deploy api", min_confidence=0.0)

    assert first == second
    assert attached == [first]
    assert first.procedure_id == procedure.id
    assert first.task_signature == procedure.task_signature
    assert first.status == "verified"
    assert stored is not None
    assert stored.receipts == [first.to_dict()]
    assert memory.procedure_verification_status(procedure.id) == "verified"
    assert memory.procedure_status(procedure.id) == "verified"


def test_structured_receipt_creation_and_round_trip():
    receipt = VerificationReceipt(
        receipt_id="receipt-release-1",
        procedure_id="deploy-release",
        task_signature="deploy api",
        verifier_type="test",
        verifier_command="pytest -q",
        expected_signal="12 passed",
        observed_signal="12 passed in 0.4s",
        exit_code=0,
        verified_at="2026-06-23T10:30:00Z",
        environment_fingerprint={
            "os": "linux",
            "python": "3.12",
        },
        artifact_hashes={"dist/app.whl": "sha256:abc123"},
        source_episode_id="episode-release",
        status="verified",
    )

    restored = VerificationReceipt.from_dict(receipt.to_dict())

    assert restored == receipt
    assert restored.receipt_id == "receipt-release-1"
    assert restored.verifier_type == "test"
    assert restored.receipt_type == "test"
    assert restored.verifier_command == "pytest -q"
    assert restored.command == "pytest -q"
    assert restored.expected_signal == "12 passed"
    assert restored.observed_signal == "12 passed in 0.4s"
    assert restored.exit_code == 0
    assert restored.verified_at == restored.timestamp
    assert restored.environment_fingerprint["python"] == "3.12"
    assert restored.artifact_hashes["dist/app.whl"] == "sha256:abc123"
    assert restored.source_episode_id == "episode-release"


def test_procedure_status_distinguishes_episode_support_from_unverified(
    tmp_path,
):
    memory = Howdex(path=tmp_path / "trust.db", embedder="hashing")
    supported = _seed(memory, "supported")
    unsupported = Procedure(
        id="unsupported",
        task_signature="unobserved operation",
        steps=[{"action": "inspect_file"}],
    )
    memory.store.put_procedure(dict(unsupported.__dict__))

    assert memory.procedure_status(supported.id) == ("observed_episode_support")
    assert memory.procedure_verification_status(supported.id) == ("unverified")
    assert memory.procedure_status(unsupported.id) == "unverified"


def test_verify_procedure_creates_independent_evidence(tmp_path):
    memory = Howdex(path=tmp_path / "verify.db", embedder="hashing")
    procedure = _seed(memory)

    receipt = memory.verify_procedure(
        procedure.id,
        verifier_type="test",
        verifier_command="pytest -q",
        expected_signal="234 passed",
        observed_signal="234 passed in 2.1s",
        exit_code=0,
        verified_at="2026-06-23T12:00:00Z",
        environment_fingerprint={
            "platform": "linux-x86_64",
            "python": "3.12",
        },
        artifact_hashes={"wheel": "sha256:verified"},
        source_episode_id="verification-episode",
    )

    assert receipt.status == "verified"
    assert receipt.procedure_id == procedure.id
    assert receipt.task_signature == procedure.task_signature
    assert memory.procedure_status(procedure.id) == "verified"
    assert memory.list_receipts(procedure.id) == [receipt]


def test_verify_procedure_failed_signal_sets_failed_status(tmp_path):
    memory = Howdex(path=tmp_path / "failed-verify.db", embedder="hashing")
    procedure = _seed(memory)

    receipt = memory.verify_procedure(
        procedure.id,
        verifier_type="http_health",
        verifier_command="curl http://127.0.0.1/health",
        expected_signal="HTTP 200",
        observed_signal="HTTP 503",
        exit_code=0,
    )

    assert receipt.status == "failed"
    assert memory.procedure_status(procedure.id) == ("failed_verification")


def test_verify_procedure_cannot_overclaim_verified_status(tmp_path):
    memory = Howdex(path=tmp_path / "overclaim.db", embedder="hashing")
    procedure = _seed(memory)

    with pytest.raises(ValueError, match="requires exit_code=0"):
        memory.verify_procedure(
            procedure.id,
            verifier_type="test",
            verifier_command="pytest -q",
            expected_signal="passed",
            observed_signal="1 failed",
            exit_code=1,
            status="verified",
        )

    assert memory.list_receipts(procedure.id) == []
    assert memory.procedure_status(procedure.id) == (
        "observed_episode_support"
    )


def test_verified_procedure_suggestion_exposes_receipt_status(tmp_path):
    memory = Howdex(path=tmp_path / "suggestion.db", embedder="hashing")
    procedure = _seed(memory)
    memory.attach_receipt(
        procedure.id,
        {
            "receipt_type": "build",
            "target": "dist/howdex.whl",
            "status": "pass",
            "digest": "sha256:def456",
        },
    )

    suggestion = memory.suggest_procedure("deploy api")[0]
    guidance = memory.render_procedure_guidance(suggestion)

    assert suggestion.verification_status == "verified"
    assert suggestion.procedure_status == "verified"
    assert suggestion.procedure_verified is True
    assert len(suggestion.verification_receipts) == 1
    assert suggestion.to_dict()["verification_status"] == "verified"
    assert suggestion.to_dict()["procedure_status"] == "verified"
    assert "Verification status: verified (1 receipts)" in guidance


def test_stale_receipt_marks_procedure_stale(tmp_path):
    memory = Howdex(path=tmp_path / "stale.db", embedder="hashing")
    procedure = _seed(memory)
    memory.attach_receipt(
        procedure.id,
        {
            "verifier_type": "build",
            "status": "stale",
            "verifier_command": "python -m build",
            "expected_signal": "wheel created",
            "observed_signal": "wheel created",
            "exit_code": 0,
        },
    )

    suggestion = memory.suggest_procedure("deploy api")[0]
    guidance = memory.render_procedure_guidance(suggestion)

    assert memory.procedure_status(procedure.id) == "stale"
    assert suggestion.procedure_status == "stale"
    assert "Verification status: stale" in guidance
    assert "verification evidence is stale" in guidance


def test_agent_guidance_warns_when_procedure_is_unverified():
    guidance = render_agent_guidance(
        [
            {
                "procedure_id": "unverified",
                "task_signature": "unverified deployment",
                "steps": [{"action": "deploy_service"}],
            }
        ],
        objective="Deploy the service",
        include_source=False,
    )

    assert "Procedure trust:" in guidance
    assert "unverified deployment: unverified" in guidance
    assert "Unverified memory" in guidance
    assert "until a real verifier succeeds" in guidance


def test_failed_receipt_dominates_verified_receipt(tmp_path):
    memory = Howdex(path=tmp_path / "failed.db", embedder="hashing")
    procedure = _seed(memory)
    memory.attach_receipt(
        procedure.id,
        {"receipt_type": "test", "status": "failed", "target": "unit"},
    )

    failed = memory.suggest_procedure("deploy api")[0]
    assert failed.verification_status == "failed_verification"
    assert failed.procedure_verified is False

    memory.attach_receipt(
        procedure.id,
        {"receipt_type": "build", "status": "pass", "target": "wheel"},
    )
    conservative = memory.suggest_procedure("deploy api")[0]
    assert conservative.verification_status == "failed_verification"
    assert conservative.procedure_status == "failed_verification"
    assert conservative.procedure_verified is False


def test_import_bootproof_like_attestation_and_redact_secrets(tmp_path):
    memory = Howdex(path=tmp_path / "bootproof.db", embedder="hashing")
    procedure = _seed(memory)
    attestation = tmp_path / ".bootproof" / "attestation.json"
    attestation.parent.mkdir()
    attestation.write_text(
        json.dumps(
            {
                "schema": "bootproof/attestation/v1",
                "finishedAt": "2026-06-22T12:30:00Z",
                "repo": {"path": "/tmp/service", "commit": "abc123"},
                "result": {
                    "booted": True,
                    "healthVerified": True,
                    "healthObservation": "HTTP 200",
                },
                "command": "bootproof verify --token secret-value",
                "metadata": {"runner": "local", "api_key": "do-not-store"},
                "signature": "signed-value",
            }
        ),
        encoding="utf-8",
    )

    imported = memory.import_bootproof_attestation(
        procedure.id,
        attestation,
    )
    attached = memory.list_receipts(procedure.id)

    assert imported is not None
    assert imported.receipt_type == "bootproof"
    assert imported.status == "verified"
    assert imported.command == "bootproof verify --token [REDACTED]"
    assert imported.target == "/tmp/service"
    assert imported.digest is not None
    assert imported.digest.startswith("sha256:")
    assert imported.signature == "signed-value"
    assert imported.source == str(attestation)
    assert imported.metadata["schema"] == "bootproof/attestation/v1"
    assert attached[0].metadata["api_key"] == "[REDACTED]"
    assert attached[0].raw_payload is not None
    assert attached[0].raw_payload["metadata"]["api_key"] == "[REDACTED]"


def test_missing_bootproof_attestation_is_optional(tmp_path):
    memory = Howdex(path=tmp_path / "missing.db", embedder="hashing")
    procedure = _seed(memory)
    missing = tmp_path / ".bootproof" / "attestation.json"

    assert parse_bootproof_attestation(missing) is None
    assert memory.import_bootproof_attestation(procedure.id, missing) is None
    assert memory.list_receipts(procedure.id) == []
    assert memory.procedure_verification_status(procedure.id) == "unverified"


def test_failed_bootproof_attestation_maps_to_failed_verification(tmp_path):
    attestation = tmp_path / "attestation.json"
    attestation.write_text(
        json.dumps(
            {
                "schema": "bootproof/attestation/v1",
                "result": {
                    "booted": False,
                    "healthVerified": False,
                    "failureClass": "health_timeout",
                },
            }
        ),
        encoding="utf-8",
    )

    receipt = parse_bootproof_attestation(attestation)

    assert receipt is not None
    assert receipt.status == "failed"


def test_malformed_receipts_are_rejected_without_attachment(tmp_path):
    memory = Howdex(path=tmp_path / "malformed.db", embedder="hashing")
    procedure = _seed(memory)
    malformed = tmp_path / "attestation.json"
    malformed.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed BootProof attestation"):
        memory.import_bootproof_attestation(procedure.id, malformed)
    with pytest.raises(ValueError, match="unsupported verification"):
        memory.attach_receipt(
            procedure.id,
            {"receipt_type": "custom", "status": "maybe"},
        )

    assert memory.list_receipts(procedure.id) == []


def test_old_database_migrates_receipt_table_idempotently(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE procedures (
            id TEXT PRIMARY KEY,
            task_signature TEXT NOT NULL UNIQUE,
            steps TEXT NOT NULL DEFAULT '[]',
            preconditions TEXT NOT NULL DEFAULT '[]',
            expected_outcome TEXT NOT NULL DEFAULT '',
            success_rate REAL NOT NULL DEFAULT 0,
            sample_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            last_used_at REAL,
            use_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO procedures(
            id, task_signature, created_at
        ) VALUES ('legacy', 'legacy deploy', 1.0);
        """
    )
    connection.close()

    first = Howdex(path=path, embedder="hashing")
    first.attach_receipt(
        "legacy",
        {"receipt_type": "custom", "status": "pass"},
    )
    first.close()

    reopened = Howdex(path=path, embedder="hashing")
    assert len(reopened.list_receipts("legacy")) == 1
    assert reopened.procedure_verification_status("legacy") == "verified"
    reopened.close()
