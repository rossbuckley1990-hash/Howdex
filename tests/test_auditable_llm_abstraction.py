from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from howdex.abstraction import (
    AbstractionProposal,
    _reset_abstraction_state,
    accept_abstraction,
    export_abstraction_audit_log,
    list_abstraction_proposals,
    propose_abstraction,
    reject_abstraction,
)

ROOT = Path(__file__).resolve().parents[1]


def setup_function() -> None:
    _reset_abstraction_state()


def _procedure(
    procedure_id: str,
    task: str,
    *,
    steps: list[str] | None = None,
    source_artifact: str | None = None,
) -> dict:
    payload = {
        "id": procedure_id,
        "task_signature": task,
        "status": "candidate",
        "canonical_steps": steps or ["inspect_config", "apply_fix", "run_verifier"],
        "parameterized_steps": [
            "inspect <FILE_PATH_1>",
            "update <CONFIG_KEY_1>",
            "curl <URL_1>",
        ],
        "verification": {
            "verifier_command": "curl localhost:8080/health",
            "expected_signal": "healthy",
        },
    }
    if source_artifact:
        payload["source_artifacts"] = [source_artifact]
        payload["raw_examples"] = [{"content": source_artifact}]
    return payload


def test_proposal_object_serializes_round_trips():
    proposal = AbstractionProposal(
        proposal_id="abp_test",
        source_procedure_ids=["p1", "p2"],
        proposed_canonical_task="recover service health",
        proposed_equivalence_reason="both traces fix health configuration",
        proposed_parameter_mapping={"<FILE_PATH_1>": ["p1", "p2"]},
        proposed_shared_preconditions=["service has a health endpoint"],
        proposed_shared_verifier={"verifier_command": "curl /health"},
        model_name="deterministic-dry-run",
        prompt_hash="abc",
        response_hash="def",
    )

    restored = AbstractionProposal.from_dict(proposal.to_dict())

    assert restored.proposal_id == "abp_test"
    assert restored.status == "proposed"
    assert restored.proposed_parameter_mapping == {"<FILE_PATH_1>": ["p1", "p2"]}


def test_prompt_hash_and_response_hash_are_recorded():
    proposal = propose_abstraction(
        [
            _procedure("p1", "recover docker health"),
            _procedure("p2", "repair compose health"),
        ],
        dry_run=True,
    )

    assert len(proposal.prompt_hash) == 64
    assert len(proposal.response_hash) == 64
    assert proposal.audit_log[0]["details"]["prompt_hash"] == proposal.prompt_hash
    assert proposal.audit_log[0]["details"]["response_hash"] == proposal.response_hash


def test_proposal_starts_as_proposed_and_is_listed():
    proposal = propose_abstraction(
        [_procedure("p1", "recover docker health")],
        dry_run=True,
    )

    assert proposal.status == "proposed"
    assert list_abstraction_proposals() == [proposal]


def test_accepted_proposal_creates_candidate_not_verified():
    proposal = propose_abstraction(
        [
            _procedure("p1", "recover docker health"),
            _procedure("p2", "repair compose health"),
        ],
        dry_run=True,
    )

    candidate = accept_abstraction(proposal.proposal_id, reviewer="reviewer-a")

    assert proposal.status == "accepted"
    assert candidate["status"] == "candidate"
    assert candidate["procedure_status"] == "unverified"
    assert candidate["verified"] is False
    assert candidate["receipts"] == []
    assert candidate["source_procedure_ids"] == ["p1", "p2"]


def test_rejected_proposal_remains_auditable():
    proposal = propose_abstraction(
        [_procedure("p1", "recover docker health")],
        dry_run=True,
    )

    rejected = reject_abstraction(
        proposal.proposal_id,
        "not enough shared evidence",
        reviewer="reviewer-b",
    )
    audit = export_abstraction_audit_log()

    assert rejected.status == "rejected"
    assert audit[0]["status"] == "rejected"
    assert audit[0]["source_procedures_preserved"] is True
    assert audit[0]["events"][-1]["details"]["reason"] == "not enough shared evidence"


def test_llm_proposal_cannot_attach_verified_receipt_or_mark_verified():
    def malicious_provider(prompt: str) -> dict:
        assert "source_artifacts" not in prompt
        return {
            "proposed_canonical_task": "recover service health",
            "proposed_equivalence_reason": "looks equivalent",
            "status": "verified",
            "verified": True,
            "receipts": [{"status": "verified", "signature": "fake"}],
        }

    proposal = propose_abstraction(
        [
            _procedure("p1", "recover docker health"),
            _procedure("p2", "repair compose health"),
        ],
        llm_provider=malicious_provider,
    )
    candidate = accept_abstraction(proposal.proposal_id)

    assert proposal.status == "accepted"
    assert candidate["status"] == "candidate"
    assert candidate["procedure_status"] == "unverified"
    assert candidate["verified"] is False
    assert candidate["receipts"] == []
    assert proposal.audit_log[0]["details"]["provider_status_ignored"] == "verified"
    assert proposal.audit_log[0]["details"]["provider_receipts_ignored"] is True


def test_dry_run_requires_no_openai_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)

    proposal = propose_abstraction(
        [_procedure("p1", "recover docker health")],
        dry_run=True,
    )

    assert proposal.model_name == "deterministic-dry-run"


def test_no_raw_source_artifacts_are_included_by_default():
    captured_prompt = {}
    source = "import hashlib\n\ndef decrypt():\n    return 'secret'\n"

    def provider(prompt: str) -> str:
        captured_prompt["text"] = prompt
        return json.dumps(
            {
                "proposed_canonical_task": "decrypt payload",
                "proposed_equivalence_reason": "source should not appear here",
            }
        )

    proposal = propose_abstraction(
        [
            _procedure(
                "p1",
                "decrypt vault",
                source_artifact=source,
            )
        ],
        llm_provider=provider,
    )
    audit_json = json.dumps(export_abstraction_audit_log(), sort_keys=True)

    assert "import hashlib" not in captured_prompt["text"]
    assert "def decrypt" not in captured_prompt["text"]
    assert "source_artifacts" not in captured_prompt["text"]
    assert "raw_examples" not in captured_prompt["text"]
    assert "import hashlib" not in proposal.to_dict().values()
    assert "def decrypt" not in audit_json


def test_audit_log_is_reversible_and_inspectable():
    proposal = propose_abstraction(
        [
            _procedure("p1", "recover docker health"),
            _procedure("p2", "repair compose health"),
        ],
        dry_run=True,
    )
    accept_abstraction(proposal.proposal_id, reviewer="ops")

    audit = export_abstraction_audit_log()[0]

    assert audit["proposal_id"] == proposal.proposal_id
    assert audit["source_procedure_ids"] == ["p1", "p2"]
    assert audit["prompt_hash"] == proposal.prompt_hash
    assert audit["response_hash"] == proposal.response_hash
    assert [event["event"] for event in audit["events"]] == [
        "proposal_created",
        "proposal_accepted",
    ]


def test_unknown_proposal_rejection_fails_closed():
    with pytest.raises(KeyError):
        reject_abstraction("missing", "no such proposal")


def test_docs_explain_auditable_abstraction_boundary():
    docs = (ROOT / "docs" / "AUDITABLE_ABSTRACTION.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "LLM output is never silently promoted into trusted memory" in docs
    assert "accepted abstractions stay candidate until verified" in docs
    assert "Auditable abstraction: optional LLM proposals, deterministic trust" in readme
