"""
Build Your Own Agent Memory (in ~200 lines)
===========================================

The runnable companion to the blog post. Copy this file, run it, and
watch a tiny agent-memory system learn from its own traces.

    python examples/build-your-own/agent_memory.py

No dependencies beyond Python 3.9+ and the standard library.
Each section maps to a section of the blog post.
"""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

# ────────────────────────────────────────────────────────────────────── #
# Section 1: The Mental Model
# ────────────────────────────────────────────────────────────────────── #
# Four memory types every agent needs:
#
#   working    — the current scratchpad (context window)
#   episodic   — what happened (session logs)
#   semantic   — facts ("the user prefers dark mode")
#   procedural — how to do the work (reusable routines)  ← this post
#
# Procedural memory is what turns an agent from "answers questions"
# into "does the job better over time." It's also the least served
# by existing tools. Let's build the smallest version that works.


# ────────────────────────────────────────────────────────────────────── #
# Section 2: Log Episodes (~30 lines)
# ────────────────────────────────────────────────────────────────────── #

class EpisodeStore:
    """A dead-simple episodic store backed by SQLite.

    Records what the agent did: each tool call, its observation,
    and the session outcome (success / failure).
    """

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                task TEXT,
                outcome TEXT,
                steps TEXT,        -- JSON array
                created_at REAL
            )
        """)
        self.conn.commit()
        self._current = None
        self._steps = []

    def start_session(self, task: str):
        self._current = hashlib.sha256(
            f"{task}:{time.time()}".encode()
        ).hexdigest()[:12]
        self._steps = []
        self._task = task

    def log_step(self, action: str, observation: str):
        self._steps.append({
            "action": action,
            "observation": observation,
            "timestamp": time.time(),
        })

    def end_session(self, outcome: str):
        self.conn.execute(
            "INSERT INTO episodes VALUES (?,?,?,?,?)",
            (self._current, self._task, outcome,
             json.dumps(self._steps), time.time()),
        )
        self.conn.commit()

    def get_episodes(self, task: str = None) -> list[dict]:
        if task:
            rows = self.conn.execute(
                "SELECT * FROM episodes WHERE task=?", (task,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM episodes").fetchall()
        return [
            {"id": r[0], "task": r[1], "outcome": r[2],
             "steps": json.loads(r[3]), "created_at": r[4]}
            for r in rows
        ]


# Demo: run the same task twice
def demo_step1():
    print("\n=== Step 1: Log Episodes ===\n")
    store = EpisodeStore()

    # First run — agent struggles, finds the fix
    store.start_session("fix_missing_dependency")
    store.log_step("read package.json", "dependency 'express' listed")
    store.log_step("run node app.js", "Error: Cannot find module 'express'")
    store.log_step("run npm install express", "added 1 package")
    store.log_step("run node app.js", "App running on port 3000")
    store.end_session("success")

    # Second run — same task, slightly different path
    store.start_session("fix_missing_dependency")
    store.log_step("read package.json", "dependency 'cors' listed")
    store.log_step("run node app.js", "Error: Cannot find module 'cors'")
    store.log_step("run npm install cors", "added 1 package")
    store.log_step("run node app.js", "App running on port 3000")
    store.end_session("success")

    episodes = store.get_episodes("fix_missing_dependency")
    print(f"Stored {len(episodes)} episodes for 'fix_missing_dependency':")
    for ep in episodes:
        print(f"  [{ep['outcome']}] {len(ep['steps'])} steps")
        for s in ep["steps"]:
            print(f"    {s['action']} → {s['observation'][:50]}")
    print("\n→ We remember what happened. But we're not learning anything yet.")

    return store


# ────────────────────────────────────────────────────────────────────── #
# Section 3: Find the Reusable Routine (~50 lines)
# ────────────────────────────────────────────────────────────────────── #

# Canonicalization: normalize "read package.json" and "check the manifest"
# into the same canonical action. In production this is the hard part —
# here we use a simple keyword map.
_CANONICAL_MAP = {
    "read": "read_config",
    "check": "read_config",
    "inspect": "read_config",
    "run node": "execute_app",
    "run npm install": "install_dependency",
    "npm install": "install_dependency",
    "pip install": "install_dependency",
}

def canonicalize(action: str) -> str:
    """Normalize an action string to a canonical name."""
    action_lower = action.lower()
    for keyword, canonical in _CANONICAL_MAP.items():
        if keyword in action_lower:
            return canonical
    return "unknown"


def extract_procedure(episodes: list[dict], min_samples: int = 2) -> dict | None:
    """Extract a reusable procedure from multiple successful episodes.

    This is the simplest possible workflow induction:
    1. Filter to successful episodes
    2. Canonicalize each step
    3. Find the shared sub-sequence (longest common sequence)
    """
    successes = [ep for ep in episodes if ep["outcome"] == "success"]
    if len(successes) < min_samples:
        return None

    # Canonicalize all steps
    canonical_traces = []
    for ep in successes:
        trace = [canonicalize(s["action"]) for s in ep["steps"]]
        canonical_traces.append(trace)

    # Find the longest common subsequence (simplified — just take the
    # intersection of canonical action sets, in order of first appearance)
    common_actions = set.intersection(*[
        set(trace) for trace in canonical_traces
    ])

    # Build the procedure from the first trace, keeping only common actions
    procedure_steps = []
    for action in canonical_traces[0]:
        if action in common_actions:
            procedure_steps.append(action)

    return {
        "task": successes[0]["task"],
        "steps": procedure_steps,
        "sample_count": len(successes),
        "canonical_traces": canonical_traces,
    }


def demo_step2(store: EpisodeStore):
    print("\n=== Step 2: Find the Reusable Routine ===\n")

    episodes = store.get_episodes("fix_missing_dependency")
    procedure = extract_procedure(episodes, min_samples=2)

    if procedure:
        print(f"Extracted procedure: {procedure['task']}")
        print(f"  Samples: {procedure['sample_count']}")
        print(f"  Steps: {' → '.join(procedure['steps'])}")
        print(f"\n  Canonical traces:")
        for i, trace in enumerate(procedure["canonical_traces"], 1):
            print(f"    Run {i}: {' → '.join(trace)}")
        print(f"\n→ 3 messy traces collapsed into one clean procedure.")
        print(f"→ This is procedural memory. This is workflow induction.")
    else:
        print("Not enough successful episodes to extract a procedure.")

    return procedure


# ────────────────────────────────────────────────────────────────────── #
# Section 4: Retrieve and Inject (~40 lines)
# ────────────────────────────────────────────────────────────────────── #

def retrieve_procedure(procedures: list[dict], task: str) -> dict | None:
    """Retrieve the best-matching procedure for a new task."""
    if not procedures:
        return None

    # Simple keyword overlap score — but also check if any task word
    # appears in the procedure's steps
    best = None
    best_score = 0
    for proc in procedures:
        task_words = set(task.lower().split())
        proc_words = set(proc["task"].lower().split())
        # Also check step words
        step_words = set()
        for s in proc.get("steps", []):
            step_words.update(s.lower().split("_"))
        score = len(task_words & (proc_words | step_words))
        if score > best_score:
            best = proc
            best_score = score

    return best if best_score > 0 else None


def render_guidance(procedure: dict) -> str:
    """Render a procedure as agent-ready guidance."""
    lines = [
        "# PROCEDURAL MEMORY",
        "",
        "Use this as prior guidance. Verify in the current environment.",
        "",
        f"Task: {procedure['task']}",
        f"Samples: {procedure['sample_count']}",
        "",
        "Recommended steps:",
    ]
    for i, step in enumerate(procedure["steps"], 1):
        lines.append(f"  {i}. {step}")
    lines.extend([
        "",
        "Rules:",
        "- Adapt these steps to the current environment.",
        "- Do not claim success until a real verifier passes.",
        "- If a step fails, update your plan rather than repeating it.",
    ])
    return "\n".join(lines)


def demo_step3(procedure: dict):
    print("\n=== Step 3: Retrieve and Inject ===\n")

    # New task — similar but not identical
    new_task = "Fix a Node app that cannot find module bcrypt"
    print(f"New task: {new_task}")

    retrieved = retrieve_procedure([procedure], new_task)
    if retrieved:
        guidance = render_guidance(retrieved)
        print(f"\nRetrieved procedure: {retrieved['task']}")
        print(f"\n--- Agent Guidance ---")
        print(guidance)
        print(f"--- End Guidance ---\n")
        print("→ The agent now has a roadmap. It skips the dead-ends")
        print("  and goes straight to: read config → install dep → verify.")
        print("→ This is the payoff: the agent starts cold but doesn't")
        print("  solve from scratch.")
    else:
        print("No matching procedure found.")


# ────────────────────────────────────────────────────────────────────── #
# Section 5: Where It Gets Hard (the honest middle)
# ────────────────────────────────────────────────────────────────────── #
# Run this section to see the landmines explained:

def demo_step5():
    print("\n=== Section 5: Where It Gets Hard ===\n")
    print("""The 200 lines above work. They also paper over four landmines
