"""Multi-agent memory sharing via Howdex sync.

Two agents on the same machine share a memory layer through file-based
CRDT sync. In production you'd use HTTP sync; the principle is identical.

Run: python examples/multi_agent_sync.py
"""

import time
from pathlib import Path

from howdex import Howdex


def main():
    workdir = Path("./multi-agent-demo")
    workdir.mkdir(exist_ok=True)

    # agent A — observes something
    a = Howdex(path=workdir / "agent_a.db", embedder="hashing", agent_id="agent-a")
    a.remember("Customer Acme Corp is churning — escalations up 40% this week",
               layer="semantic", type="fact", importance=0.95)
    a.remember("Customer Acme Corp's renewal date is 2025-03-15",
               layer="semantic", type="fact", importance=0.85)

    # agent A pushes its memory to a sync file
    sync_file = str(workdir / "sync.json")
    n = a.sync(peer=sync_file)
    print(f"Agent A pushed {n['pushed']} ops to {sync_file}")

    # agent B pulls the sync file — now B knows what A knows
    b = Howdex(path=workdir / "agent_b.db", embedder="hashing", agent_id="agent-b")
    n = b.sync(peer=sync_file)
    print(f"Agent B pulled {n['pulled']} ops")

    # B can now recall A's memories
    results = b.recall("Acme Corp renewal", top_k=3)
    print("\n=== Agent B recalls ===")
    for r in results:
        print(f"  [{r.score:.2f}] {r.memory.content}")

    # B adds new info
    b.remember("Acme Corp CTO is unhappy with API rate limits",
               layer="semantic", importance=0.9)

    # B pushes back
    sync_file_2 = str(workdir / "sync_b.json")
    n = b.sync(peer=sync_file_2)
    print(f"\nAgent B pushed {n['pushed']} ops")

    # A pulls
    n = a.sync(peer=sync_file_2)
    print(f"Agent A pulled {n['pulled']} ops")

    results = a.recall("Acme Corp CTO complaint", top_k=3)
    print("\n=== Agent A now also knows about the CTO ===")
    for r in results:
        print(f"  [{r.score:.2f}] {r.memory.content}")

    a.close()
    b.close()


if __name__ == "__main__":
    main()
