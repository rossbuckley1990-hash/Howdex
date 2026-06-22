"""Deterministic procedure retrieval and prompt-injection tests."""

from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance
from howdex.core.types import Procedure


def _store_procedure(
    memory: Howdex,
    *,
    procedure_id: str,
    task: str,
    confidence: float,
    success_rate: float = 1.0,
    support_count: int = 3,
    steps: list[dict] | None = None,
    preconditions: list[str] | None = None,
    episode_ids: list[str] | None = None,
) -> Procedure:
    procedure = Procedure(
        id=procedure_id,
        task_signature=task,
        steps=steps or [{"action": "run_test_suite"}],
        preconditions=preconditions or [],
        expected_outcome="success",
        success_rate=success_rate,
        sample_count=support_count,
        support_count=support_count,
        success_count=round(success_rate * support_count),
        confidence=confidence,
        source_episode_ids=episode_ids or [],
    )
    memory.store.put_procedure(dict(procedure.__dict__))
    return procedure


def test_suggest_procedure_retrieves_matching_known_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "match.db", embedder="hashing")
    stored = _store_procedure(
        memory,
        procedure_id="repair-tests",
        task="repair package test command",
        confidence=0.91,
        success_rate=0.88,
        support_count=5,
        steps=[
            {
                "action": "inspect_package_manifest",
                "canonical_name": "inspect_package_manifest",
                "intent": "read",
                "target": "package.json",
            },
            {
                "action": "repair_test_command",
                "canonical_name": "repair_test_command",
                "intent": "update",
                "target": "package.json:test",
            },
        ],
        preconditions=["inspect_package_manifest"],
        episode_ids=["episode-1", "episode-2"],
    )

    suggestions = memory.suggest_procedure("repair package test command")

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.procedure_id == stored.id
    assert suggestion.task_signature == stored.task_signature
    assert suggestion.confidence == 0.91
    assert suggestion.success_rate == 0.88
    assert suggestion.support_count == 5
    assert suggestion.canonical_steps == stored.steps
    assert suggestion.preconditions == ["inspect_package_manifest"]
    assert suggestion.source_episode_ids == ["episode-1", "episode-2"]
    assert suggestion.match_explanation["task_similarity"] == 1.0
    assert suggestion.match_explanation["recency_used"] is False


def test_suggest_procedure_filters_below_min_confidence(tmp_path):
    memory = Howdex(path=tmp_path / "confidence.db", embedder="hashing")
    _store_procedure(
        memory,
        procedure_id="low",
        task="deploy api",
        confidence=0.49,
    )

    assert memory.suggest_procedure(
        "deploy api",
        min_confidence=0.5,
    ) == []


def test_suggest_procedure_limits_top_k_and_global_maximum(tmp_path):
    memory = Howdex(path=tmp_path / "limits.db", embedder="hashing")
    for index, confidence in enumerate((0.95, 0.90, 0.85, 0.80), start=1):
        _store_procedure(
            memory,
            procedure_id=f"deploy-{index}",
            task=f"deploy service {index}",
            confidence=confidence,
        )

    assert len(memory.suggest_procedure("deploy service", top_k=2)) == 2
    assert len(memory.suggest_procedure("deploy service", top_k=20)) == 3
    assert memory.suggest_procedure("deploy service", top_k=0) == []


def test_guidance_block_is_deterministic_and_includes_provenance(tmp_path):
    memory = Howdex(path=tmp_path / "render.db", embedder="hashing")
    _store_procedure(
        memory,
        procedure_id="publish-release",
        task="publish release",
        confidence=0.93,
        success_rate=1.0,
        support_count=4,
        steps=[
            {
                "action": "github.create_pr",
                "canonical_name": "github.create_pr",
                "intent": "create",
                "target": "repo=acme/service",
                "side_effect_class": "external_write",
            }
        ],
        preconditions=["tests_green"],
        episode_ids=["episode-b", "episode-a"],
    )
    suggestion = memory.suggest_procedure("publish release")[0]

    first = memory.render_procedure_guidance(suggestion)
    second = render_procedure_guidance([suggestion])

    assert first == second
    assert "Guidance only" in first
    assert "do not execute automatically" in first
    assert "github.create_pr" in first
    assert "tests_green" in first
    assert "observed_episode_support_not_independently_verified" in first
    assert "episode-a, episode-b" in first


