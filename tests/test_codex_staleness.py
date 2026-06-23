from __future__ import annotations

import json
from pathlib import Path

from howdex.core.codex_staleness import (
    evaluate_codex_staleness,
)
from howdex.core.guidance import render_agent_guidance


ROOT = Path(__file__).resolve().parents[1]


def _react_entry(**compatibility_overrides):
    compatibility = {
        "ecosystem": "javascript",
        "framework": "react",
        "known_incompatible_versions": ["19.x"],
        "last_verified_at": "2026-06-01",
        "stale_after_days": 90,
        "tested_versions": ["18.2.0"],
        "version_range": ">=18 <19",
    }
    compatibility.update(compatibility_overrides)
    return {
        "category": "frontend",
        "compatibility": compatibility,
        "confidence": 0.9,
        "id": "react-18-render",
        "learned_facts": [
            "Use the React 18 render recovery procedure for this frontend task."
        ],
        "status": "candidate",
        "tags": ["react", "frontend"],
        "task_signature": "React 18 render recovery",
        "title": "React 18 render recovery",
        "verification": [
            "Run the local frontend test suite before marking done.",
        ],
    }


def test_react_18_entry_in_react_18_is_fresh():
    decision = evaluate_codex_staleness(
        _react_entry(),
        {
            "as_of": "2026-06-23",
            "ecosystem": "javascript",
            "framework": "react",
            "version": "18.2.0",
        },
    )

    assert decision.status == "fresh"
    assert decision.required_reverification is False
    assert decision.confidence_multiplier == 1.0


def test_react_18_entry_in_react_19_is_incompatible_when_metadata_says_so():
    decision = evaluate_codex_staleness(
        _react_entry(),
        {
            "as_of": "2026-06-23",
            "ecosystem": "javascript",
            "framework": "react",
            "version": "19.0.0",
        },
    )

    assert decision.status == "incompatible"
    assert decision.required_reverification is True
    assert decision.confidence_multiplier == 0.0
    assert any("incompatible" in reason for reason in decision.reasons)


def test_react_18_entry_in_react_19_warns_when_not_known_incompatible():
    decision = evaluate_codex_staleness(
        _react_entry(known_incompatible_versions=[]),
        {
            "as_of": "2026-06-23",
            "ecosystem": "javascript",
            "framework": "react",
            "version": "19.0.0",
        },
    )

    assert decision.status == "warning"
    assert decision.required_reverification is True
    assert decision.confidence_multiplier < 1.0


def test_entry_past_stale_after_days_is_stale():
    decision = evaluate_codex_staleness(
        _react_entry(last_verified_at="2026-01-01", stale_after_days=30),
        {
            "as_of": "2026-06-23",
            "ecosystem": "javascript",
            "framework": "react",
            "version": "18.2.0",
        },
    )

    assert decision.status == "stale"
    assert decision.required_reverification is True
    assert decision.confidence_multiplier < 1.0
    assert any("stale_after_days" in reason for reason in decision.reasons)


def test_unknown_environment_is_not_treated_as_verified():
    decision = evaluate_codex_staleness(_react_entry(), None)

    assert decision.status in {"unknown", "warning"}
    assert decision.required_reverification is True
    assert decision.confidence_multiplier < 1.0


def test_guidance_includes_staleness_warning():
    guidance = render_agent_guidance(
        [_react_entry(last_verified_at="2026-01-01", stale_after_days=30)],
        objective="Repair a React 18 frontend render issue",
        current_environment={
            "as_of": "2026-06-23",
            "ecosystem": "javascript",
            "framework": "react",
            "version": "18.2.0",
        },
    )

    assert "Codex staleness:" in guidance
    assert "stale; reverify before relying on it" in guidance
    assert "Reverify React 18 render recovery before relying on it" in guidance


def test_incompatible_entry_is_blocked_historical_not_recommended_guidance():
    guidance = render_agent_guidance(
        [_react_entry()],
        objective="Repair a React 19 frontend render issue",
        current_environment={
            "as_of": "2026-06-23",
            "ecosystem": "javascript",
            "framework": "react",
            "version": "19.0.0",
        },
    )

    assert "Blocked/historical memory:" in guidance
    assert "not recommended for the current environment" in guidance
    assert "Use the React 18 render recovery procedure" not in guidance
    assert "staleness=incompatible" in guidance


def test_existing_seed_entries_validate_with_optional_compatibility_metadata():
    schema = json.loads(
        (ROOT / "codex" / "schemas" / "procedure.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert "compatibility" in schema["properties"]
    assert "compatibility" not in schema["required"]

    required = set(schema["required"])
    for path in sorted((ROOT / "codex" / "entries").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert required <= set(entry), path
        if "compatibility" in entry:
            assert isinstance(entry["compatibility"], dict), path


def test_staleness_guidance_output_is_deterministic():
    kwargs = {
        "objective": "Repair a React 18 frontend render issue",
        "current_environment": {
            "as_of": "2026-06-23",
            "ecosystem": "javascript",
            "framework": "react",
            "version": "18.2.0",
        },
    }
    first = render_agent_guidance([_react_entry()], **kwargs)
    second = render_agent_guidance([_react_entry()], **kwargs)

    assert first == second
