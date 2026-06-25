from howdex import Howdex
from pathlib import Path
import shutil
import random
import time

demo_dir = Path.home() / ".howdex-stress-scale"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

mem = Howdex(path=str(demo_dir / "howdex.db"))

print("\n🧠 Howdex Stress Test 1: Scale")
print("==============================")
print("Writing 10,000 memories, then searching for one critical needle.\n")

critical_memory = "CRITICAL_DEPLOY_RULE: Always check DATABASE_URL before production deploy."

start = time.time()

for i in range(10000):
    mem.remember(
        f"Noise memory {i}: random agent observation about task {random.randint(1, 500)}",
        layer="semantic",
        type="fact",
        importance=random.random(),
    )

mem.remember(
    critical_memory,
    layer="semantic",
    type="fact",
    importance=0.99,
)

write_time = time.time() - start

print(f"Stored 10,001 memories in {write_time:.2f}s")

start = time.time()
results = mem.recall("what must I check before production deploy?", top_k=10, min_score=0.0)
search_time = time.time() - start

print(f"Search completed in {search_time:.4f}s\n")

found = False

for i, r in enumerate(results, start=1):
    print(f"{i}. [{r.score:.3f}] {r.memory.content}")
    if "CRITICAL_DEPLOY_RULE" in r.memory.content:
        found = True

print("\nRESULT")
print("======")

if found:
    print("✅ PASS: Critical memory found despite 10,000 noisy memories.")
else:
    print("❌ FAIL: Critical memory was not retrieved.")

print("\nStats:")
print(mem.stats())
