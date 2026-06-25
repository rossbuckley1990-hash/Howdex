from howdex import Howdex
from pathlib import Path
import shutil
import random

demo_dir = Path.home() / ".howdex-stress-procedure"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

mem = Howdex(path=str(demo_dir / "howdex.db"))

print("\n🧠 Howdex Stress Test 3: Noisy Procedure Learning")
print("================================================\n")

task = "deploy api to production"

successful_core = [
    ("run tests", "passed"),
    ("check DATABASE_URL", "present"),
    ("check migration file", "present"),
    ("run migration", "success"),
    ("deploy service", "success"),
]

noise_steps = [
    ("read docs", "irrelevant"),
    ("check weather", "irrelevant"),
    ("ping teammate", "no response"),
    ("open dashboard", "loaded"),
    ("clear terminal", "done"),
]

# 10 successful sessions with random noise inserted
for i in range(10):
    mem.start_session(task)

    steps = successful_core.copy()

    # insert 0-2 random noisy steps
    for _ in range(random.randint(0, 2)):
        insert_at = random.randint(0, len(steps))
        steps.insert(insert_at, random.choice(noise_steps))

    for action, observation in steps:
        mem.log_step(action, observation)

    mem.end_session("success")

# 5 failed sessions
failed_sessions = [
    [
        ("run tests", "passed"),
        ("deploy service", "failed: DATABASE_URL missing"),
    ],
    [
        ("run tests", "failed"),
    ],
    [
        ("run tests", "passed"),
        ("check DATABASE_URL", "missing"),
    ],
    [
        ("run tests", "passed"),
        ("check DATABASE_URL", "present"),
        ("run migration", "failed: migration file missing"),
    ],
    [
        ("deploy service", "failed: no checks performed"),
    ],
]

for steps in failed_sessions:
    mem.start_session(task)
    for action, observation in steps:
        mem.log_step(action, observation)
    mem.end_session("failure", error=steps[-1][1])

procedures = mem.learn(min_samples=5)

print("Learned procedures:")
for p in procedures:
    print(f"\nTask: {p.task_signature}")
    print(f"Success rate: {p.success_rate:.0%}")
    print(f"Evidence: {p.sample_count}")
    print("Steps:")
    for i, step in enumerate(p.steps, start=1):
        action = step.get("action", step) if isinstance(step, dict) else step
        print(f"   {i}. {action}")

proc = mem.get_procedure(task)

expected = [
    "run tests",
    "check DATABASE_URL",
    "check migration file",
    "run migration",
    "deploy service",
]

learned = []
if proc:
    learned = [
        step.get("action", step) if isinstance(step, dict) else step
        for step in proc.steps
    ]

print("\nRESULT")
print("======")
print("Expected core sequence:")
for x in expected:
    print(f"   - {x}")

print("\nLearned sequence:")
for x in learned:
    print(f"   - {x}")

missing = [x for x in expected if x not in learned]

if not missing:
    print("\n✅ PASS: Howdex learned the core procedure despite noise and failures.")
else:
    print(f"\n❌ FAIL: Missing expected steps: {missing}")
