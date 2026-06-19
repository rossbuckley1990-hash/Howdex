"""Tests for CRDT sync."""

import json
import pytest

from howdex import Howdex
from howdex.sync import sync_to_file, sync_from_file, export_ops, import_ops


def test_export_import_roundtrip(tmp_path):
    # node A
    a = Howdex(path=tmp_path / "a.db", embedder="hashing")
    a.remember("hello from A")
    a.remember("another fact")

    ops = export_ops(a.store)
    assert len(ops) >= 2

    # node B
    b = Howdex(path=tmp_path / "b.db", embedder="hashing")
    n = import_ops(b.store, ops)
    assert n == len(ops)

    # B should now see A's memories
    results = b.recall("hello from A", min_score=0.0)
    assert any("hello from A" in r.memory.content for r in results)


def test_file_sync(tmp_path):
    a = Howdex(path=tmp_path / "a.db", embedder="hashing")
    a.remember("shared memory")
    sync_file = tmp_path / "sync.json"
    n_pushed = sync_to_file(a.store, str(sync_file))
    assert n_pushed >= 1

    b = Howdex(path=tmp_path / "b.db", embedder="hashing")
    n_pulled = sync_from_file(b.store, str(sync_file))
    assert n_pulled >= 1

    results = b.recall("shared memory", min_score=0.0)
    assert any("shared memory" in r.memory.content for r in results)


def test_idempotent_import(tmp_path):
    a = Howdex(path=tmp_path / "a.db", embedder="hashing")
    a.remember("x")
    ops = export_ops(a.store)

    b = Howdex(path=tmp_path / "b.db", embedder="hashing")
    import_ops(b.store, ops)
    # importing again should not duplicate
    import_ops(b.store, ops)
    results = b.recall("x", min_score=0.0)
    contents = [r.memory.content for r in results]
    assert sum(1 for c in contents if c == "x") == 1


def test_delete_propagates(tmp_path):
    a = Howdex(path=tmp_path / "a.db", embedder="hashing")
    m = a.remember("delete me")
    a.forget(m.id)
    ops = export_ops(a.store)

    b = Howdex(path=tmp_path / "b.db", embedder="hashing")
    # first push the create
    create_ops = [op for op in ops if op["op"] == "upsert"]
    import_ops(b.store, create_ops)
    # then push the delete
    delete_ops = [op for op in ops if op["op"] == "delete"]
    import_ops(b.store, delete_ops)

    # B should not have this memory
    assert b.store.get(m.id) is None or b.store.get(m.id) is None
