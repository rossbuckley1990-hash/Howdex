"""Deterministic intent and side-effect classification tests."""

import pytest

from howdex.core.actions import canonicalize_steps
from howdex.core.classification import INTENTS, SIDE_EFFECT_CLASSES
from howdex.core.tool_calls import canonicalize_tool_call


@pytest.mark.parametrize(
    ("tool_name", "expected_intent"),
    [
        ("records.read_item", "read"),
        ("records.search_items", "search"),
        ("records.list_items", "list"),
        ("records.create_item", "create"),
        ("records.update_item", "update"),
        ("records.write_item", "write"),
        ("records.delete_item", "delete"),
        ("jobs.execute_task", "execute"),
        ("ledger.transfer_funds", "transfer"),
        ("messages.send_message", "notify"),
        ("workflow.approve_request", "approve"),
        ("workflow.reject_request", "reject"),
        ("auth.login", "authenticate"),
        ("custom.reticulate_splines", "unknown"),
    ],
)
def test_all_intent_ontology_values(tool_name, expected_intent):
    action = canonicalize_tool_call(tool_name, {"id": "example"})

    assert action.intent == expected_intent
    assert action.intent in INTENTS
    assert action.evidence["intent_rule"]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_intent", "expected_class"),
    [
        (
            "filesystem.read_file",
            {"path": "README.md"},
            "read",
            "read_only",
        ),
        (
            "filesystem.write_file",
            {"path": "README.md", "content": "updated"},
            "write",
            "local_write",
        ),
        (
            "github.create_pr",
            {"repo": "acme/service", "title": "Release"},
            "create",
            "external_write",
        ),
        (
            "stripe.refund",
            {"payment_intent": "pi_123", "amount": 100},
            "transfer",
            "financial",
        ),
        (
            "db.drop_table",
            {"table": "obsolete"},
            "delete",
            "destructive",
        ),
        (
            "auth.login",
            {"user": "alice", "password": "secret"},
            "authenticate",
            "security_sensitive",
        ),
        (
            "custom.reticulate_splines",
            {"id": "job-7"},
            "unknown",
            "unknown",
        ),
    ],
)
def test_all_side_effect_classes(
    tool_name,
    arguments,
    expected_intent,
    expected_class,
):
    action = canonicalize_tool_call(tool_name, arguments)

    assert action.intent == expected_intent
    assert action.side_effect_class == expected_class
    assert action.side_effect_class in SIDE_EFFECT_CLASSES
    assert action.evidence["side_effect_rule"]


def test_notify_is_an_external_write():
    action = canonicalize_tool_call(
        "slack.send_message",
        {"channel": "engineering", "message": "Deploy complete"},
    )

    assert action.intent == "notify"
    assert action.side_effect_class == "external_write"
    assert action.evidence["side_effecting"] is True


def test_metadata_can_override_side_effect_class_and_hint_intent():
    action = canonicalize_tool_call(
        "custom.perform_operation",
        {"resource": "record-7"},
        {
            "verb": "patch",
            "side_effect_class": "security_sensitive",
        },
    )

    assert action.intent == "update"
    assert action.side_effect_class == "security_sensitive"
    assert action.evidence["intent_rule"] == "metadata_verb:patch"
    assert action.evidence["side_effect_rule"] == "metadata_side_effect_class"


def test_schema_and_mcp_annotation_hints_are_used():
    local_write = canonicalize_tool_call(
        "custom.persist",
        {"payload": "value"},
        {
            "intent": "write",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    )
    read_only = canonicalize_tool_call(
        "custom.perform",
        {},
        {"annotations": {"readOnlyHint": True}},
    )

    assert local_write.side_effect_class == "local_write"
    assert local_write.evidence["side_effect_rule"] == "local_mutation_signal"
    assert read_only.intent == "read"
    assert read_only.side_effect_class == "read_only"
    assert read_only.evidence["side_effect_rule"] == "metadata_read_only"


def test_classification_is_deterministic_across_argument_order():
    first = canonicalize_tool_call(
        "filesystem.write_file",
        {"content": "hello", "path": "notes.txt"},
        {"source": "mcp"},
    )
    second = canonicalize_tool_call(
        "filesystem.write_file",
        {"path": "notes.txt", "content": "hello"},
        {"source": "mcp"},
    )

    assert first.to_dict() == second.to_dict()


def test_stored_side_effect_class_is_preserved():
    action = canonicalize_steps(
        [
            {
                "action": "legacy description",
                "tool_name": "custom.perform",
                "tool_args": {"id": "job-7"},
                "canonical_action": "custom.perform",
                "intent": "execute",
                "side_effect_class": "destructive",
            }
        ]
    )[0]

    assert action.side_effect_class == "destructive"
    assert action.evidence["side_effect_rule"] == "stored_side_effect_class"
