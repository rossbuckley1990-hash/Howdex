from howdex import Howdex
from pathlib import Path
import shutil

demo_dir = Path.home() / ".howdex-stress-meta-cognition"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

mem = Howdex(path=str(demo_dir / "howdex.db"))

task = "deploy api to production with database migration"

successful_steps = [
    ("inspect_howdex", "Relevant Howdex memories found"),
    ("check_DATABASE_URL", "present"),
    ("check_migration_file", "present"),
    ("run_database_migration", "success"),
    ("deploy_service", "success"),
]

for _ in range(5):
    mem.start_session(task)
    for action, observation in successful_steps:
        mem.log_step(action, observation)
    mem.end_session("success")

procedures = mem.learn(min_samples=3)
proc = mem.get_procedure(task)

learned = []
if proc:
    learned = [
        step.get("action", step) if isinstance(step, dict) else step
        for step in proc.steps
    ]

print("\n🧠 Howdex Stress Test: Meta-Cognition Filter")
print("===========================================")
print("Learned sequence:")
for step in learned:
    print(f"   - {step}")

print("\nRESULT")
print("======")

if "inspect_howdex" in learned:
    print("❌ FAIL: Internal memory tool leaked into executable procedure.")
else:
    print("✅ PASS: Internal memory tool was excluded from learned procedure.")

expected = [
    "check_DATABASE_URL",
    "check_migration_file",
    "run_database_migration",
    "deploy_service",
]

missing = [step for step in expected if step not in learned]

if missing:
    print(f"❌ FAIL: Missing real procedural steps: {missing}")
else:
    print("✅ PASS: Real deployment steps were preserved.")
