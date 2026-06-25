"""Regression coverage for deterministic variable masking before LCS."""

from __future__ import annotations

import json
from typing import Any

from howdex import Howdex
from howdex.core.actions import canonicalize_action
from howdex.core.parameterize import (
    REDACTED,
    parameterize_action,
    parameterize_step_for_learning,
)
from howdex.core.tool_calls import canonicalize_tool_call


def _store_episode(
    memory: Howdex,
    episode_id: str,
    steps: list[dict[str, Any]],
    *,
    task: str = "repair application",
) -> None:
    memory.store.put_episode(
        {
            "id": episode_id,
            "session_id": episode_id,
            "agent_id": "variable-masking-test",
            "task": task,
            "steps": steps,
            "outcome": "success",
            "started_at": 1.0,
            "finished_at": 2.0,
        }
    )


def test_parameterized_step_exposes_stable_learning_fields():
    step = parameterize_step_for_learning(
        canonicalize_tool_call(
            "fs.write",
            {"path": "app.js", "content": "const ready = true;"},
        )
    )

    assert step.parameterized_action == "fs.write"
    assert step.parameterized_args == {
        "content": "<CONTENT_1>",
        "path": "<FILE_PATH_1>",
    }
    assert step.parameter_bindings == {
        "<FILE_PATH_1>": "app.js",
    }
    assert step.placeholder_types == {
        "<CONTENT_1>": "CONTENT",
        "<FILE_PATH_1>": "FILE_PATH",
    }
    assert "app.js" not in step.learning_key
    assert "const ready" not in step.learning_key
    assert step.provenance["source"] == "parameterized_lcs"


def test_file_write_literals_merge_into_one_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "file-write.db", embedder="hashing")
    _store_episode(
        memory,
        "write-app",
        [
            {
                "tool": "fs.write",
                "args": {"path": "app.js", "content": "alpha"},
            }
        ],
    )
    _store_episode(
        memory,
        "write-server",
        [
            {
                "tool": "fs.write",
                "args": {"path": "server.js", "content": "beta"},
            }
        ],
    )

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.extraction_method == "parameterized_lcs"
    assert procedure.source_episode_ids == ["write-app", "write-server"]
    assert procedure.parameterized_steps[0]["action"] == "fs.write"
    assert procedure.parameterized_steps[0]["arguments"] == {
        "content": "<CONTENT_1>",
        "path": "<FILE_PATH_1>",
    }
    assert {
        example["bindings"]["<FILE_PATH_1>"]
        for example in procedure.example_bindings
    } == {"app.js", "server.js"}


def test_structured_package_literals_merge_into_one_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "packages.db", embedder="hashing")
    for episode_id, package in (("cors", "cors"), ("express", "express")):
        _store_episode(
            memory,
            episode_id,
            [{"tool": "bash", "args": {"cmd": f"npm install {package}"}}],
            task="install dependency",
        )

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.parameterized_steps[0]["action"] == (
        "npm install <PKG_1>"
    )
    assert {
        example["bindings"]["<PKG_1>"]
        for example in procedure.example_bindings
    } == {"cors", "express"}


def test_file_write_and_install_workflow_masks_literals_and_key_order(
    tmp_path,
):
    memory = Howdex(path=tmp_path / "workflow.db", embedder="hashing")
    _store_episode(
        memory,
        "first",
        [
            {
                "tool": "fs.write",
                "args": {"path": "app.js", "content": "alpha"},
            },
            {"tool": "bash", "args": {"cmd": "npm install cors"}},
        ],
    )
    _store_episode(
        memory,
        "second",
        [
            {
                "args": {"content": "beta", "path": "server.js"},
                "tool": "fs.write",
            },
            {"args": {"cmd": "npm install express"}, "tool": "bash"},
        ],
    )

    procedure = memory.learn(min_samples=2)[0]

    assert [step["action"] for step in procedure.parameterized_steps] == [
        "fs.write",
        "npm install <PKG_1>",
    ]
    assert procedure.parameterized_steps[0]["arguments"]["path"] == (
        "<FILE_PATH_1>"
    )
    assert procedure.support_count == 2