that separate a toy from a production system:

1. CANONICALIZATION
   "read package.json" and "check the manifest" are the same step.
   Our keyword map catches the easy cases. But what about:
     - "look at the dependency file"
     - "cat package.json"
     - "inspect node_modules"
   A rules-based approach (like ours) is inspectable but brittle.
   An LLM-based extractor generalizes better but is harder to audit.
   The research (AWM) found LLM extraction generalizes better.
   Production systems need both: rules for speed, LLM for coverage.

2. WHEN NOT TO TRUST A RECALLED PROCEDURE
   A procedure that worked once isn't proven. Maybe the environment
   was different. Maybe the agent got lucky. Injecting bad guidance
   is worse than no guidance — it sends the agent down a wrong path
   with confidence.

   The fix: mark procedures as "candidate" until a DETERMINISTIC
   VERIFIER (not an LLM) confirms the outcome. A test suite passing.
   An HTTP 200. An exit code 0. Only then promote to "verified."

   An LLM saying "I think it worked" is NOT verification. It's an
   observation. The distinction is the difference between a toy and
   a system you'd deploy in production.

3. DON'T PASTE THE ANSWER
   If memory just hands the agent the literal solution, you've proven
   nothing about reuse. The agent might just copy-paste a fix that
   doesn't apply to the new environment.

   The fix: guidance must be OPERATIONAL FACTS, not literal code.
   "The fix involves renaming the module file to match the import"
   — not "rename util.py to utils.py." The agent reconstructs the
   implementation from the facts, adapting to the current environment.

