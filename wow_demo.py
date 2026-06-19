from howdex import Howdex
import shutil
from pathlib import Path

# Start fresh so the demo is deterministic
demo_dir = Path.home() / ".howdex-wow-demo"
if demo_dir.exists():
    shutil.rmtree(demo_dir)
demo_dir.mkdir(parents=True, exist_ok=True)

db_path = demo_dir / "howdex.db"
mem = Howdex(path=str(db_path))

print("\n🧠 Howdex Wow Demo")
print("==================")
print("Scenario: an AI agent keeps failing deployments until it learns the fix.\n")

# Store durable semantic knowledge
mem.remember(
    "Production deploys fail if DATABASE_URL is missing from the environment.",
    layer="semantic",
    type="fact",
    importance=0.95,
)

mem.remember(
    "User prefers safe deploys: run tests first, check environment variables, then deploy.",
    layer="semantic",
    type="preference",
    importance=0.9,
)

# Simulate repeated agent sessions
sessions = [
    {
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("build docker image", "passed"),
            ("deploy service", "failed: DATABASE_URL missing"),
        ],
        "outcome": "failure",
        "error": "DATABASE_URL missing",
    },
    {
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("check environment variables", "DATABASE_URL missing"),
            ("add DATABASE_URL", "added successfully"),
            ("deploy service", "success"),
        ],
        "outcome": "success",
        "error": None,
    },
    {
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("check environment variables", "DATABASE_URL present"),
            ("build docker image", "passed"),
            ("deploy service", "success"),
        ],
        "outcome": "success",
        "error": None,
    },
    {
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("check environment variables", "DATABASE_URL present"),
            ("deploy service", "success"),
        ],
        "outcome": "success",
        "error": None,
    },
]

print("1) Recording repeated agent attempts...\n")

for i, s in enumerate(sessions, start=1):
    mem.start_session(s["task"])
    for action, observation in s["steps"]:
        mem.log_step(action, observation)
    mem.end_session(s["outcome"], error=s["error"])
    print(f"   Session {i}: {s['outcome'].upper()}")

print("\n2) Asking Howdex what it remembers about deploy failures...\n")

results = mem.recall("why do production deploys fail?", top_k=3, min_score=0.0)

for r in results:
    print(f"   [{r.score:.3f}] {r.memory.content}")

print("\n3) Triggering learning from repeated episodes...\n")

procedures = mem.learn(min_samples=3)

if not procedures:
    print("   No procedure learned. Try lowering min_samples or check episode logging.")
else:
    for p in procedures:
        print(f"   Learned procedure: {p.task_signature}")
        print(f"   Success rate: {p.success_rate:.0%}")
        print(f"   Sample count: {p.sample_count}")
        print("   Steps:")
        for step in p.steps:
            action = step.get("action", step)
            print(f"     - {action}")

print("\n4) New future task: 'deploy api to production'")
print("   Howdex should now know the safe sequence.\n")

proc = mem.get_procedure("deploy api to production")

if proc:
    print("   ✅ Howdex recovered learned muscle memory:")
    for step in proc.steps:
        action = step.get("action", step)
        print(f"      → {action}")
else:
    print("   Could not retrieve procedure by exact task signature.")

print("\n5) Final proof: semantic + episodic + procedural memory are all working.\n")

stats = mem.stats()
for key, value in stats.items():
    print(f"   {key}: {value}")

print("\n🔥 Demo line:")
print("   This is not chat history. This is an agent gaining operational memory.")