def test_test_and_node_file_targets_merge(tmp_path):
    for command, first_path, second_path, canonical_name in (
        ("pytest", "tests/test_a.py", "tests/test_b.py", "run_test_suite"),
        ("node", "app.js", "server.js", "execute_file"),
    ):
        memory = Howdex(
            path=tmp_path / f"{command}.db",
            embedder="hashing",
        )
        for episode_id, path in (("first", first_path), ("second", second_path)):
            _store_episode(
                memory,
                episode_id,
                [{"tool": "bash", "args": {"cmd": f"{command} {path}"}}],
                task=f"run {command} target",
            )

        procedure = memory.learn(min_samples=2)[0]

        assert procedure.canonical_steps[0]["canonical_name"] == canonical_name
        assert procedure.parameterized_steps[0]["action"] == (
            f"{command} <FILE_PATH_1>"
        )


def test_command_package_and_file_target_matrix():
    expected = {
        "npm i cors": "npm i <PKG_1>",
        "pnpm add zod": "pnpm add <PKG_1>",
        "yarn add lodash": "yarn add <PKG_1>",
        "pip install fastapi": "pip install <PKG_1>",
        "poetry add pydantic": "poetry add <PKG_1>",
        "cargo add serde": "cargo add <PKG_1>",
        "go get github.com/foo/bar": "go get <PKG_1>",
        "python app.py": "python <FILE_PATH_1>",
        "node server.js": "node <FILE_PATH_1>",
        "ts-node src/index.ts": "ts-node <FILE_PATH_1>",
    }

    for command, template in expected.items():
        assert (
            parameterize_action(
                canonicalize_action(command)
            ).parameterized_action
            == template
        )


def test_url_port_id_hash_email_and_branch_are_typed():
    action = parameterize_action(
        canonicalize_tool_call(
            "custom.process",
            {
                "url": "http://localhost:3000/health",
                "port": 3000,
                "payment_intent": "pi_123",
                "uuid": "123e4567-e89b-12d3-a456-426614174000",
                "hash": "a" * 64,
                "email": "user@example.com",
                "branch": "feature/fix-auth",
            },
        )
    )

    assert action.parameterized_args == {
        "branch": "<BRANCH_1>",
        "email": "<EMAIL_1>",
        "hash": "<HASH_1>",
        "payment_intent": "<ID_1>",
        "port": "<PORT_1>",
        "url": "<URL_1>",
        "uuid": "<ID_2>",
    }


def test_secret_values_are_redacted_from_learning_and_output(tmp_path):
    first_secret = "sensitive-first-value"
    second_secret = "sensitive-second-value"
    memory = Howdex(path=tmp_path / "secrets.db", embedder="hashing")
    for path, secret in (
        ("app.js", first_secret),
        ("server.js", second_secret),
    ):
        with memory.session("write protected file") as session:
            session.tool_call(
                "fs.write",
                {
                    "path": path,
                    "content": "safe content",
                    "api_key": secret,
                    "authorization": f"Bearer {secret}",
                },
                "written",
            )

    procedure = memory.learn(min_samples=2)[0]
    export_dir = tmp_path / "portable"
    memory.export_procedures(export_dir)
    exported = next(export_dir.glob("*.json")).read_text(encoding="utf-8")
    serialized = json.dumps(
        {
            "procedure": procedure.to_memory().metadata,
            "export": json.loads(exported),
        },
        sort_keys=True,
    )

    assert first_secret not in serialized
    assert second_secret not in serialized
    assert REDACTED in serialized
    assert all(
        REDACTED not in str(example["bindings"].values())
        for example in procedure.example_bindings
    )
    command = parameterize_action(
        canonicalize_action(
            "deploy service --bearer another-sensitive-value"
        )
    )
    assert "another-sensitive-value" not in str(command.to_dict())
    assert REDACTED in command.parameterized_action


def test_unrelated_structured_workflows_do_not_merge(tmp_path):
    memory = Howdex(path=tmp_path / "unrelated.db", embedder="hashing")
    _store_episode(
        memory,
        "write",
        [{"tool": "fs.write", "args": {"path": "app.js", "content": "x"}}],
    )
    _store_episode(
        memory,
        "notify",
        [
            {
                "tool": "slack.send_message",
                "args": {"channel": "alerts", "message": "service down"},
            }
        ],
    )

    assert memory.learn(min_samples=2) == []
