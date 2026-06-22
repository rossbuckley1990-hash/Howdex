"""Deterministic procedure-template parameterisation tests."""

from __future__ import annotations

from howdex import Howdex
from howdex.core.actions import canonicalize_action
from howdex.core.parameterize import (
    REDACTED,
    parameter_bindings,
    parameterize_action,
    parameterize_steps,
)
from howdex.core.tool_calls import canonicalize_tool_call


def test_bash_command_parameterisation_examples():
    expected = {
        "npm install cors": "npm install <PKG_1>",
        "pnpm add zod": "pnpm add <PKG_1>",
        "pip install fastapi": "pip install <PKG_1>",
        "pytest tests/test_auth.py": "pytest <PATH_1>",
        "node server.js": "node <PATH_1>",
        "curl http://localhost:3000/health": "curl <URL_1>",
    }

    for command, template in expected.items():
        result = parameterize_action(canonicalize_action(command))
        assert result.parameterized_action == template


def test_tool_arguments_parameterize_salient_values():
    cases = [
        (
            "filesystem.read_file",
            {"path": "src/app.js"},
            {"path": "<PATH_1>"},
        ),
        (
            "github.create_pr",
            {"repo": "acme/app"},
            {"repo": "<REPO_1>"},
        ),
        (
            "stripe.refund",
            {"payment_intent": "pi_123"},
            {"payment_intent": "<ID_1>"},
        ),
    ]

    for name, arguments, expected in cases:
        result = parameterize_action(
            canonicalize_tool_call(name, arguments)
        )
        assert result.parameterized_args == expected


def test_placeholder_names_are_stable_across_dict_order():
    first = parameterize_action(
        canonicalize_tool_call(
            "custom.process",
            {"path": "src/app.js", "repo": "acme/app", "port": 3000},
        )
    )
    second = parameterize_action(
        canonicalize_tool_call(
            "custom.process",
            {"port": 3000, "repo": "acme/app", "path": "src/app.js"},
        )
    )

    assert first.parameterized_args == second.parameterized_args
    assert first.parameter_map == second.parameter_map
    assert first.parameter_map == {
        "<PATH_1>": "src/app.js",
        "<PORT_1>": 3000,
        "<REPO_1>": "acme/app",
    }


def test_repeated_literal_reuses_placeholder_and_new_values_increment():
    actions = parameterize_steps(
        [
            canonicalize_tool_call(
                "filesystem.read_file",
                {"path": "src/app.py"},
            ),
            canonicalize_tool_call(
                "filesystem.write_file",
                {"path": "src/app.py"},
            ),
            canonicalize_tool_call(
                "filesystem.read_file",
                {"path": "src/config.py"},
            ),
        ]
    )

    assert actions[0].parameterized_args["path"] == "<PATH_1>"
    assert actions[1].parameterized_args["path"] == "<PATH_1>"
    assert actions[2].parameterized_args["path"] == "<PATH_2>"
    assert parameter_bindings(actions) == {
        "<PATH_1>": "src/app.py",
        "<PATH_2>": "src/config.py",
    }


def test_secrets_are_redacted_and_never_exposed_as_bindings():
    action = canonicalize_tool_call(
        "custom.deploy",
        {
            "path": "src/app.py",
            "api_key": "secret-api-key",
            "env": {
                "MODE": "production",
                "AUTH_TOKEN": "secret-token",
            },
        },
    )
    result = parameterize_action(action)
    serialized = str(result.to_dict())

    assert result.parameterized_args["api_key"] == REDACTED
    assert result.parameterized_args["env"]["AUTH_TOKEN"] == REDACTED
    assert result.parameterized_args["env"]["MODE"] == "<ENV_VALUE_1>"
    assert "secret-api-key" not in serialized
    assert "secret-token" not in serialized
    assert "secret-api-key" not in str(result.parameter_map)
    assert "secret-token" not in str(result.parameter_map)


def test_shell_secret_is_absent_from_learned_evidence_and_bindings(tmp_path):
    memory = Howdex(path=tmp_path / "secret.db", embedder="hashing")
    for _ in range(2):
        with memory.session("deploy application") as session:
            session.step(
                "deploy service --token example-sensitive-value",
                "deployed",
            )

    procedure = memory.learn(min_samples=2)[0]
    serialized = str(procedure)
    stored_steps = str(memory.store.query_episodes())
    export_dir = tmp_path / "portable"
    memory.export_procedures(export_dir)
    exported = next(export_dir.glob("*.json")).read_text(encoding="utf-8")

    assert "example-sensitive-value" not in serialized
    assert "example-sensitive-value" not in stored_steps
    assert "example-sensitive-value" not in exported
    assert REDACTED in serialized
    assert all(
        "example-sensitive-value" not in str(example)
        for example in procedure.raw_supporting_examples
    )


def test_different_file_names_learn_one_parameterized_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "files.db", embedder="hashing")
    paths = ["src/app.py", "src/config.py", "src/worker.py"]
    for path in paths:
        with memory.session("inspect application file") as session:
            session.tool_call(
                "filesystem.read_file",
                {"path": path},
                "read",
            )

    procedure = memory.learn(min_samples=3)[0]

    assert procedure.steps[0]["action"] == "filesystem.read_file"
    assert procedure.steps[0]["parameterized_args"] == {
        "path": "<PATH_1>"
    }
    assert procedure.steps[0]["template"]["arguments"] == {
        "path": "<PATH_1>"
    }
    assert {
        binding["bindings"]["<PATH_1>"]
        for binding in procedure.parameter_bindings
    } == set(paths)


def test_different_package_names_learn_one_parameterized_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "packages.db", embedder="hashing")
    packages = ["cors", "express", "zod"]
    for package in packages:
        with memory.session("install application dependency") as session:
            session.step(f"npm install {package}", "installed")

    procedure = memory.learn(min_samples=3)[0]

    assert procedure.steps[0]["action"] == "install_dependencies"
    assert (
        procedure.steps[0]["parameterized_action"]
        == "npm install <PKG_1>"
    )
    assert {
        binding["bindings"]["<PKG_1>"]
        for binding in procedure.parameter_bindings
    } == set(packages)


def test_legacy_prose_actions_still_learn_with_templates(tmp_path):
    memory = Howdex(path=tmp_path / "legacy.db", embedder="hashing")
    for path in ("src/a.py", "src/b.py"):
        with memory.session("inspect source file") as session:
            session.step(f"read {path}", "read")

    procedure = memory.learn(min_samples=2)[0]

    assert procedure.steps[0]["action"] == "inspect_file"
    assert procedure.steps[0]["parameterized_action"] == "read <PATH_1>"
    assert len(procedure.raw_supporting_examples) == 2
    assert all(
        example["bindings"]
        for example in procedure.raw_supporting_examples
    )
