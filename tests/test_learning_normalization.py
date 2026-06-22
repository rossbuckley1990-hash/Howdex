"""Regression tests for canonical structured-step learning identity."""

from __future__ import annotations

from typing import Any

from howdex import Howdex
from howdex.core.learning import (
    canonical_json,
    normalize_step_for_learning,
)


def _store_episode(
    memory: Howdex,
    *,
    episode_id: str,
    task: str,
    steps: list[Any],
) -> None:
    memory.store.put_episode(
        {
            "id": episode_id,
            "session_id": episode_id,
            "agent_id": "normalization-test",
            "task": task,
            "steps": steps,
            "outcome": "success",
            "error": None,
            "duration_s": 1.0,
            "started_at": 1.0,
            "finished_at": 2.0,
        }
    )


def test_different_top_level_json_key_order_learns_one_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "key-order.db", embedder="hashing")
    _store_episode(
        memory,
        episode_id="ordered",
        task="install dependency",
        steps=[
            {
                "tool": "bash",
                "cmd": "npm install cors",
                "cwd": "./",
            }
        ],
    )
    _store_episode(
        memory,
        episode_id="reordered",
        task="install dependency",
        steps=[
            {
                "cwd": "./",
                "cmd": "npm install cors",
                "tool": "bash",
            }
        ],
    )

    procedures = memory.learn(min_samples=2)

    assert len(procedures) == 1
    assert procedures[0].steps[0]["canonical_name"] == (
        "install_dependencies"
    )
    assert procedures[0].steps[0]["parameterized_action"] == (
        "npm install <PKG_1>"
    )
    assert procedures[0].support_count == 2


def test_nested_argument_key_order_normalizes_identically():
    first = normalize_step_for_learning(
        {
            "tool_name": "filesystem.write_file",
            "tool_args": {
                "path": "src/app.js",
                "options": {
                    "mode": "atomic",
                    "encoding": "utf-8",
                },
            },
        }
    )
    second = normalize_step_for_learning(
        {
            "tool_args": {
                "options": {
                    "encoding": "utf-8",
                    "mode": "atomic",
                },
                "path": "src/app.js",
            },
            "tool_name": "filesystem.write_file",
        }
    )

    assert first.identity == second.identity
    assert first.canonical_payload == second.canonical_payload
    assert canonical_json(first.canonical_payload) == first.identity


def test_raw_json_string_and_dict_normalize_identically():
    mapping = {
        "tool": "bash",
        "cmd": "npm install cors",
        "cwd": "./",
    }
    raw_json = """
    {
      "cwd": "./",
      "cmd": "npm install cors",
      "tool": "bash"
    }
    """

    from_mapping = normalize_step_for_learning(mapping)
    from_json = normalize_step_for_learning(raw_json)

    assert from_mapping.identity == from_json.identity
    assert from_mapping.canonical_payload == from_json.canonical_payload


def test_json_and_command_whitespace_do_not_change_identity():
    compact = normalize_step_for_learning(
        '{"tool":"bash","cmd":"npm install cors","cwd":"./"}'
    )
    spaced = normalize_step_for_learning(
        '{ "cwd" : "./", "cmd" : "npm   install   cors", '
        '"tool" : "bash" }'
    )

    assert compact.identity == spaced.identity
    assert compact.parameterized.parameterized_action == (
        "npm install <PKG_1>"
    )
    assert spaced.parameterized.parameterized_action == (
        "npm install <PKG_1>"
    )


def test_invalid_json_falls_back_without_crashing(tmp_path):
    malformed = '{"tool": "bash", "cmd": '
    normalized = normalize_step_for_learning(malformed)

    assert normalized.canonical.canonical_name == "unknown_action"
    assert normalized.raw_step["action"] == malformed

    memory = Howdex(path=tmp_path / "invalid.db", embedder="hashing")
    for episode_id in ("invalid-1", "invalid-2"):
        _store_episode(
            memory,
            episode_id=episode_id,
            task="malformed trace",
            steps=[malformed],
        )

    assert memory.learn(min_samples=2) == []


def test_changed_package_literals_use_parameterized_identity(tmp_path):
    memory = Howdex(path=tmp_path / "packages.db", embedder="hashing")
    for episode_id, package in (
        ("package-1", "cors"),
        ("package-2", "express"),
    ):
        _store_episode(
            memory,
            episode_id=episode_id,
            task="install dependency",
            steps=[
                {
                    "tool": "bash",
                    "cmd": f"npm install {package}",
                    "cwd": "./",
                }
            ],
        )

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.steps[0]["canonical_name"] == "install_dependencies"
    assert procedure.steps[0]["parameterized_action"] == (
        "npm install <PKG_1>"
    )
    assert {
        binding["bindings"]["<PKG_1>"]
        for binding in procedure.parameter_bindings
    } == {"cors", "express"}


def test_logged_bash_tool_calls_use_command_template_for_learning(tmp_path):
    memory = Howdex(path=tmp_path / "logged-bash.db", embedder="hashing")
    for package in ("cors", "express"):
        with memory.session("install dependency") as session:
            session.tool_call(
                "bash",
                {"cmd": f"npm install {package}", "cwd": "./"},
                "installed",
            )

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.steps[0]["canonical_name"] == "install_dependencies"
    assert procedure.steps[0]["parameterized_action"] == (
        "npm install <PKG_1>"
    )


