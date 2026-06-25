from howdex import Howdex
from pathlib import Path
import shutil

demo_dir = Path.home() / ".howdex-stress-retrieval"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

mem = Howdex(path=str(demo_dir / "howdex.db"))

print("\n🧠 Howdex Stress Test 2: Retrieval Accuracy")
print("==========================================\n")

memories = [
    ("User prefers dark mode and compact UI.", "UI preferences"),
    ("Production deploy failed because DATABASE_URL was missing.", "deployment"),
    ("Customer ACME renewal is due on March 15.", "sales"),
    ("Agent should run database migrations before deployment.", "deployment"),
    ("User likes short answers with exact commands.", "communication"),
    ("Invoice export failed because VAT number was missing.", "finance"),
    ("Production deploy succeeded after checking DATABASE_URL and migration.sql.", "deployment"),
    ("User prefers coffee meetings in the morning.", "personal"),
]

for content, category in memories:
    mem.remember(
        content,
        layer="semantic",
        type="fact",
        metadata={"category": category},
        importance=0.8,
    )

queries = [
    {
        "query": "how do I avoid production deployment failure?",
        "expected": "deployment",
    },
    {
        "query": "how should I format the interface?",
        "expected": "UI preferences",
    },
    {
        "query": "how should I answer the user?",
        "expected": "communication",
    },
    {
        "query": "why did invoice export fail?",
        "expected": "finance",
    },
]

passes = 0

for test in queries:
    results = mem.recall(test["query"], top_k=3, min_score=0.0)
    top = results[0]
    category = top.memory.metadata.get("category")

    print(f"Query: {test['query']}")
    print(f"Expected category: {test['expected']}")
    print(f"Top result: {top.memory.content}")
    print(f"Top category: {category}")

    if category == test["expected"]:
        print("✅ PASS\n")
        passes += 1
    else:
        print("❌ FAIL\n")

print("RESULT")
print("======")
print(f"{passes}/{len(queries)} retrieval checks passed.")

if passes == len(queries):
    print("✅ PASS: Retrieval accuracy is strong on this test set.")
else:
    print("⚠️ PARTIAL: Retrieval needs tuning.")
