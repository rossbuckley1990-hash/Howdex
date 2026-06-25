"""First-time developer quickstart — the full Howdex loop in one file.

This script walks through the entire Howdex value proposition end-to-end:
  1. Initialize a Howdex memory.
  2. Record a real agent trace (a 3-step "fix missing dependency" task).
  3. Consolidate the trace into a reusable procedure.
  4. Verify the procedure with a real receipt.
  5. Pull guidance for a fresh, related task — and see the learned
     procedure surface as operational memory.
  6. Publish the verified procedure to a local Codex.
  7. Lint the Codex (governance check).

Run: python examples/first_time_dev.py

This is the script to run if you're evaluating Howdex for the first time.
It produces visible output at every step and leaves you with a real,
inspectable verified Codex entry.
"""

import json
import shutil
from pathlib import Path

from howdex import Howdex


def main():
    # Use a fresh DB so this script is idempotent.
    db_path = Path("./first_time_dev.db")
    codex_path = Path("./first_time_dev_codex")
    if db_path.exists():
        db_path.unlink()
    if codex_path.exists():
        shutil.rmtree(codex_path)

    # 1. init
    print("=" * 60)
    print("1. Initialize Howdex memory")
    print("=" * 60)
    mem = Howdex(path=str(db_path))
    print(f"  db: {db_path}")
    print(f"  node_id: {mem.store.node_id}")

    # 2. record a real agent trace
    print("\n" + "=" * 60)
    print("2. Record an agent trace (fix a missing Node dependency)")
    print("=" * 60)
    mem.start_session("fix_missing_dependency")
    mem.log_tool_call(
        "execute_bash",
        {"cmd": "node app.js"},
        "Error: Cannot find module 'express'",
    )
    print("  step 1: node app.js  ->  Error: Cannot find module 'express'")
    mem.log_tool_call(
        "execute_bash",
        {"cmd": "npm install express"},
        "added 1 package",
    )
    print("  step 2: npm install express  ->  added 1 package")
    mem.log_tool_call(
        "execute_bash",
        {"cmd": "node app.js"},
        "App running on port 3000",
    )
    print("  step 3: node app.js  ->  App running on port 3000")
    mem.end_session("success")
    print("  session ended: success")

    # 3. consolidate
    print("\n" + "=" * 60)
    print("3. Consolidate the trace into a reusable procedure")
    print("=" * 60)
    procs = mem.learn(min_samples=1)
    print(f"  learned {len(procs)} procedure(s)")
    assert procs, "expected at least 1 procedure"
    proc = procs[0]
    print(f"  task_signature: {proc.task_signature}")
    print(f"  success_rate:   {proc.success_rate}")
    print(f"  confidence:     {proc.confidence:.3f}")
    print(f"  steps:")
    for i, s in enumerate(proc.steps):
        print(f"    {i+1}. {s.get('action')}")

    # 4. verify with a real receipt
    print("\n" + "=" * 60)
    print("4. Attach a verification receipt")
    print("=" * 60)
    receipt = mem.verify_procedure(
        procedure_id=proc.id,
        verifier_type="bash",
        verifier_command="node app.js | grep -q 'App running'",
        expected_signal="App running",
        observed_signal="App running on port 3000",
        exit_code=0,
    )
    print(f"  receipt_id: {receipt.receipt_id[:12]}...")
    print(f"  status:     {receipt.status}")

    # 5. pull guidance for a fresh related task
    print("\n" + "=" * 60)
    print("5. Pull guidance for a FRESH, related task")
    print("=" * 60)
    print("  Objective: 'Fix a Node app that cannot find module cors'")
    print("  (Note: the learned procedure was for 'express', not 'cors'.")
    print("   Howdex should still surface it as relevant operational memory.)")
    print()
    guidance = mem.guidance(
        "Fix a Node app that cannot find module cors",
        max_chars=2000,
    )
    print(guidance)

    # 6. publish to a local Codex
    print("\n" + "=" * 60)
    print("6. Publish the verified procedure to a local Codex")
    print("=" * 60)
    pub = mem.publish_codex(codex_path)
    print(f"  codex root:   {pub['root']}")
    print(f"  exported:     {pub['exported']} entry/entries")
    for f in pub["files"]:
        print(f"    {f}")

    # Show the entry's status
    entry_path = pub["files"][0]
    entry = json.loads(entry_path.read_text())
    print(f"\n  entry id:     {entry['id']}")
    print(f"  entry status: {entry['status']}")
    print(f"  receipt_id:   {entry['verification'].get('receipt_id', '(none)')[:12]}...")

    # 7. lint the Codex (governance check)
    print("\n" + "=" * 60)
    print("7. Lint the Codex (governance check)")
    print("=" * 60)
    import subprocess
    r = subprocess.run(
        ["howdex", "codex", "lint", str(codex_path)],
        capture_output=True, text=True,
    )
    print(f"  exit code: {r.returncode}")
    print(r.stdout.strip())
    if r.returncode == 0:
        print("\n  ✓ The published Codex entry passes governance lint.")
        print("    The full Howdex loop is working: trace -> learn -> verify -> publish -> lint.")

    mem.close()
    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)
    print(f"  Memory DB:    {db_path}")
    print(f"  Codex folder: {codex_path}")
    print(f"\nInspect the published entry:")
    print(f"  cat {entry_path}")
    print(f"\nSearch the Codex from the CLI:")
    print(f"  howdex codex search --query 'fix missing node module' --max-results 3 {codex_path}")


if __name__ == "__main__":
    main()
