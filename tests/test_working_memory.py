"""Deterministic session-scoped working-memory tests."""

from howdex import Howdex
from howdex.core.types import Memory, MemoryLayer, MemoryType
from howdex.core.working import select_working_context


def _working(
    content: str,
    *,
    memory_id: str,
    created_at: float,
    importance: float = 0.5,
    ttl: float | None = 300,
    session_id: str = "session-1",
    source: str = "agent",
    metadata: dict | None = None,
) -> Memory:
    return Memory(
        id=memory_id,
        layer=MemoryLayer.WORKING,
        type=MemoryType.CONTEXT,
        content=content,
        metadata=metadata or {},
        source=source,
        session_id=session_id,
        created_at=created_at,
        accessed_at=created_at,
        importance=importance,
        ttl=ttl,
    )


def test_expired_working_items_are_excluded():
    memories = [
        _working(
            "expired",
            memory_id="expired",
            created_at=0,
            ttl=5,
        ),
        _working(
            "active",
            memory_id="active",
            created_at=10,
            ttl=20,
        ),
    ]

    selected, context = select_working_context(
        memories,
        max_chars=None,
        include_provenance=False,
        now=15,
    )

    assert [memory.id for memory in selected] == ["active"]
    assert context == "active"


def test_equal_importance_uses_recency_ordering():
    memories = [
        _working("old", memory_id="old", created_at=1),
        _working("new", memory_id="new", created_at=3),
        _working("middle", memory_id="middle", created_at=2),
    ]

    selected, _ = select_working_context(
        memories,
        max_chars=None,
        include_provenance=False,
        now=4,
    )

    assert [memory.id for memory in selected] == ["new", "middle", "old"]


def test_importance_can_outweigh_recency():
    memories = [
        _working(
            "critical older fact",
            memory_id="important",
            created_at=1,
            importance=1.0,
        ),
        _working(
            "minor recent note",
            memory_id="recent",
            created_at=2,
            importance=0.1,
        ),
    ]

    selected, _ = select_working_context(
        memories,
        max_chars=None,
        include_provenance=False,
        now=3,
    )

    assert [memory.id for memory in selected] == ["important", "recent"]


def test_item_and_character_budgets_limit_context():
    memories = [
        _working("first context item", memory_id="first", created_at=3),
        _working("second context item", memory_id="second", created_at=2),
        _working("third context item", memory_id="third", created_at=1),
    ]

    selected, context = select_working_context(
        memories,
        max_items=2,
        max_chars=12,
        include_provenance=False,
        now=4,
    )

    assert [memory.id for memory in selected] == ["first"]
    assert len(context) <= 12
    assert context.endswith("…")
    assert "second" not in context


def test_max_items_evicts_lower_ranked_items():
    memories = [
        _working("first", memory_id="first", created_at=3),
        _working("second", memory_id="second", created_at=2),
        _working("third", memory_id="third", created_at=1),
    ]

    selected, context = select_working_context(
        memories,
        max_items=2,
        max_chars=None,
        include_provenance=False,
        now=4,
    )

    assert [memory.id for memory in selected] == ["first", "second"]
    assert context == "first\nsecond"


def test_token_budget_uses_deterministic_character_approximation():
    memory = _working(
        "abcdefghijklmnopqrstuvwxyz",
        memory_id="alphabet",
        created_at=1,
    )

    _, context = select_working_context(
        [memory],
        max_chars=None,
        token_budget=4,
        include_provenance=False,
        now=2,
    )

    assert len(context) == 16
    assert context.endswith("…")


def test_working_context_is_deterministic_and_includes_provenance():
    memories = [
        _working(
            "release is blocked",
            memory_id="blocked",
            created_at=2,
            importance=0.9,
            source="tool",
            metadata={"provenance": {"call_id": "call-7", "source": "mcp"}},
        ),
        _working(
            "tests are green",
            memory_id="tests",
            created_at=1,
            importance=0.7,
        ),
    ]

    first = select_working_context(memories, now=3)[1]
    second = select_working_context(list(reversed(memories)), now=3)[1]

    assert first == second
    assert "source=tool" in first
    assert 'provenance={"call_id":"call-7","source":"mcp"}' in first


def test_get_working_context_is_session_isolated(tmp_path):
    memory = Howdex(path=tmp_path / "working.db", embedder="hashing")
    memory.remember(
        "session one note",
        layer="working",
        session_id="session-1",
        embed=False,
    )
    memory.remember(
        "session two note",
        layer="working",
        session_id="session-2",
        embed=False,
    )

    first = memory.get_working_context(
        "session-1",
        include_provenance=False,
    )
    second = memory.get_working_context(
        "session-2",
        include_provenance=False,
    )

    assert first == "session one note"
    assert second == "session two note"


def test_active_session_is_the_default_working_context(tmp_path):
    memory = Howdex(path=tmp_path / "active.db", embedder="hashing")
    session = memory.start_session("investigate incident")
    memory.remember(
        "database is healthy",
        layer="working",
        importance=0.8,
        embed=False,
    )

    context = memory.get_working_context(include_provenance=False)

    assert context == "database is healthy"
    assert memory.store.query(
        layer=MemoryLayer.WORKING,
        session_id=session.session_id,
    )[0].session_id == session.session_id


def test_session_close_flushes_bounded_working_context_to_episode(tmp_path):
    memory = Howdex(path=tmp_path / "flush.db", embedder="hashing")
    episode = memory.start_session("prepare release")
    kept = memory.remember(
        "release checklist complete",
        layer="working",
        importance=0.9,
        source="agent",
        metadata={"provenance": {"step": "checklist"}},
        embed=False,
    )
    memory.remember(
        "expired scratch note",
        layer="working",
        ttl=0,
        embed=False,
    )

    memory.end_session("success")
    episodic = memory.store.query(
        layer=MemoryLayer.EPISODIC,
        session_id=episode.session_id,
    )[0]

    assert episodic.metadata["working_memory_ids"] == [kept.id]
    assert episodic.metadata["working_memory_count"] == 1
    assert "release checklist complete" in episodic.metadata[
        "working_memory_context"
    ]
    assert "expired scratch note" not in episodic.metadata[
        "working_memory_context"
    ]
