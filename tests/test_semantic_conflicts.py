"""Semantic conflict detection scaffolding tests."""

from howdex import Howdex


def test_obvious_preference_conflict_requires_review(tmp_path):
    mem = Howdex(path=tmp_path / "conflicts.db", embedder="hashing")
    original = mem.remember(
        "User prefers Python",
        layer="semantic",
        type="preference",
    )
    conflicting = mem.remember(
        "User prefers Rust",
        layer="semantic",
        type="preference",
    )

    assert conflicting.metadata["semantic_conflict_detected"] is True
    assert conflicting.metadata["requires_review"] is True
    assert conflicting.metadata["conflict_key"] == "user:prefer"
    assert conflicting.metadata["conflicting_values"] == ["python"]
    assert conflicting.metadata["conflicts_with"] == [original.id]


def test_repeated_semantic_assertion_is_not_a_conflict(tmp_path):
    mem = Howdex(path=tmp_path / "no-conflict.db", embedder="hashing")
    mem.remember("User prefers Python", layer="semantic", type="preference")
    repeated = mem.remember(
        "User prefers Python.",
        layer="semantic",
        type="preference",
    )

    assert "semantic_conflict_detected" not in repeated.metadata