def test_changed_path_literals_use_parameterized_identity(tmp_path):
    memory = Howdex(path=tmp_path / "paths.db", embedder="hashing")
    for episode_id, path in (
        ("path-1", "tests/test_auth.py"),
        ("path-2", "tests/test_billing.py"),
    ):
        _store_episode(
            memory,
            episode_id=episode_id,
            task="run focused tests",
            steps=[
                {
                    "tool": "bash",
                    "cmd": f"pytest {path}",
                    "cwd": "./",
                }
            ],
        )

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.steps[0]["canonical_name"] == "run_test_suite"
    assert (
        procedure.steps[0]["parameterized_action"]
        == "pytest <FILE_PATH_1>"
    )
    assert {
        binding["bindings"]["<FILE_PATH_1>"]
        for binding in procedure.parameter_bindings
    } == {"tests/test_auth.py", "tests/test_billing.py"}


def test_equivalent_workflows_learn_reusable_parameterized_template(
    tmp_path,
):
    memory = Howdex(
        path=tmp_path / "workflow-template.db",
        embedder="hashing",
    )
    for episode_id, path, package in (
        ("workflow-1", "app.js", "cors"),
        ("workflow-2", "server.js", "express"),
    ):
        _store_episode(
            memory,
            episode_id=episode_id,
            task="repair application dependency",
            steps=[
                f"edit {path}",
                f"npm install {package}",
                "npm test",
            ],
        )

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.support_count == 2
    assert procedure.source_episode_ids == [
        "workflow-1",
        "workflow-2",
    ]
    assert [
        step["parameterized_action"]
        for step in procedure.steps
    ] == [
        "edit <FILE_PATH_1>",
        "npm install <PKG_1>",
        "run <TEST_COMMAND_1>",
    ]
    assert [
        step["canonical_name"]
        for step in procedure.canonical_steps
    ] == [
        "repair_file",
        "install_dependencies",
        "run_test_suite",
    ]
    assert [
        step["action"]
        for step in procedure.parameterized_steps
    ] == [
        "edit <FILE_PATH_1>",
        "npm install <PKG_1>",
        "run <TEST_COMMAND_1>",
    ]
    assert {
        binding["bindings"]["<FILE_PATH_1>"]
        for binding in procedure.example_bindings
    } == {"app.js", "server.js"}
    assert {
        binding["bindings"]["<PKG_1>"]
        for binding in procedure.example_bindings
    } == {"cors", "express"}


def test_key_order_and_changed_literals_share_learning_identity(tmp_path):
    memory = Howdex(
        path=tmp_path / "key-order-and-literals.db",
        embedder="hashing",
    )
    _store_episode(
        memory,
        episode_id="first",
        task="repair javascript service",
        steps=[
            {"tool": "bash", "cmd": "edit app.js", "cwd": "./"},
            {"tool": "bash", "cmd": "npm install cors", "cwd": "./"},
            {"tool": "bash", "cmd": "npm test", "cwd": "./"},
        ],
    )
    _store_episode(
        memory,
        episode_id="second",
        task="repair javascript service",
        steps=[
            {"cwd": "./", "cmd": "edit server.js", "tool": "bash"},
            {"cmd": "npm install express", "tool": "bash", "cwd": "./"},
            {"cwd": "./", "tool": "bash", "cmd": "npm test"},
        ],
    )

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.support_count == 2
    assert [
        step["parameterized_action"]
        for step in procedure.steps
    ] == [
        "edit <FILE_PATH_1>",
        "npm install <PKG_1>",
        "run <TEST_COMMAND_1>",
    ]


def test_repeated_literal_binding_is_consistent_in_learned_template(
    tmp_path,
):
    memory = Howdex(
        path=tmp_path / "repeated-literal.db",
        embedder="hashing",
    )
    for episode_id, path in (
        ("repeat-1", "app.js"),
        ("repeat-2", "server.js"),
    ):
        _store_episode(
            memory,
            episode_id=episode_id,
            task="edit and execute application",
            steps=[
                f"edit {path}",
                f"read {path}",
            ],
        )

    procedure = memory.learn(min_samples=2)[0]

    assert [
        step["parameterized_action"]
        for step in procedure.steps
    ] == ["edit <FILE_PATH_1>", "read <FILE_PATH_1>"]
    assert all(
        list(binding["bindings"]) == ["<FILE_PATH_1>"]
        for binding in procedure.example_bindings
    )


def test_unrelated_literal_bearing_workflows_do_not_merge(tmp_path):
    memory = Howdex(
        path=tmp_path / "unrelated-templates.db",
        embedder="hashing",
    )
    _store_episode(
        memory,
        episode_id="repair",
        task="maintain application",
        steps=[
            "edit app.js",
            "npm install cors",
            "npm test",
        ],
    )
    _store_episode(
        memory,
        episode_id="deploy",
        task="maintain application",
        steps=[
            "read deploy.yaml",
            "curl https://example.test/health",
            "delete old release",
        ],
    )

    assert memory.learn(min_samples=2) == []


def test_legacy_prose_learning_remains_supported(tmp_path):
    memory = Howdex(path=tmp_path / "legacy.db", embedder="hashing")
    for _ in range(2):
        memory.start_session("repair test command")
        memory.log_step("read package.json", "broken script")
        memory.log_step("patch package.json test script", "fixed")
        memory.log_step("run tests", "passed")
        memory.end_session("success")

    procedure = memory.learn(min_samples=2)[0]

    assert [step["canonical_name"] for step in procedure.steps] == [
        "inspect_package_manifest",
        "repair_test_command",
        "run_test_suite",
    ]
