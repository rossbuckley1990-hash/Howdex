"""Structured tool-call canonicalisation tests."""

from howdex import Howdex
from howdex.core.actions import canonicalize_action, canonicalize_steps
from howdex.core.tool_calls import canonicalize_tool_call


def test_github_create_pr_uses_normalized_name_and_repo_target():
    action = canonicalize_tool_call(
        " GitHub.Create-PR ",
        {"title": "Ship structured calls", "repo": "openai/howdex"},
        {"source": "openai", "call_id": "call-1"},
    )

    assert action.canonical_name == "github.create_pr"
    assert action.intent == "create"
    assert action.target == "repo=openai/howdex"
    assert action.raw_name == "GitHub.Create-PR"
    assert action.raw_args["title"] == "Ship structured calls"
    assert action.provenance == {
        "source": "openai",
        "call_id": "call-1",
        "schema_name": None,
    }
    assert action.matched_by == "structured_tool_call"
    assert action.evidence["side_effecting"] is True


def test_stripe_refund_projects_payment_identifier():
    payment_intent = canonicalize_tool_call(
        "stripe.refund",
        {"payment_intent": "pi_123", "amount": 2500},
    )
    charge = canonicalize_tool_call(
        "stripe.refund",
        {"charge": "ch_123"},
    )

    assert payment_intent.intent == "transfer"
    assert payment_intent.target == "payment_intent=pi_123"
    assert charge.target == "charge=ch_123"
    assert payment_intent.evidence["side_effecting"] is True


def test_filesystem_read_and_write_are_distinguished():
    read = canonicalize_tool_call(
        "filesystem.read_file",
        {"path": "src/howdex.py"},
    )
    write = canonicalize_tool_call(
        "filesystem.write_file",
        {"content": "safe", "path": "src/howdex.py"},
    )

    assert read.intent == "read"
    assert read.target == "path=src/howdex.py"
    assert read.evidence["side_effecting"] is False
    assert write.intent == "write"
    assert write.target == "path=src/howdex.py"
    assert write.evidence["side_effecting"] is True


def test_ehr_and_bio_tools_need_no_domain_registry():
    medication = canonicalize_tool_call(
        "ehr.administer_med",
        {"medication": "amoxicillin", "patient": "patient-42"},
    )
    analysis = canonicalize_tool_call(
        "bio.run_deseq2",
        {"dataset": "counts-v3", "project": "oncology"},
    )

    assert medication.canonical_name == "ehr.administer_med"
    assert medication.intent == "execute"
    assert medication.target == "patient=patient-42;medication=amoxicillin"
    assert analysis.canonical_name == "bio.run_deseq2"
    assert analysis.intent == "execute"
    assert analysis.target == "project=oncology;dataset=counts-v3"


def test_unknown_custom_tool_preserves_identity_with_unknown_intent():
    action = canonicalize_tool_call(
        " Custom Tools/Reticulate-Splines ",
        {"id": "job-7"},
    )

    assert action.canonical_name == "custom_tools.reticulate_splines"
    assert action.intent == "unknown"
    assert action.target == "id=job-7"
    assert action.confidence > 0.5


def test_target_hash_is_stable_across_argument_ordering():
    first = canonicalize_tool_call(
        "custom.compute",
        {"alpha": 1, "beta": {"two": 2, "one": 1}},
    )
    second = canonicalize_tool_call(
        "custom.compute",
        {"beta": {"one": 1, "two": 2}, "alpha": 1},
    )

    assert first.target.startswith("args:sha256:")
    assert first.target == second.target


def test_secret_values_are_redacted_from_args_and_target():
    first = canonicalize_tool_call(
        "custom.authenticate",
        {
            "api_key": "sk-secret-one",
            "credentials": {"token": "nested-secret"},
            "user": "alice",
        },
    )
    second = canonicalize_tool_call(
        "custom.authenticate",
        {
            "api_key": "sk-secret-two",
            "credentials": {"token": "different-secret"},
            "user": "alice",
        },
    )

    assert first.raw_args["api_key"] == "[REDACTED]"
    assert first.raw_args["credentials"]["token"] == "[REDACTED]"
    assert first.target == "user=alice"
    assert first.target == second.target
    assert first.evidence["redacted_argument_paths"] == [
        "api_key",
        "credentials.token",
    ]
    assert "sk-secret" not in str(first.to_dict())


def test_metadata_can_define_open_intent_and_primary_target():
    action = canonicalize_tool_call(
        "enterprise.perform_operation",
        {"destination": "warehouse-9", "payload": {"rows": 3}},
        {
            "intent": "transfer",
            "primary_argument": "destination",
            "source": "mcp",
        },
    )

    assert action.intent == "transfer"
    assert action.target == "destination=warehouse-9"
    assert action.provenance["source"] == "mcp"


def test_common_framework_step_shapes_prefer_structured_calls():
    actions = canonicalize_steps(
        [
            {
                "action": "some vague prose",
                "tool_name": "filesystem.read_file",
                "arguments": {"path": "README.md"},
                "metadata": {"framework": "langchain"},
            },
            {
                "function": {
                    "name": "github.create_pr",
                    "arguments": '{"repo":"openai/howdex","title":"Release"}',
                }
            },
            {
                "type": "tool_use",
                "name": "bio.run_deseq2",
                "input": {"dataset": "counts"},
                "provider": "anthropic",
            },
            {
                "name": "stripe.refund",
                "arguments": {"charge": "ch_123"},
                "source": "mcp",
            },
        ]
    )

    assert [action.canonical_name for action in actions] == [
        "filesystem.read_file",
        "github.create_pr",
        "bio.run_deseq2",
        "stripe.refund",
    ]
    assert all(action.matched_by == "structured_tool_call" for action in actions)


def test_legacy_prose_fallback_still_works():
    action = canonicalize_action("run tests with pytest", "passed")
    from_steps = canonicalize_steps(
        [{"action": "patch package.json test script", "observation": "fixed"}]
    )

    assert action.canonical_name == "run_test_suite"
    assert action.matched_by == "legacy_prose"
    assert from_steps[0].canonical_name == "repair_test_command"
    assert from_steps[0].matched_by == "legacy_prose"


def test_structured_tool_calls_flow_into_learned_procedure(tmp_path):
    memory = Howdex(path=tmp_path / "structured.db", embedder="hashing")
    for _ in range(2):
        with memory.session("publish release") as session:
            session.tool_call(
                "filesystem.read_file",
                {"path": "pyproject.toml"},
                "version read",
                {"source": "mcp"},
            )
            session.tool_call(
                "github.create_pr",
                {"repo": "openai/howdex", "title": "Release"},
                "created",
                {"source": "openai"},
            )

    procedure = memory.learn(min_samples=2)[0]

    assert [step["action"] for step in procedure.steps] == [
        "filesystem.read_file",
        "github.create_pr",
    ]
    raw_call = procedure.raw_supporting_examples[0]["steps"][0]
    assert raw_call["arguments"] == {"path": "pyproject.toml"}
    assert raw_call["metadata"]["source"] == "mcp"


def test_structured_secrets_are_redacted_from_procedure_evidence(tmp_path):
    memory = Howdex(path=tmp_path / "redacted.db", embedder="hashing")
    for _ in range(2):
        with memory.session("authenticate service") as session:
            session.tool_call(
                "custom.authenticate",
                {"api_key": "secret-value", "user": "alice"},
                "authenticated",
            )

    procedure = memory.learn(min_samples=2)[0]
    serialized = str(procedure.raw_supporting_examples)

    assert "secret-value" not in serialized
    assert "[REDACTED]" in serialized