4. AND THEN THERE'S...
   - Segmentation: one session might contain multiple tasks. How do
     you split them?
   - Secrets: tool calls often contain API keys, passwords, tokens.
     They must be redacted before storage.
   - Latency: retrieval must be fast (sub-100ms) or the agent loop
     stalls.
   - Cross-task contamination: a procedure for "fix a bug" shouldn't
     surface when the agent is "deploying to production."
   - Context budget: injecting 5 large procedures into a small model's
     context window causes "needle in a haystack" collapse.

The easy 200 lines were the easy part.
The trust and abstraction are the actual product.
""")


# ────────────────────────────────────────────────────────────────────── #
# Section 6: The Grown-Up Version
# ────────────────────────────────────────────────────────────────────── #

def demo_step6():
    print("=== Section 6: The Grown-Up Version ===\n")
    print("""Everything in Section 5 is what Howdex does at production grade:

  - Deterministic + inspectable extraction (50+ canonical verbs,
    not a keyword map)
  - Verification layer: the BootProof gate blocks learn() unless a
    deterministic, non-LLM verifier (exit code, HTTP 200, test pass)
    confirms the result. An LLM "I think it worked" is rejected.
  - Receipts: every verified procedure carries a content-hashed,
    optionally HMAC-signed receipt. This is the "SSL certificate"
    of agent governance.
  - Secret redaction: API keys, tokens, passwords are stripped
    before storage. Automatically.
  - MCP server: any agent (Claude Desktop, Cursor, Windsurf) can
    use it via the Model Context Protocol.
  - Portable: procedures are JSON, not model weights. They move
    across models, frameworks, and clouds.
  - Compliance reports: maps receipts to SOC 2, EU AI Act, NIST AI
    RMF control objectives. Audit-ready.
  - Public registry: verified procedures shared across teams.

    pip install howdex-ai
    python examples/first_time_dev.py

    Repo: https://github.com/rossbuckley1990-hash/Howdex
""")


# ────────────────────────────────────────────────────────────────────── #
# Main
# ────────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    print("=" * 60)
    print("  Build Your Own Agent Memory (in ~200 lines)")
    print("=" * 60)

    # Step 1: Log episodes
    store = demo_step1()

    # Step 2: Extract a procedure
    procedure = demo_step2(store)

    # Step 3: Retrieve and inject
    if procedure:
        demo_step3(procedure)

    # Step 5: The hard parts
    demo_step5()

    # Step 6: The grown-up version
    demo_step6()

    print("\n" + "=" * 60)
    print("  Clone Howdex, point it at your agent,")
    print("  tell me what procedures it learns.")
    print("=" * 60)
