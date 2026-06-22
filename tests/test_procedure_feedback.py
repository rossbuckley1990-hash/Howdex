"""Deterministic procedure-use feedback tests."""

import pytest

from howdex import Howdex
from howdex.core.errors import StoreError
from howdex.core.types import Procedure


def _seed(memory: Howdex, procedure_id: str = "deploy-procedure") -> Procedure:
    procedure = Procedure(
        id=procedure_id,
        task_signature="deploy api",
        steps=[{"action": "deploy_service"}],
        expected_outcome="success",
        success_rate=1.0,
        sample_count=3,
        support_count=3,
        success_count=3,
        failure_count=0,
        confidence=0.85,
        base_confidence=0.85,
        source_episode_ids=["learn-1", "learn-2", "learn-3"],
    )
    memory.store.put_procedure(dict(procedure.__dict__))
    return procedure


def test_successful_use_increments_verified_success(tmp_path):
    memory = Howdex(path=tmp_path / "success.db", embedder="hashing")
    procedure = _seed(memory)

    pending = memory.mark_procedure_used(procedure.id, "episode-4")
    updated = memory.record_procedure_outcome(
        procedure.id,
        "episode-4",
        "success",
    )

    assert pending.use_count == 1
    assert pending.unverified_use_count == 1
    assert updated.use_count == 1
    assert updated.unverified_use_count == 0
    assert updated.support_count == 4
    assert updated.success_count == 4
    assert updated.failure_count == 0
    assert updated.feedback_success_count == 1
    assert updated.feedback_failure_count == 0
    assert updated.success_rate == 1.0
    assert updated.confidence == 0.91
    assert updated.source_episode_ids == [
        "episode-4",
        "learn-1",
        "learn-2",
        "learn-3",
    ]


def test_failed_use_increments_failure_and_reduces_confidence(tmp_path):
    memory = Howdex(path=tmp_path / "failure.db", embedder="hashing")
    procedure = _seed(memory)

    updated = memory.record_procedure_outcome(
        procedure.id,
        "episode-4",
        "failure",
    )

    assert updated.use_count == 1
    assert updated.support_count == 4
    assert updated.success_count == 3
    assert updated.failure_count == 1
    assert updated.feedback_success_count == 0
    assert updated.feedback_failure_count == 1
    assert updated.success_rate == 0.75
    assert updated.confidence == 0.7975
    assert updated.confidence < procedure.confidence


def test_suggested_only_does_not_affect_success_or_usage(tmp_path):
    memory = Howdex(path=tmp_path / "suggested.db", embedder="hashing")
    procedure = _seed(memory)

    first = memory.mark_procedure_suggested(procedure.id, "session-4")
    second = memory.mark_procedure_suggested(procedure.id, "session-4")

    assert first.suggestion_count == 1
    assert second.suggestion_count == 1
    assert second.use_count == 0
    assert second.unverified_use_count == 0
    assert second.support_count == 3
    assert second.success_count == 3
    assert second.failure_count == 0
    assert second.success_rate == 1.0
    assert second.confidence == 0.85


def test_missing_feedback_defaults_derive_from_existing_evidence(tmp_path):
    memory = Howdex(path=tmp_path / "defaults.db", embedder="hashing")
    procedure = Procedure(
        id="legacy-shaped",
        task_signature="repair service",
        success_rate=0.75,
        sample_count=4,
        support_count=4,
        success_count=3,
        confidence=0.8,
    )
    memory.store.put_procedure(dict(procedure.__dict__))

    stored = memory.get_procedure("repair service", min_confidence=0.0)

    assert stored is not None
    assert stored.failure_count == 1
    assert stored.base_confidence == 0.8


def test_used_without_outcome_remains_unverified(tmp_path):
    memory = Howdex(path=tmp_path / "pending.db", embedder="hashing")
    procedure = _seed(memory)

    first = memory.mark_procedure_used(procedure.id, "session-4")
    second = memory.mark_procedure_used(procedure.id, "session-4")

    assert first.use_count == 1
    assert second.use_count == 1
    assert second.unverified_use_count == 1
    assert second.support_count == 3
    assert second.success_count == 3
    suggestion = memory.suggest_procedure("deploy api")[0]
    assert suggestion.proof_status == "pending_unverified_use"


def test_outcome_recording_is_idempotent_and_rejects_conflicts(tmp_path):
    memory = Howdex(path=tmp_path / "idempotent.db", embedder="hashing")
    procedure = _seed(memory)

    first = memory.record_procedure_outcome(
        procedure.id,
        "episode-4",
        "success",
    )
    second = memory.record_procedure_outcome(
        procedure.id,
        "episode-4",
        "success",
    )

    assert second == first
    with pytest.raises(StoreError):
        memory.record_procedure_outcome(
            procedure.id,
            "episode-4",
            "failure",
        )


def test_confidence_update_is_deterministic(tmp_path):
    first_memory = Howdex(path=tmp_path / "first.db", embedder="hashing")
    second_memory = Howdex(path=tmp_path / "second.db", embedder="hashing")
    first = _seed(first_memory, "first")
    second = _seed(second_memory, "second")

    first_result = first_memory.record_procedure_outcome(
        first.id,
        "episode-4",
        "failure",
    )
    second_result = second_memory.record_procedure_outcome(
        second.id,
        "episode-4",
        "failure",
    )

    assert first_result.success_rate == second_result.success_rate
    assert first_result.confidence == second_result.confidence
    assert first_result.feedback_failure_count == 1
    assert second_result.feedback_failure_count == 1


def test_session_close_automatically_records_pending_use(tmp_path):
    memory = Howdex(path=tmp_path / "session-loop.db", embedder="hashing")
    procedure = _seed(memory)
    session = memory.start_session("deploy api")
    memory.mark_procedure_used(procedure.id, session.session_id)
    memory.log_step("deploy service", "healthy")

    memory.end_session("success")
    updated = memory.get_procedure("deploy api", min_confidence=0.0)

    assert updated is not None
    assert updated.use_count == 1
    assert updated.unverified_use_count == 0
    assert updated.feedback_success_count == 1
    assert session.session_id in updated.source_episode_ids


def test_partial_session_leaves_use_unverified(tmp_path):
    memory = Howdex(path=tmp_path / "partial.db", embedder="hashing")
    procedure = _seed(memory)
    session = memory.start_session("deploy api")
    memory.mark_procedure_used(procedure.id, session.session_id)

    memory.end_session("partial")
    updated = memory.get_procedure("deploy api", min_confidence=0.0)

    assert updated is not None
    assert updated.use_count == 1
    assert updated.unverified_use_count == 1
    assert updated.feedback_success_count == 0
    assert updated.feedback_failure_count == 0


def test_relearning_preserves_observed_feedback(tmp_path):
    memory = Howdex(path=tmp_path / "relearn.db", embedder="hashing")
    for _ in range(2):
        memory.start_session("repair package tests")
        memory.log_step("read package.json", "broken test script")
        memory.log_step("patch package.json test script", "fixed")
        memory.log_step("run pytest", "passed")
        memory.end_session("success")
    learned = memory.learn(min_samples=2)[0]
    memory.record_procedure_outcome(
        learned.id,
        "feedback-failure",
        "failure",
    )

    relearned = memory.learn(min_samples=2)[0]

    assert relearned.feedback_failure_count == 1
    assert relearned.failure_count == 1
    assert relearned.support_count == 3
    assert relearned.success_count == 2
    assert relearned.success_rate == 0.6667
    assert "feedback-failure" in relearned.source_episode_ids
