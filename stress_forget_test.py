from howdex import Howdex
from pathlib import Path
import shutil

demo_dir = Path.home() / ".howdex-stress-forget"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

mem = Howdex(path=str(demo_dir / "howdex.db"))

print("\n🧠 Howdex Stress Test 5: Forget/Delete")
print("=====================================\n")

m = mem.remember(
    "SECRET_TEST_MEMORY: user temporary password is banana123",
    layer="semantic",
    type="fact",
    importance=0.99,
)

print(f"Stored memory id: {m.id}")

before = mem.recall("temporary password", top_k=5, min_score=0.0)

print("\nBefore forget:")
for r in before:
    print(f"   [{r.score:.3f}] {r.memory.content}")

mem.forget(m.id)

after = mem.recall("temporary password", top_k=5, min_score=0.0)

print("\nAfter forget:")
for r in after:
    print(f"   [{r.score:.3f}] {r.memory.content}")

still_found = any("SECRET_TEST_MEMORY" in r.memory.content for r in after)

print("\nRESULT")
print("======")
if still_found:
    print("❌ FAIL: Forgotten memory was still recalled.")
else:
    print("✅ PASS: Forgotten memory no longer appears in recall.")
