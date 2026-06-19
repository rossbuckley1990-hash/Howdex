"""Tests for the SQLite store."""

import json
import tempfile
from pathlib import Path

import pytest

from howdex.core.types import Memory, MemoryLayer, MemoryType
from howdex.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def test_put_and_get(store):
    m = Memory(content="hello world", layer=MemoryLayer.SEMANTIC)
    store.put(m)
    got = store.get(m.id)
    assert got is not None
    assert got.content == "hello world"
    assert got.layer == MemoryLayer.SEMANTIC


def test_get_nonexistent(store):
    assert store.get("nope") is None


def test_query_by_layer(store):
    store.put(Memory(content="s1", layer=MemoryLayer.SEMANTIC))
    store.put(Memory(content="w1", layer=MemoryLayer.WORKING))
    store.put(Memory(content="e1", layer=MemoryLayer.EPISODIC))
    sem = store.query(layer=MemoryLayer.SEMANTIC)
    assert len(sem) == 1
    assert sem[0].content == "s1"


def test_query_by_session(store):
    store.put(Memory(content="a", session_id="sess-1"))
    store.put(Memory(content="b", session_id="sess-2"))
    results = store.query(session_id="sess-1")
    assert len(results) == 1
    assert results[0].content == "a"


def test_delete_soft(store):
    m = Memory(content="x")
    store.put(m)
    store.delete(m.id)
    assert store.get(m.id) is None  # filtered out
    # but row still exists for CRDT
    row = store._conn().execute(
        "SELECT * FROM memories WHERE id=?", (m.id,)
    ).fetchone()
    assert row["deleted"] == 1


def test_touch(store):
    m = Memory(content="x")
    store.put(m)
    store.touch(m.id)
    got = store.get(m.id)
    assert got.access_count == 1


def test_persistence_across_connections(tmp_path):
    path = tmp_path / "test.db"
    s1 = Store(path)
    s1.put(Memory(content="persist me"))
    # open a second store
    s2 = Store(path)
    got = s2.query()
    assert len(got) == 1
    assert got[0].content == "persist me"


def test_node_id_stable(store):
    n1 = store.node_id
    n2 = store.node_id
    assert n1 == n2


def test_stats(store):
    store.put(Memory(content="a", layer=MemoryLayer.SEMANTIC))
    store.put(Memory(content="b", layer=MemoryLayer.WORKING))
    s = store.stats()
    assert s["total_memories"] == 2
    assert s["per_layer"]["semantic"] == 1
    assert s["per_layer"]["working"] == 1
    assert "node_id" in s
