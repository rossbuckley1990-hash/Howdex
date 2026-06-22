"""Structured episodic evidence and deterministic segmentation tests."""

import json

from howdex import Howdex
from howdex.core.segmentation import segment_episode
from howdex.core.types import Episode


def _episode_rows(memory: Howdex):
    rows = memory.store.query_episodes(limit=100)
    parent = next(row for row in rows if not row["is_segment"])
    children = sorted(
        (row for row in rows if row["is_segment"]),
        key=lambda row: row["session_id"],
    )
    return parent, children


def _steps(row):
    return json.loads(row["steps"])


def test_long_session_splits_by_max_step_count_without_data_loss(tmp_path):
    memory = Howdex(path=tmp_path / "max-steps.db", embedder="hashing")
    session = memory.start_session(
        "long maintenance task",
        source="test-agent",
        provenance={"run_id": "run-1"},
    )
    for index in range(5):
        memory.log_step(f"step {index}", f"observation {index}")

    memory.end_session("success", max_segment_steps=2)
    parent, children = _episode_rows(memory)

    assert parent["session_id"] == session.session_id
    assert parent["step_count"] == 5
    assert parent["source"] == "test-agent"
    assert parent["provenance"]["run_id"] == "run-1"
    assert [child["step_count"] for child in children] == [2, 2, 1]
    assert all(
        child["parent_session_id"] == session.session_id
        for child in children
    )
    assert [
        step["action"]
        for child in children
        for step in _steps(child)
    ] == [f"step {index}" for index in range(5)]
    assert [step["action"] for step in _steps(parent)] == [
        f"step {index}" for index in range(5)
    ]


def test_session_splits_on_conservative_major_target_change(tmp_path):
    memory = Howdex(path=tmp_path / "targets.db", embedder="hashing")
    memory.start_session("prepare and publish release")
    memory.log_tool_call(
        "filesystem.read_file",
        {"path": "pyproject.toml"},
        "read",
    )
    memory.log_tool_call(
        "filesystem.write_file",
        {"path": "pyproject.toml", "content": "version=1"},
        "updated",
    )
    memory.log_tool_call(
        "github.create_pr",
        {"repo": "acme/service", "title": "Release"},
        "created",
    )
    memory.log_tool_call(
        "github.update_pr",
        {"repo": "acme/service", "pr": 42},
        "labelled",
    )

    memory.end_session("success", max_segment_steps=100)
    _, children = _episode_rows(memory)

    assert len(children) == 2
    assert [step["canonical_action"] for step in _steps(children[0])] == [
        "filesystem.read_file",
        "filesystem.write_file",
    ]
    assert [step["canonical_action"] for step in _steps(children[1])] == [
        "github.create_pr",
        "github.update_pr",
    ]
    assert (
        children[1]["provenance"]["segmentation_rule"]
        == "major_target_change"
    )


def test_explicit_task_boundary_sets_child_task_signature(tmp_path):
    memory = Howdex(path=tmp_path / "boundary.db", embedder="hashing")
    memory.start_session("repair package")
    memory.log_step("read package.json", "broken")
    memory.log_step("patch package.json test script", "fixed")
    memory.log_step(
        "run pytest",
        "passed",
        task_boundary="verify repaired package",
    )

    memory.end_session("success", max_segment_steps=100)
    _, children = _episode_rows(memory)

    assert [child["task_signature"] for child in children] == [
        "repair package",
        "verify repaired package",
    ]
    assert (
        children[1]["provenance"]["segmentation_rule"]
        == "explicit_task_boundary"
    )


def test_idle_gap_creates_a_deterministic_boundary(tmp_path):
    memory = Howdex(path=tmp_path / "idle.db", embedder="hashing")
    memory.start_session("investigate incident")
    memory.log_step("inspect logs", "first issue", ts=100.0)
    memory.log_step("inspect error", "cause found", ts=110.0)
    memory.log_step("run pytest", "passed", ts=2_000.0)

    memory.end_session(
        "success",
        max_segment_steps=100,
        idle_gap_s=900,
    )
    _, children = _episode_rows(memory)

    assert len(children) == 2
    assert children[1]["provenance"]["segmentation_rule"] == "idle_gap"
    assert children[1]["start_time"] == 2_000.0


