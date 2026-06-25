"""Credibility tests for deterministic v0.3 procedural extraction."""

from howdex import Howdex
from howdex.core.types import Procedure


def _record(mem: Howdex, task: str, steps: list[tuple[str, str]], outcome="success"):
    mem.start_session(task)
    for action, observation in steps:
        mem.log_step(action, observation)
    return mem.end_session(outcome)


def test_equivalent_wording_consolidates_into_one_canonical_procedure(tmp_path):
    mem = Howdex(path=tmp_path / "equivalent.db", embedder="hashing")
    task = "repair project test command"

    first = _record(
        mem,
        task,
        [
            ("open package.json", "test script missing"),
            ("edit the package.json test script", "restored npm test"),
            ("npm test", "passed"),
        ],
    )
    second = _record(
        mem,
        task,
        [
            ("check package manifest package.json", "broken script found"),
            ("patch test script in package.json", "command repaired"),
            ("run the test suite with pytest", "passed"),
        ],
    )

    procedures = mem.learn(min_samples=2)

    assert len(procedures) == 1
    procedure = procedures[0]
    assert [step["action"] for step in procedure.steps] == [
        "inspect_package_manifest",
        "repair_test_command",
        "run_test_suite",
    ]
    assert procedure.support_count == 2
    assert procedure.success_count == 2
    assert procedure.confidence >= 0.8
    assert procedure.source_episode_ids == sorted(
        [first.session_id, second.session_id]
    )
    assert len(procedure.raw_supporting_examples) == 2
    assert {
        example["steps"][0]["action"]
        for example in procedure.raw_supporting_examples
    } == {"open package.json", "check package manifest package.json"}


def test_low_overlap_successful_episodes_do_not_consolidate(tmp_path):
    mem = Howdex(path=tmp_path / "low-overlap.db", embedder="hashing")
    task = "maintain project"

    _record(
        mem,
        task,
        [
            ("open package.json", "read"),
            ("patch package.json test script", "fixed"),
            ("npm test", "passed"),
        ],
    )
    _record(
        mem,
        task,
        [
            ("pip install dependencies", "installed"),
            ("inspect traceback", "root cause found"),
            ("deploy service", "healthy"),
        ],
    )

    assert mem.learn(min_samples=2) == []


def test_internal_memory_actions_are_filtered_from_evidence(tmp_path):
    mem = Howdex(path=tmp_path / "internal.db", embedder="hashing")
    task = "repair package tests"
    for _ in range(2):
        _record(
            mem,
            task,
            [
                ("inspect_howdex", "prior context loaded"),
                ("read package.json", "test script missing"),
                ("fix package.json test script", "restored"),
                ("run tests", "passed"),
            ],
        )

    procedure = mem.learn(min_samples=2)[0]

    assert "internal_memory_action" not in [
        step["action"] for step in procedure.steps
    ]
    assert all(
        "inspect_howdex"
        not in example["canonical_sequence"]
        for example in procedure.raw_supporting_examples
    )


def test_procedural_retrieval_is_confidence_filtered_and_capped(tmp_path):
    mem = Howdex(path=tmp_path / "retrieval.db", embedder="hashing")
    for index, confidence in enumerate((0.95, 0.85, 0.75, 0.2), start=1):
        procedure = Procedure(
            task_signature=f"deploy service {index}",
            steps=[{"action": "deploy_service"}],
            success_rate=confidence,
            sample_count=3,
            support_count=3,
            success_count=3,
            confidence=confidence,
        )
        mem.store.put_procedure(dict(procedure.__dict__))

    results = mem.search(
        "deploy service",
        layer="procedural",
        top_k=10,
        min_score=0.0,
    )

    assert len(results) == 3
    assert all(
        result.memory.metadata["confidence"] >= 0.6
        for result in results
    )
    assert [
        result.memory.metadata["confidence"] for result in results
    ] == sorted(
        [result.memory.metadata["confidence"] for result in results],
        reverse=True,
    )
