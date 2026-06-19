from pathlib import Path
import shutil

from howdex import Howdex


def fresh_memory(name: str) -> Howdex:
    root = Path.home() / f".howdex-prod-test-{name}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return Howdex(path=str(root / "howdex.db"))


def test_session_context_manager_records_success():
    mem = fresh_memory("session")

    with mem.session("deploy api") as s:
        s.step("check_database_url", "present")
        s.step("run_tests", "passed")

    stats = mem.stats()
    assert stats["episodes"] >= 1


def test_remember_trusted_sets_metadata():
    mem = fresh_memory("trusted")

    memory = mem.remember_trusted(
        "Before deploying, check DATABASE_URL.",
        source="system",
        trust="verified",
        safety="operational",
        importance=0.95,
    )

    assert memory.metadata["source"] == "system"
    assert memory.metadata["trust"] == "verified"
    assert memory.metadata["verified"] is True
    assert memory.metadata["trusted"] is True
    assert memory.metadata["safety"] == "operational"


def test_procedure_alias():
    mem = fresh_memory("procedure")

    task = "deploy api"

    for _ in range(3):
        with mem.session(task) as s:
            s.step("check_database_url", "present")
            s.step("run_tests", "passed")

    mem.learn(min_samples=2)

    proc = mem.procedure(task)
    assert proc is not None
