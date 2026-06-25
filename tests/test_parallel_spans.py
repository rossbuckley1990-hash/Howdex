"""Parallel tool-call spans and DAG-shaped procedure tests."""

from __future__ import annotations

import json

from howdex import Howdex
from howdex.core.parallel import (
    Parallel_Span_Resolver,
    render_dag_steps,
)


def test_overlapping_steps_are_resolved_as_one_parallel_group():
    resolved = Parallel_Span_Resolver().resolve(
        [
            {
                "step_id": "inspect",
                "action": "inspect package.json",
                "started_at": 0.0,
                "ended_at": 1.0,
            },
            {
                "step_id": "read-source",
                "action": "read src/app.py",
                "started_at": 2.0,
                "ended_at": 5.0,
            },
            {
                "step_id": "read-log",
                "action": "inspect error log",
                "started_at": 3.0,
                "ended_at": 4.0,
            },
            {
                "step_id": "test",
                "action": "run pytest",
                "started_at": 6.0,
                "ended_at": 8.0,
            },
        ],
        episode_id="episode-1",
    )

    parallel = [
        step for step in resolved if step["parallel_group_id"]
    ]
    assert len(parallel) == 2
    assert {
        step["parallel_group_id"] for step in parallel
    } == {"parallel-0002"}
    assert {
        step["ordering_index"] for step in parallel
    } == {1}
    assert all(
        step["parent_step_ids"] == ["inspect"] for step in parallel
    )
    final = next(step for step in resolved if step["step_id"] == "test")
    assert final["parent_step_ids"] == ["read-log", "read-source"]


def test_non_overlapping_steps_remain_sequential():
    resolved = Parallel_Span_Resolver().resolve(
        [
            {
                "step_id": "one",
                "action": "one",
                "started_at": 0.0,
                "ended_at": 1.0,
            },
            {
                "step_id": "two",
                "action": "two",
                "started_at": 1.0,
                "ended_at": 2.0,
            },
            {
                "step_id": "three",
                "action": "three",
                "started_at": 2.0,
                "ended_at": 3.0,
            },
        ]
    )

    assert [step["parallel_group_id"] for step in resolved] == [
        None,
        None,
        None,
    ]
    assert [step["parent_step_ids"] for step in resolved] == [
        [],
        ["one"],
        ["two"],
    ]
    assert [step["ordering_index"] for step in resolved] == [0, 1, 2]


def test_explicit_parent_relationship_is_preserved():
    resolved = Parallel_Span_Resolver().resolve(
        [
            {
                "step_id": "parent",
                "action": "start service",
                "started_at": 0.0,
                "ended_at": 5.0,
                "span_id": "span-parent",
            },
            {
                "step_id": "child",
                "parent_step_ids": ["parent"],
                "action": "check health",
                "started_at": 1.0,
                "ended_at": 2.0,
                "span_id": "span-child",
            },
        ]
    )

    child = next(step for step in resolved if step["step_id"] == "child")
    assert child["parent_step_ids"] == ["parent"]
    assert child["span_id"] == "span-child"
    assert all(step["parallel_group_id"] is None for step in resolved)


def _record_parallel_episode(
    memory: Howdex,
    suffix: str,
    *,
    reverse_parallel_logging: bool = False,
) -> None:
    memory.start_session("repair and verify package")
    memory.log_tool_call(
        "filesystem.read_file",
        {"path": "package.json"},
        "manifest read",
        step_id=f"{suffix}-manifest",
        started_at=0.0,
        ended_at=1.0,
    )
    parallel_calls = [
        lambda: memory.log_tool_call(
            "filesystem.read_file",
            {"path": "src/app.py"},
            "source read",
            step_id=f"{suffix}-source",
            span_id=f"{suffix}-source-span",
            started_at=2.0,
            ended_at=5.0,
        ),
        lambda: memory.log_step(
            "inspect error log",
            "cause found",
            step_id=f"{suffix}-log",
            span_id=f"{suffix}-log-span",
            started_at=2.5,
            ended_at=4.0,
        ),
    ]
    if reverse_parallel_logging:
        parallel_calls.reverse()
    for call in parallel_calls:
        call()
    memory.log_step(
        "run pytest",
        "passed",
        step_id=f"{suffix}-test",
        started_at=6.0,
        ended_at=8.0,
    )
    memory.end_session("success")


def test_learned_procedure_preserves_parallel_dag_and_portable_json(tmp_path):
    memory = Howdex(path=tmp_path / "parallel.db", embedder="hashing")
    _record_parallel_episode(memory, "first")
    _record_parallel_episode(
        memory,
        "second",
        reverse_parallel_logging=True,
    )

    procedure = memory.learn(min_samples=2)[0]
    groups = {}
    for step in procedure.steps:
        groups.setdefault(step["ordering_index"], []).append(step)

    assert [len(groups[index]) for index in sorted(groups)] == [1, 2, 1]
    parallel = groups[1]
    assert {
        step["canonical_name"] for step in parallel
    } == {"filesystem.read_file", "inspect_error"}
    assert {
        step["parallel_group_id"] for step in parallel
    } == {"parallel-0002"}
    assert all(
        step["parent_step_ids"] == ["procedure-step-0001"]
        for step in parallel
    )
    final = groups[2][0]
    assert final["parent_step_ids"] == [
        "procedure-step-0002",
        "procedure-step-0003",
    ]

    output = tmp_path / "portable"
    memory.export_procedures(output)
    document = json.loads(next(output.glob("*.json")).read_text())
    exported_parallel = [
        step
        for step in document["procedure"]["steps"]
        if step["parallel_group_id"] == "parallel-0002"
    ]
    assert len(exported_parallel) == 2
    assert all("step_id" in step for step in exported_parallel)
    assert all("parent_step_ids" in step for step in exported_parallel)


def test_parallel_guidance_rendering_is_deterministic(tmp_path):
    memory = Howdex(path=tmp_path / "render.db", embedder="hashing")
    _record_parallel_episode(memory, "first")
    _record_parallel_episode(
        memory,
        "second",
        reverse_parallel_logging=True,
    )
    memory.learn(min_samples=2)
    suggestion = memory.suggest_procedure(
        "repair and verify package"
    )[0]

    first = memory.render_procedure_guidance(suggestion)
    second = memory.render_procedure_guidance(suggestion)

    assert first == second
    assert "Step 1:" in first
    assert "Step 2a (parallel): filesystem.read_file" in first
    assert "Step 2b (parallel): inspect error log" in first
    assert "Step 3: run <TEST_COMMAND_1>" in first


def test_logged_steps_store_all_dag_fields(tmp_path):
    memory = Howdex(path=tmp_path / "fields.db", embedder="hashing")
    memory.start_session("parallel fields")
    memory.log_step(
        "read package.json",
        "read",
        step_id="explicit-step",
        parent_step_ids=["root"],
        span_id="span-1",
        parallel_group_id="provided-group",
        started_at=10.0,
        ended_at=12.0,
        ordering_index=7,
    )
    memory.end_session("success")

    row = memory.store.query_episodes()[0]
    step = json.loads(row["steps"])[0]
    assert step["step_id"] == "explicit-step"
    assert step["parent_step_ids"] == ["root"]
    assert step["span_id"] == "span-1"
    assert step["parallel_group_id"] == "provided-group"
    assert step["started_at"] == 10.0
    assert step["ended_at"] == 12.0
    assert step["ordering_index"] == 0


def test_render_dag_steps_supports_legacy_linear_steps():
    assert render_dag_steps(
        [{"action": "first"}, {"action": "second"}]
    ) == [
        "Step 1: first",
        "Step 2: second",
    ]
