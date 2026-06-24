"""Tests for the SQLite store."""

import sqlite3

import pytest

from howdex.core.types import Memory, MemoryLayer
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


def test_v1_procedure_schema_migrates_with_evidence_defaults(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1');
        CREATE TABLE procedures (
            id TEXT PRIMARY KEY,
            task_signature TEXT NOT NULL UNIQUE,
            steps TEXT NOT NULL DEFAULT '[]',
            preconditions TEXT NOT NULL DEFAULT '[]',
            expected_outcome TEXT NOT NULL DEFAULT '',
            success_rate REAL NOT NULL DEFAULT 0,
            sample_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            last_used_at REAL,
            use_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO procedures(
            id, task_signature, steps, preconditions, expected_outcome,
            success_rate, sample_count, created_at, last_used_at, use_count
        ) VALUES (
            'legacy', 'repair tests', '[]', '[]', 'success',
            0.75, 4, 1.0, NULL, 0
        );
        """
    )
    connection.close()

    migrated = Store(path)
    procedure = migrated.get_procedure("repair tests")

    assert procedure is not None
    assert procedure["support_count"] == 4
    assert procedure["success_count"] == 3
    assert procedure["failure_count"] == 1
    assert procedure["confidence"] == 0.75
    assert procedure["base_confidence"] == 0.75
    assert procedure["feedback_success_count"] == 0
    assert procedure["feedback_failure_count"] == 0
    assert procedure["suggestion_count"] == 0
    assert procedure["unverified_use_count"] == 0
    assert procedure["raw_supporting_examples"] == []
    assert procedure["parameter_bindings"] == []
    assert procedure["source_episode_ids"] == []

    reopened = Store(path)
    assert reopened.get_procedure("repair tests") == procedure
    feedback_table = reopened._conn().execute(
        """SELECT name FROM sqlite_master
           WHERE type='table' AND name='procedure_feedback'"""
    ).fetchone()
    assert feedback_table is not None
    receipt_table = reopened._conn().execute(
        """SELECT name FROM sqlite_master
           WHERE type='table' AND name='procedure_receipts'"""
    ).fetchone()
    assert receipt_table is not None
