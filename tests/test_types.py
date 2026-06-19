"""Tests for the type system."""

import time

from howdex.core.types import Memory, MemoryLayer, MemoryType, Episode


def test_memory_defaults():
    m = Memory()
    assert m.layer == MemoryLayer.SEMANTIC
    assert m.type == MemoryType.FACT
    assert m.importance == 0.5
    assert m.access_count == 0
    assert len(m.id) == 36  # uuid4


def test_memory_touch():
    m = Memory()
    old_accessed = m.accessed_at
    time.sleep(0.01)
    m.touch()
    assert m.accessed_at > old_accessed
    assert m.access_count == 1


def test_memory_ttl_expired():
    m = Memory(ttl=0.01)
    time.sleep(0.02)
    assert m.is_expired()


def test_memory_ttl_not_expired():
    m = Memory(ttl=1000)
    assert not m.is_expired()


def test_memory_no_ttl_never_expires():
    m = Memory(ttl=None)
    assert not m.is_expired()


def test_memory_to_dict_roundtrip():
    m = Memory(content="hello", importance=0.9)
    d = m.to_dict()
    assert d["layer"] == "semantic"
    assert d["content"] == "hello"
    m2 = Memory.from_dict(d)
    assert m2.layer == MemoryLayer.SEMANTIC
    assert m2.content == "hello"
    assert m2.importance == 0.9


def test_episode_to_memory_success():
    ep = Episode(session_id="s1", agent_id="a1", task="deploy")
    ep.add_step("build", "ok")
    ep.add_step("deploy", "ok")
    ep.close("success")
    mem = ep.to_memory()
    assert mem.layer == MemoryLayer.EPISODIC
    assert mem.type == MemoryType.SESSION
    assert "deploy" in mem.content


def test_episode_to_memory_failure():
    ep = Episode(session_id="s1", agent_id="a1", task="deploy")
    ep.add_step("build", "ok")
    ep.close("failure", error="OOM")
    mem = ep.to_memory()
    assert mem.type == MemoryType.ERROR
    assert "OOM" in mem.content