def test_episode_and_steps_expose_structured_evidence_fields(tmp_path):
    memory = Howdex(path=tmp_path / "evidence.db", embedder="hashing")
    session = memory.start_session(
        "read configuration",
        source="mcp-agent",
        provenance={"framework": "mcp", "trace_id": "trace-7"},
    )
    memory.log_tool_call(
        "filesystem.read_file",
        {"path": "settings.json"},
        observation="loaded",
        metadata={"source": "mcp"},
        outcome="success",
        error=None,
        duration_s=0.25,
    )

    episode = memory.end_session("success")
    parent, children = _episode_rows(memory)
    step = _steps(parent)[0]

    assert children == []
    assert episode.task_signature == "read configuration"
    assert episode.start_time == parent["start_time"]
    assert episode.end_time == parent["end_time"]
    assert parent["outcome"] == "success"
    assert parent["error_summary"] is None
    assert parent["step_count"] == 1
    assert parent["source"] == "mcp-agent"
    assert parent["provenance"] == {
        "framework": "mcp",
        "trace_id": "trace-7",
    }
    assert step["tool_name"] == "filesystem.read_file"
    assert step["canonical_action"] == "filesystem.read_file"
    assert step["observation"] == "loaded"
    assert step["outcome"] == "success"
    assert step["error"] is None
    assert step["duration_s"] == 0.25
    assert step["end_time"] == step["start_time"] + 0.25
    assert parent["session_id"] == session.session_id


def test_failed_episode_exposes_error_summary(tmp_path):
    memory = Howdex(path=tmp_path / "failure.db", embedder="hashing")
    memory.start_session("deploy service", provenance={"run_id": "failed-1"})
    memory.log_step(
        "deploy service",
        "permission denied",
        outcome="failure",
        error="permission denied",
    )

    memory.end_session("failure", error="permission denied")
    parent, _ = _episode_rows(memory)

    assert parent["outcome"] == "failure"
    assert parent["error"] == "permission denied"
    assert parent["error_summary"] == "permission denied"


def test_consolidation_learns_from_children_not_raw_parent(tmp_path):
    memory = Howdex(path=tmp_path / "learn-segments.db", embedder="hashing")
    for _ in range(2):
        memory.start_session("repair package tests")
        memory.log_step("read package.json", "test script missing")
        memory.log_step("patch package.json test script", "fixed")
        memory.log_step(
            "run pytest",
            "passed",
            task_boundary="verify package tests",
        )
        memory.end_session("success", max_segment_steps=100)

    procedures = memory.learn(min_samples=2)
    repair = next(
        procedure
        for procedure in procedures
        if procedure.task_signature == "repair package tests"
    )

    assert [step["action"] for step in repair.steps] == [
        "inspect_package_manifest",
        "repair_test_command",
    ]
    assert repair.support_count == 2
    assert all(
        ":segment:" in episode_id
        for episode_id in repair.source_episode_ids
    )


def test_segmentation_is_deterministic_for_the_same_raw_episode():
    episode = Episode(
        session_id="session-7",
        agent_id="agent-1",
        task="multi-step task",
        started_at=100.0,
        finished_at=200.0,
        outcome="success",
        steps=[
            {
                "action": f"step {index}",
                "observation": "ok",
                "ts": float(100 + index),
                "start_time": float(100 + index),
                "end_time": float(101 + index),
            }
            for index in range(5)
        ],
    )

    first = segment_episode(episode, max_steps=2)
    second = segment_episode(episode, max_steps=2)

    assert [child.to_record() for child in first] == [
        child.to_record() for child in second
    ]
