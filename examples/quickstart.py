"""Quickstart — the 60-second tour of Howdex.

Run: python examples/quickstart.py

This quickstart demonstrates the full Howdex loop end-to-end:
  1. zero-config init
  2. remember some semantic facts
  3. search semantic memory
  4. run an episodic session with STRUCTURED tool calls
  5. consolidate episodes -> procedures
  6. pull guidance for a related task and see the learned procedure surface

Note: `log_step("fetch calendar", "ok")` (prose form) does NOT produce
procedures because the canonicalizer cannot recognize "fetch calendar"
as a known tool action. Use `log_tool_call(tool_name, args, observation)`
instead — that's what Howdex is designed to learn from.
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

    # 4. run an episodic session with STRUCTURED tool calls.
    # Repeat 3 times so consolidation has enough samples (min_samples=3).
    print("\n=== Record 3 sessions of a recurring task ===")
    for _ in range(3):
        mem.start_session("send_morning_briefing")
        mem.log_tool_call(
            "fetch_calendar",
            {"source": "google_calendar", "range": "today"},
            "3 events scheduled today",
        )
        mem.log_tool_call(
            "summarize_emails",
            {"mailbox": "inbox", "max_messages": 50},
            "12 unread emails, 3 marked important",
        )
        mem.log_tool_call(
            "send_slack_message",
            {"channel": "#morning-briefing", "text": "Good morning! Here's your briefing..."},
            "message sent successfully",
        )
        mem.end_session("success")

    # 5. consolidate episodes -> procedures
    print("\n=== Learn ===")
    procs = mem.learn(min_samples=3)
    print(f"learned {len(procs)} procedure(s)")
    for p in procs:
        print(f"  Task: {p.task_signature}")
        print(f"    success_rate={p.success_rate}, samples={p.sample_count}, confidence={p.confidence:.3f}")
        for i, s in enumerate(p.steps):
            print(f"    {i+1}. {s.get('action')} -> {s.get('observation', '')[:60]}")

    # 6. pull guidance for a fresh related task — this is the value prop
    print("\n=== Guidance for a related fresh task ===")
    guidance = mem.guidance(
        "Prepare the morning briefing for the team channel",
        max_chars=4000,
    )
    print(guidance)

    # 7. stats
    print("\n=== Stats ===")
    for k, v in mem.stats().items():
        print(f"  {k}: {v}")

    mem.close()
    print("\n✓ Done. Inspect quickstart.db with: howdex --path ./quickstart.db stats")


if __name__ == "__main__":
    main()
