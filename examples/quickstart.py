"""Quickstart — the 60-second tour of Howdex.

Run: python examples/quickstart.py
"""

from howdex import Howdex


def main():
    # 1. zero-config init — creates ~/.howdex/howdex.db
    # we override the path here just to keep the example self-contained
    mem = Howdex(path="./quickstart.db", embedder="hashing")

    # 2. remember some facts
    mem.remember("User prefers dark mode and minimal UI",
                 layer="semantic", type="preference", importance=0.9)
    mem.remember("User's timezone is Asia/Shanghai",
                 layer="semantic", type="fact", importance=0.8)
    mem.remember("User asked about the weather yesterday",
                 layer="episodic", type="turn", importance=0.3)

    # 3. search
    print("=== Howdex: 'UI preferences' ===")
    for r in mem.search("UI preferences", top_k=3):
        print(f"  [{r.score:.2f} {r.matched_by}] {r.memory.content}")

    print("\n=== Howdex: 'what does the user like?' ===")
    for r in mem.search("what does the user like?", top_k=3):
        print(f"  [{r.score:.2f} {r.matched_by}] {r.memory.content}")

    # 4. run an episodic session (so learn() has something to chew on)
    for _ in range(3):
        mem.start_session("send morning briefing")
        mem.log_step("fetch calendar", "ok")
        mem.log_step("summarize emails", "ok")
        mem.log_step("send slack message", "ok")
        mem.end_session("success")

    # 5. consolidate episodes → procedures
    print("\n=== Learn ===")
    procs = mem.learn(min_samples=3)
    for p in procs:
        print(f"  Learned: {p.task_signature}")
        print(f"    success_rate={p.success_rate}, samples={p.sample_count}")
        for i, s in enumerate(p.steps):
            print(f"    {i+1}. {s['action']} → {s['observation']}")

    # 6. stats
    print("\n=== Stats ===")
    for k, v in mem.stats().items():
        print(f"  {k}: {v}")

    mem.close()
    print("\n✓ Done. Inspect quickstart.db with: howdex --path ./quickstart.db stats")


if __name__ == "__main__":
    main()
