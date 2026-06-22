"""Deterministic, provenance-rich semantic memory tests."""

import json

import pytest

from howdex import Howdex
from howdex.core.types import MemoryLayer, MemoryType
from howdex.vectors import Embedder, HashingEmbedder
from howdex.vectors import embedder as embedder_module


@pytest.mark.parametrize(
    "memory_type",
    ["fact", "preference", "entity", "relation"],
)
def test_explicit_semantic_writes_preserve_type_and_provenance(
    tmp_path,
    memory_type,
):
    memory = Howdex(path=tmp_path / f"{memory_type}.db", embedder="hashing")

    written = memory.remember(
        f"explicit {memory_type} knowledge",
        layer="semantic",
        type=memory_type,
        source="agent",
        confidence=0.92,
        provenance={"run_id": "run-7", "api_key": "do-not-store"},
    )

    assert written.layer == MemoryLayer.SEMANTIC
    assert written.type == MemoryType(memory_type)
    assert written.source == "agent"
    assert written.metadata["semantic_origin"] == "explicit"
    assert written.metadata["confidence"] == 0.92
    assert written.metadata["provenance"] == {
        "api_key": "[REDACTED]",
        "run_id": "run-7",
    }


def test_explicit_fact_write_is_retrievable(tmp_path):
    memory = Howdex(path=tmp_path / "facts.db", embedder="hashing")
    fact = memory.remember(
        "Deployment region is eu-west-1",
        layer="semantic",
        type="fact",
        source="agent",
        provenance={"config": "deployment"},
    )

    results = memory.search(
        "deployment region eu-west-1",
        layer="semantic",
        min_score=0.0,
    )

    assert results[0].memory.id == fact.id
    assert results[0].memory.metadata["semantic_origin"] == "explicit"


def test_structured_tool_call_derives_entities_and_relation(tmp_path):
    memory = Howdex(path=tmp_path / "derived.db", embedder="hashing")
    memory.start_session("publish change")
    memory.log_tool_call(
        "github.create_pr",
        {"repo": "acme/service", "title": "Release v1"},
        observation="created",
        metadata={"source": "mcp", "call_id": "call-1"},
        outcome="success",
    )
    memory.end_session("success")

    semantic = memory.store.query(layer=MemoryLayer.SEMANTIC, limit=100)
    by_content = {item.content: item for item in semantic}

    assert "system:github" in by_content
    assert "action:github.create_pr" in by_content
    assert "repo:acme/service" in by_content
    relation = by_content[
        "action:github.create_pr -> repo:acme/service"
    ]
    assert relation.type == MemoryType.RELATION
    assert relation.metadata["relation"] == "targets"
    assert relation.metadata["observed_outcome"] == "success"
    assert relation.metadata["provenance"] == {
        "call_id": "call-1",
        "schema_name": None,
        "source": "mcp",
    }
    assert len(relation.relations) == 2
    assert "Release v1" not in by_content


def test_derived_semantics_are_idempotent(tmp_path):
    memory = Howdex(path=tmp_path / "idempotent.db", embedder="hashing")
    memory.start_session("publish change")
    for _ in range(2):
        memory.log_tool_call(
            "github.create_pr",
            {"repo": "acme/service", "title": "Release v1"},
            outcome="success",
        )

    semantic = memory.store.query(layer=MemoryLayer.SEMANTIC, limit=100)

    assert len(semantic) == 4
    assert len({item.id for item in semantic}) == 4


def test_structured_semantics_do_not_leak_secrets(tmp_path):
    memory = Howdex(path=tmp_path / "secrets.db", embedder="hashing")
    memory.start_session("authenticate service")
    memory.log_tool_call(
        "auth.login",
        {
            "user": "alice",
            "password": "plain-secret",
            "credentials": {"token": "nested-secret"},
        },
        metadata={
            "source": "mcp",
            "api_key": "metadata-secret",
        },
        outcome="success",
    )

    semantic = memory.store.query(layer=MemoryLayer.SEMANTIC, limit=100)
    serialized = json.dumps(
        [item.to_dict() for item in semantic],
        sort_keys=True,
    )

    assert "plain-secret" not in serialized
    assert "nested-secret" not in serialized
    assert "metadata-secret" not in serialized
    assert "user:alice" in serialized


def test_structured_semantic_derivation_can_be_disabled(tmp_path):
    memory = Howdex(path=tmp_path / "disabled.db", embedder="hashing")
    memory.start_session("private operation")
    memory.log_tool_call(
        "custom.execute",
        {"resource": "private-7"},
        derive_semantics=False,
    )

    assert memory.store.query(layer=MemoryLayer.SEMANTIC) == []


def test_auto_embedder_uses_hashing_when_optional_backend_is_unavailable(
    monkeypatch,
):
    monkeypatch.delenv("HOWDEX_EMBEDDER", raising=False)

    class UnavailableSentenceTransformer:
        def __init__(self):
            raise embedder_module.EmbeddingError("not installed")

    monkeypatch.setattr(
        embedder_module,
        "SentenceTransformerEmbedder",
        UnavailableSentenceTransformer,
    )

    selected = embedder_module.auto_embedder()

    assert isinstance(selected, HashingEmbedder)


def test_auto_embedder_prefers_available_local_neural_backend(monkeypatch):
    monkeypatch.delenv("HOWDEX_EMBEDDER", raising=False)

    class AvailableLocalEmbedder(Embedder):
        name = "test-local-neural"
        dim = 3

        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

    monkeypatch.setattr(
        embedder_module,
        "SentenceTransformerEmbedder",
        AvailableLocalEmbedder,
    )

    assert embedder_module.auto_embedder().name == "test-local-neural"


def test_hashing_semantic_retrieval_is_deterministic(tmp_path):
    memory = Howdex(path=tmp_path / "deterministic.db", embedder="hashing")
    memory.remember(
        "Service deployment region is eu-west-1",
        layer="semantic",
        type="fact",
    )
    memory.remember(
        "User prefers Python for automation",
        layer="semantic",
        type="preference",
    )

    first = memory.search(
        "Python automation preference",
        layer="semantic",
        min_score=0.0,
    )
    second = memory.search(
        "Python automation preference",
        layer="semantic",
        min_score=0.0,
    )

    assert [result.memory.id for result in first] == [
        result.memory.id for result in second
    ]
    assert [result.score for result in first] == [
        result.score for result in second
    ]
