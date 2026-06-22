"""Deterministic canonical action tests."""

from howdex.core.actions import canonicalize_action, canonicalize_steps


def test_equivalent_actions_share_canonical_name():
    actions = [
        canonicalize_action("run tests"),
        canonicalize_action("npm test"),
        canonicalize_action("execute the test suite with pytest"),
    ]

    assert {action.canonical_name for action in actions} == {"run_test_suite"}
    assert all(action.confidence >= 0.9 for action in actions)


def test_package_manifest_actions_are_deterministic():
    inspected = canonicalize_action("open package.json")
    repaired = canonicalize_action("patch the package.json test script")

    assert inspected.canonical_name == "inspect_package_manifest"
    assert inspected.target == "package.json"
    assert repaired.canonical_name == "repair_test_command"
    assert repaired.target == "package.json:test"


def test_unknown_action_has_low_confidence():
    action = canonicalize_action("ponder the shape of the repository")

    assert action.canonical_name == "unknown_action"
    assert action.confidence < 0.5
    assert action.evidence["rule"] == "no_rule_matched"


def test_canonicalize_steps_preserves_raw_evidence():
    actions = canonicalize_steps(
        [
            {"action": "read package.json", "observation": "test script found"},
            {"action": "pytest", "observation": "42 passed"},
        ]
    )

    assert [action.canonical_name for action in actions] == [
        "inspect_package_manifest",
        "run_test_suite",
    ]
    assert actions[0].raw_action == "read package.json"
    assert actions[0].evidence["observation"] == "test script found"
