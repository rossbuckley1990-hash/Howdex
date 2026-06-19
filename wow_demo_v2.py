from howdex import Howdex
import shutil
from pathlib import Path

demo_dir = Path.home() / ".howdex-wow-demo-v2"
if demo_dir.exists():
    shutil.rmtree(demo_dir)
demo_dir.mkdir(parents=True, exist_ok=True)

db_path = demo_dir / "howdex.db"
mem = Howdex(path=str(db_path))

print("\n🧠 Howdex Wow Demo v2")
print("=====================")
print("Scenario: an AI agent stops making the same deployment mistake twice.\n")

print("0) Initial problem")
print("   The agent keeps deploying without checking DATABASE_URL.")
print("   First deploy fails. Later attempts succeed after the agent learns the safe sequence.\n")

mem.remember(
    "Production deploys fail when DATABASE_URL is missing.",
    layer="semantic",
    type="fact",
    importance=0.98,
)

mem.remember(
    "Safe production deployment requires tests, DATABASE_URL validation, Docker build, and deploy.",
    layer="semantic",
    type="fact",
    importance=0.92,
)

sessions = [
    {
        "label": "Attempt 1",
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
        "label": "Attempt 2",
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("check DATABASE_URL", "missing"),
            ("build docker image", "passed"),
            ("deploy service", "failed safely before release: DATABASE_URL missing"),
        ],
        "outcome": "failure",
        "error": "blocked unsafe deploy because DATABASE_URL missing",
    },
    {
        "label": "Attempt 3",
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("check DATABASE_URL", "present"),
            ("build docker image", "passed"),
            ("deploy service", "success"),
        ],
        "outcome": "success",
        "error": None,
    },
    {
        "label": "Attempt 4",
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("check DATABASE_URL", "present"),
            ("build docker image", "passed"),
            ("deploy service", "success"),
        ],
        "outcome": "success",
        "error": None,
    },
    {
        "label": "Attempt 5",
        "task": "deploy api to production",
        "steps": [
            ("run tests", "passed"),
            ("check DATABASE_URL", "present"),
            ("build docker image", "passed"),
            ("deploy service", "success"),
        ],
        "outcome": "success",
        "error": None,
    },
]

print("1) Recording agent attempts into episodic memory...\n")

for s in sessions:
    mem.start_session(s["task"])
    for action, observation in s["steps"]:
        mem.log_step(action, observation)
    mem.end_session(s["outcome"], error=s["error"])

    status = "❌ FAILURE" if s["outcome"] == "failure" else "✅ SUCCESS"
    print(f"   {s['label']}: {status}")
    for action, observation in s["steps"]:
        print(f"      - {action} → {observation}")
    print()

print("2) New agent session asks: 'What went wrong last time?'\n")

failure_memories = mem.recall(
    "why did the production deploy fail last time?",
    top_k=4,
    min_score=0.0,
)

for r in failure_memories:
    print(f"   [{r.score:.3f}] {r.memory.content}")

print("\n3) Howdex now learns from repeated episodes...\n")

procedures = mem.learn(min_samples=3)

if not procedures:
    print("   ❌ No procedures learned.")
else:
    for p in procedures:
        print(f"   🧠 Learned procedure: {p.task_signature}")
        print(f"   Success rate: {p.success_rate:.0%}")
        print(f"   Evidence: {p.sample_count} attempts")
        print("   Learned safe sequence:")
        for i, step in enumerate(p.steps, start=1):
            action = step.get("action", step)
            print(f"      {i}. {action}")

print("\n4) Future moment: the agent is about to deploy again.\n")

proc = mem.get_procedure("deploy api to production")

if proc:
    print("   Agent asks Howdex: 'How do I safely deploy api to production?'")
    print("\n   ✅ Howdex answers with learned muscle memory:\n")
    for i, step in enumerate(proc.steps, start=1):
        action = step.get("action", step)
        print(f"      {i}. {action}")
else:
    print("   ❌ No procedure found.")

print("\n5) Final proof from local SQLite memory store:\n")

stats = mem.stats()
print(f"   Semantic memories:   {stats.get('per_layer', {}).get('semantic', 0)}")
print(f"   Episodic memories:   {stats.get('per_layer', {}).get('episodic', 0)}")
print(f"   Procedural memories: {stats.get('per_layer', {}).get('procedural', 0)}")
print(f"   Episodes recorded:   {stats.get('episodes')}")
print(f"   Procedures learned:  {stats.get('procedures')}")
print(f"   Local database:      {stats.get('db_path')}")

print("\n🔥 Demo line:")
print("   Before Howdex: the agent repeats mistakes.")
print("   After Howdex: the agent turns experience into reusable operational memory.")
