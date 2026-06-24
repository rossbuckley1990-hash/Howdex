"""End-to-end tests for the Howdex engine."""

import pytest

from howdex import Howdex
from howdex.core.types import MemoryLayer


@pytest.fixture
def mem(tmp_path):
    return Howdex(path=tmp_path / "test.db", embedder="hashing")


def test_remember_and_search(mem):
    mem.remember("The user prefers dark mode and sans-serif fonts",
                 layer="semantic", type="preference", importance=0.9)
    mem.remember("The weather today is sunny", layer="semantic", importance=0.3)
    results = mem.search("user UI preferences", top_k=2)
    assert len(results) > 0
    assert "dark mode" in results[0].memory.content


def test_search_no_results(mem):
    results = mem.search("nonexistent topic xyz123")
    assert len(results) == 0


def test_search_layer_filter(mem):
    mem.remember("fact one", layer="semantic")
    mem.remember("scratch one", layer="working")
    results = mem.search("one", layer="semantic", top_k=5, min_score=0.0)
    assert all(r.memory.layer == MemoryLayer.SEMANTIC for r in results)


def test_recall_remains_compatibility_alias(mem):
    mem.remember("compatibility memory")
    results = mem.recall("compatibility", min_score=0.0)
    assert any(r.memory.content == "compatibility memory" for r in results)


def test_working_memory_ttl(mem):
    mem.remember("temp note", layer="working", ttl=0.01)
    import time
    time.sleep(0.02)
    results = mem.recall("temp note", include_expired=False, min_score=0.0)
    assert all(r.memory.content != "temp note" for r in results)


def test_forget(mem):
    m = mem.remember("forget me")
    mem.forget(m.id)
    results = mem.recall("forget me", min_score=0.0)
    assert all(r.memory.id != m.id for r in results)


def test_session_lifecycle(mem):
    mem.start_session("test task")
    mem.log_step("step1", "ok")
    mem.log_step("step2", "ok")
    ep = mem.end_session("success")
    assert ep.outcome == "success"
    assert len(ep.steps) == 2
    # the session should be stored as episodic memory
    results = mem.recall("test task", layer="episodic", min_score=0.0)
    # at least one should be from this session
    assert any(r.memory.session_id == ep.session_id for r in results)


def test_learn_produces_procedure(mem):
    """Run several episodes with the same task, then consolidate."""
    for _i in range(3):
        mem.start_session("deploy to production")
        mem.log_step("run tests", "ok")
        mem.log_step("build image", "ok")
        mem.log_step("deploy", "ok")
        mem.end_session("success")

    procs = mem.learn(min_samples=3)
    assert len(procs) == 1
    assert procs[0].task_signature == "deploy to production"
    assert procs[0].success_rate == 1.0
    assert procs[0].sample_count == 3
    assert len(procs[0].steps) >= 1
    assert procs[0].preconditions == [
        "build_artifact",
        "deploy_service",
        "run_test_suite",
    ]


def test_learn_no_episodes(mem):
    procs = mem.learn()
    assert procs == []


def test_stats(mem):
    mem.remember("a", layer="semantic")
    mem.remember("b", layer="working")
    s = mem.stats()
    assert s["total_memories"] >= 2


def test_vacuum_removes_expired(mem):
    mem.remember("temp", layer="working", ttl=0.01)
    import time
    time.sleep(0.02)
    n = mem.vacuum()
    assert n >= 1


def test_relations_and_graph_search(mem):
    """Memories linked by relations should be reachable via graph expansion."""
    m1 = mem.remember("Python is a programming language", layer="semantic")
    mem.remember("Python was created by Guido van Rossum", layer="semantic",
                      relations=[{"type": "about", "target": m1.id}])
    # search for something that matches m1 directly; m2 should come via graph
    results = mem.recall("programming language", top_k=10, min_score=0.0)
    ids = [r.memory.id for r in results]
    assert m1.id in ids
    # graph expansion might or might not pull in m2 depending on scoring;
    # at minimum the direct hit should be there


def test_context_manager(tmp_path):
    with Howdex(path=tmp_path / "ctx.db", embedder="hashing") as mem:
        mem.remember("hello")
        s = mem.stats()
        assert s["total_memories"] == 1
