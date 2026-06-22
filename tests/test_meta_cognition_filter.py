from pathlib import Path
import shutil

from howdex import Howdex


def test_inspect_howdex_is_not_learned_as_procedure_step():
    root = Path.home() / ".howdex-test-meta-cognition-filter"

    if root.exists():
        shutil.rmtree(root)

    root.mkdir(parents=True, exist_ok=True)

    mem = Howdex(path=str(root / "howdex.db"))

    task = "deploy api to production with database migration"

    steps = [
        ("inspect_howdex", "Relevant Howdex memories found"),
        ("check_DATABASE_URL", "present"),
        ("check_migration_file", "present"),
        ("run_database_migration", "success"),
        ("deploy_service", "success"),
    ]

    for _ in range(5):
        mem.start_session(task)
        for action, observation in steps:
            mem.log_step(action, observation)
        mem.end_session("success")

    mem.learn(min_samples=3)

    proc = mem.get_procedure(task)
    assert proc is not None

    learned = [
        step.get("action", step) if isinstance(step, dict) else step
        for step in proc.steps
    ]

    assert "inspect_howdex" not in learned
    assert "unknown" not in learned
    assert learned == [
        "inspect_file",
        "inspect_file",
        "run_database_migration",
        "deploy_service",
    ]
