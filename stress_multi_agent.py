from howdex import Howdex
from pathlib import Path
import shutil

demo_dir = Path.home() / ".howdex-stress-multi-agent"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

db_path = str(demo_dir / "howdex.db")

agent_a = Howdex(path=db_path, agent_id="deploy-agent")
agent_b = Howdex(path=db_path, agent_id="support-agent")

print("\n🧠 Howdex Stress Test 4: Multi-Agent Memory")
print("==========================================\n")

agent_a.remember(
    "Deploy agent rule: check DATABASE_URL before deployment.",
    layer="semantic",
    type="fact",
    importance=0.95,
)

agent_b.remember(
    "Support agent rule: check customer SLA before responding.",
    layer="semantic",
    type="fact",
    importance=0.95,
)

print("Query as deploy-agent:")
results_a = agent_a.recall("what should I check before acting?", top_k=5, min_score=0.0, agent_id="deploy-agent")

for r in results_a:
    print(f"   [{r.score:.3f}] {r.memory.content}")

print("\nQuery as support-agent:")
results_b = agent_b.recall("what should I check before acting?", top_k=5, min_score=0.0, agent_id="support-agent")

for r in results_b:
    print(f"   [{r.score:.3f}] {r.memory.content}")

pass_a = any("DATABASE_URL" in r.memory.content for r in results_a)
pass_b = any("SLA" in r.memory.content for r in results_b)

print("\nRESULT")
print("======")
if pass_a and pass_b:
    print("✅ PASS: Agent-specific retrieval works.")
else:
    print("❌ FAIL: Agent-specific retrieval confused memories.")