def test_structured_tool_context_matches_actions_targets_and_domains(tmp_path):
    memory = Howdex(path=tmp_path / "structured.db", embedder="hashing")
    github = _store_procedure(
        memory,
        procedure_id="github-release",
        task="publish software change",
        confidence=0.90,
        steps=[
            {
                "action": "github.create_pr",
                "canonical_name": "github.create_pr",
                "intent": "create",
                "target": "repo=acme/service",
                "side_effect_class": "external_write",
            }
        ],
        episode_ids=["github-episode"],
    )
    _store_procedure(
        memory,
        procedure_id="stripe-refund",
        task="refund payment",
        confidence=0.99,
        steps=[
            {
                "action": "stripe.refund",
                "canonical_name": "stripe.refund",
                "intent": "transfer",
                "target": "payment_intent=pi_123",
                "side_effect_class": "financial",
            }
        ],
        episode_ids=["stripe-episode"],
    )

    suggestions = memory.suggest_procedure(
        "prepare external change",
        context={
            "tool_name": "github.create_pr",
            "tool_args": {
                "repo": "acme/service",
                "title": "Release",
            },
            "tool_metadata": {"source": "mcp"},
        },
    )

    assert suggestions[0].procedure_id == github.id
    explanation = suggestions[0].match_explanation
    assert explanation["canonical_action_overlap"] == 1.0
    assert explanation["target_overlap"] == 1.0
    assert explanation["domain_overlap"] == 1.0
    assert suggestions[0].canonical_steps[0]["target"] == "repo=acme/service"


def test_task_text_can_match_a_canonical_procedure_step(tmp_path):
    memory = Howdex(path=tmp_path / "task-action.db", embedder="hashing")
    procedure = _store_procedure(
        memory,
        procedure_id="maintenance-tests",
        task="project maintenance",
        confidence=0.85,
        steps=[
            {
                "action": "run_test_suite",
                "canonical_name": "run_test_suite",
                "intent": "execute",
            }
        ],
    )

    suggestions = memory.suggest_procedure("run tests with pytest")

    assert suggestions[0].procedure_id == procedure.id
    assert (
        suggestions[0].match_explanation["canonical_action_overlap"]
        == 1.0
    )


def test_legacy_string_steps_remain_renderable(tmp_path):
    memory = Howdex(path=tmp_path / "legacy-steps.db", embedder="hashing")
    procedure = _store_procedure(
        memory,
        procedure_id="legacy",
        task="legacy deployment",
        confidence=0.8,
        steps=["run_test_suite", "deploy_service"],
    )

    suggestion = memory.suggest_procedure("legacy deployment")[0]
    guidance = memory.render_procedure_guidance(suggestion)

    assert suggestion.procedure_id == procedure.id
    assert suggestion.canonical_steps == [
        {"action": "run_test_suite", "canonical_name": "run_test_suite"},
        {"action": "deploy_service", "canonical_name": "deploy_service"},
    ]
    assert "run_test_suite" in guidance
    assert "deploy_service" in guidance


def test_unrelated_task_without_context_returns_no_suggestion(tmp_path):
    memory = Howdex(path=tmp_path / "unrelated.db", embedder="hashing")
    _store_procedure(
        memory,
        procedure_id="deploy",
        task="deploy api",
        confidence=1.0,
    )

    assert memory.suggest_procedure("write customer invoice") == []


def test_agent_guidance_formats_node_dependency_template_without_raw_repr():
    procedure = {
        "procedure_id": "missing-node-dependency",
        "task": "fix missing node dependency",
        "confidence": 0.91,
        "success_rate": 1.0,
        "support_count": 1,
        "episode_ids": ["episode-node"],
        "canonical_steps": [
            {
                "canonical_name": "bash",
                "parameterized_args": {
                    "cmd": "cd test_env && node <FILE_PATH_1>",
                    "cwd": "<PATH_1>",
                },
            },
            {
                "canonical_name": "bash",
                "parameterized_args": {
                    "cmd": "cd test_env && npm install <PKG_1>",
                    "cwd": "<PATH_1>",
                },
            },
            {
                "canonical_name": "bash",
                "parameterized_args": {
                    "cmd": "cd test_env && node <FILE_PATH_1>",
                    "cwd": "<PATH_1>",
                },
            },
        ],
    }

    guidance = render_procedure_guidance([procedure])

    assert "# PAST LEARNED PROCEDURE" in guidance
    assert "npm install <PKG_1>" in guidance
    assert "Cannot find module '<PKG_1>'" in guidance
    assert "Bind `<FILE_PATH_1>` to the current target file." in guidance
    assert "Bind `<PKG_1>` to the missing module/package named in the error." in guidance
    assert "parameterized_args" not in guidance
    assert "canonical_steps" not in guidance


def test_agent_guidance_renders_multiple_procedures():
    first = {
        "procedure_id": "first",
        "task": "first task",
        "canonical_steps": [
            {
                "canonical_name": "bash",
                "parameterized_args": {"cmd": "npm install <PKG_1>"},
            }
        ],
    }
    second = {
        "procedure_id": "second",
        "task": "second task",
        "canonical_steps": [
            {
                "canonical_name": "bash",
                "parameterized_args": {"cmd": "pytest"},
            }
        ],
    }

    guidance = render_procedure_guidance([first, second])

    assert "Procedure 1: first task" in guidance
    assert "Procedure 2: second task" in guidance
    assert "npm install <PKG_1>" in guidance
    assert "pytest" in guidance
