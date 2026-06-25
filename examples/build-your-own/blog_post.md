# Build Your Own Agent Memory (in ~200 lines)

Your agent just solved a gnarly task — recovered a broken Docker service, fixed a missing dependency, restarted the API. You watched it read config files, hit dead ends, try the wrong fix, backtrack, and finally land on the solution. Tomorrow, the same class of task comes in. And the agent starts from zero. Re-reads the same files. Repeats the same dead-ends. Burns the same tokens.

Humans don't do this. We abstract a routine once — "when the service won't start, check the config, then the dependencies, then rebuild" — and reuse it. We get faster. Agents don't, because most agent frameworks have no procedural memory: no way to learn *how* they solved something and reuse that routine next time.

This post builds the smallest thing that fixes this — a working procedural memory system in ~200 lines of Python. Then we'll look at what makes it hard, and what a production system (Howdex) actually does differently.

**The runnable code lives at [`examples/build-your-own/agent_memory.py`](https://github.com/rossbuckley1990-hash/Howdex/blob/main/examples/build-your-own/agent_memory.py). Clone it, run it, modify it.**

## The mental model

Every agent needs four kinds of memory:

- **Working memory** — the current context window. What the agent is thinking about right now.
- **Episodic memory** — what happened. Session logs: "I ran X, observed Y, and it failed."
- **Semantic memory** — facts. "The user prefers dark mode." "The API lives at `api.example.com`."
- **Procedural memory** — how to do the work. Reusable routines: "when a dependency is missing, install it, then re-run."

The first three are well-served. Context windows handle working memory. Conversation logs handle episodic. Vector databases (Pinecone, Weaviate) handle semantic. **Procedural memory is the one that turns an agent from "answers questions" into "does the job better over time"** — and it's the least served by existing tools. This is the frame the whole post hangs on.

## Step 1: Log episodes

First, we need to remember what happened. This is a dead-simple episodic store:

```python
class EpisodeStore:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, task TEXT, outcome TEXT,
                steps TEXT, created_at REAL
            )
        """)
        self.conn.commit()
        self._current = None
        self._steps = []

    def start_session(self, task):
        self._current = hashlib.sha256(
            f"{task}:{time.time()}".encode()
        ).hexdigest()[:12]
        self._steps = []
        self._task = task

    def log_step(self, action, observation):
        self._steps.append({"action": action, "observation": observation})

    def end_session(self, outcome):
        self.conn.execute(
            "INSERT INTO episodes VALUES (?,?,?,?,?)",
            (self._current, self._task, outcome,
             json.dumps(self._steps), time.time()),
        )
        self.conn.commit()
```

Run an agent on the same task twice:

```python
store = EpisodeStore()

# First run — agent struggles, finds the fix
store.start_session("fix_missing_dependency")
store.log_step("read package.json", "dependency 'express' listed")
store.log_step("run node app.js", "Error: Cannot find module 'express'")
store.log_step("run npm install express", "added 1 package")
store.log_step("run node app.js", "App running on port 3000")
store.end_session("success")

# Second run — same task, different module
store.start_session("fix_missing_dependency")
store.log_step("read package.json", "dependency 'cors' listed")
store.log_step("run node app.js", "Error: Cannot find module 'cors'")
store.log_step("run npm install cors", "added 1 package")
store.log_step("run node app.js", "App running on port 3000")
store.end_session("success")
```

**Point made:** we now remember what happened. But we're not *learning* anything from it. The next agent still starts cold.

## Step 2: Find the reusable routine

Take multiple *successful* episodes for similar tasks and extract what's common. Normalize each step to a canonical action, then find the shared sub-sequence.

```python
_CANONICAL_MAP = {
    "read": "read_config", "check": "read_config", "inspect": "read_config",
    "run node": "execute_app",
    "run npm install": "install_dependency", "npm install": "install_dependency",
}

def canonicalize(action: str) -> str:
    action_lower = action.lower()
    for keyword, canonical in _CANONICAL_MAP.items():
        if keyword in action_lower:
            return canonical
    return "unknown"

def extract_procedure(episodes, min_samples=2):
    successes = [ep for ep in episodes if ep["outcome"] == "success"]
    if len(successes) < min_samples:
        return None
    canonical_traces = [
        [canonicalize(s["action"]) for s in ep["steps"]]
        for ep in successes
    ]
    common_actions = set.intersection(*[set(t) for t in canonical_traces])
    procedure_steps = [a for a in canonical_traces[0] if a in common_actions]
    return {
        "task": successes[0]["task"],
        "steps": procedure_steps,
        "sample_count": len(successes),
    }
```

Output:

```
Extracted procedure: fix_missing_dependency
  Samples: 2
  Steps: read_config → execute_app → install_dependency → execute_app
```

**Point made:** two messy traces collapsed into one clean procedure. This is procedural memory. This is what the research calls *workflow induction* (see the AWM paper — Agent Workflow Memory — which uses LLM-based extraction to generalize across environments).

## Step 3: Retrieve and inject

Given a new task, retrieve the best-matching procedure and inject its steps into the agent's prompt as guidance:

```python
def retrieve_procedure(procedures, task):
    best, best_score = None, 0
    for proc in procedures:
        task_words = set(task.lower().split())
        proc_words = set(proc["task"].lower().split())
        step_words = set()
        for s in proc.get("steps", []):
            step_words.update(s.lower().split("_"))
        score = len(task_words & (proc_words | step_words))
        if score > best_score:
            best, best_score = proc, score
    return best if best_score > 0 else None

def render_guidance(procedure):
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
    ])
    return "\n".join(lines)
```

Now when the agent gets a new task — "Fix a Node app that cannot find module bcrypt" — it retrieves the procedure and gets:

```
# PROCEDURAL MEMORY

Use this as prior guidance. Verify in the current environment.

Task: fix_missing_dependency
Samples: 2

Recommended steps:
  1. read_config
  2. execute_app
  3. install_dependency
  4. execute_app

Rules:
  - Adapt these steps to the current environment.
  - Do not claim success until a real verifier passes.
```

The agent now has a roadmap. It skips the dead-ends and goes straight to: read config → install the missing dep → verify. **This is the payoff: the agent starts cold but doesn't solve from scratch.**

## Where it gets hard

The 200 lines above work. They also paper over four landmines that separate a toy from a production system.

### 1. Canonicalization

"Read package.json" and "check the manifest" are the same step. Our keyword map catches the easy cases. But what about "look at the dependency file"? "Cat package.json"? "Inspect node_modules"?

A rules-based approach (like ours) is inspectable but brittle — it only catches the patterns you thought of. An LLM-based extractor generalizes better but is harder to audit. The AWM research found that LLM extraction generalizes across environments better than rules. Production systems need both: rules for speed and inspectability, LLM for coverage.

### 2. When NOT to trust a recalled procedure

A procedure that worked once isn't *proven*. Maybe the environment was different. Maybe the agent got lucky. Injecting bad guidance is worse than no guidance — it sends the agent down a wrong path with confidence.

The fix: mark procedures as "candidate" until a **deterministic verifier** (not an LLM) confirms the outcome. A test suite passing. An HTTP 200. An exit code 0. Only then promote to "verified."

An LLM saying "I think it worked" is NOT verification. It's an observation. The distinction is the difference between a toy and a system you'd deploy in production.

### 3. Don't paste the answer

If memory just hands the agent the literal solution — "rename `util.py` to `utils.py`" — you've proven nothing about reuse. The agent might copy-paste a fix that doesn't apply to the new environment.

The fix: guidance must be **operational facts**, not literal code. "The fix involves renaming the module file to match the import in `__init__.py`" — not the literal filename. The agent reconstructs the implementation from the facts, adapting to the current environment. This is harder to get right, but it's what makes the memory *transferable* rather than just a replay.

### 4. And then there's...

- **Segmentation:** one session might contain multiple tasks. How do you split them?
- **Secrets:** tool calls often contain API keys, passwords, tokens. They must be redacted before storage.
- **Latency:** retrieval must be fast (sub-100ms) or the agent loop stalls.
- **Cross-task contamination:** a procedure for "fix a bug" shouldn't surface when the agent is "deploying to production."
- **Context budget:** injecting 5 large procedures into a small model's context window causes "needle in a haystack" collapse.

**The easy 200 lines were the easy part. The trust and abstraction are the actual product.**

## The grown-up version

Everything in the section above is what [Howdex](https://github.com/rossbuckley1990-hash/Howdex) does at production grade:

- **Deterministic + inspectable extraction** — 50+ canonical verbs across execute, transform, validate, and repair intents, not a keyword map
- **Verification layer** — the BootProof gate blocks `learn()` unless a deterministic, non-LLM verifier (exit code, HTTP 200, test pass) confirms the result. An LLM "I think it worked" is explicitly rejected.
- **Receipts** — every verified procedure carries a content-hashed, optionally HMAC-signed receipt. This is the "SSL certificate" of agent governance.
- **Secret redaction** — API keys, tokens, passwords are stripped before storage. Automatically.
- **MCP server** — any agent (Claude Desktop, Cursor, Windsurf) can use it via the Model Context Protocol.
- **Portable** — procedures are JSON, not model weights. They move across models, frameworks, and clouds.
- **Compliance reports** — maps receipts to SOC 2, EU AI Act, and NIST AI RMF control objectives. Audit-ready.
- **Public registry** — verified procedures shared across teams. The network effect is built on verification, not vibes.

```bash
pip install howdex-ai
python examples/first_time_dev.py
```

## Call to action

Clone it, point it at your agent, tell me what procedures it learns.

- **Repo:** [github.com/rossbuckley1990-hash/Howdex](https://github.com/rossbuckley1990-hash/Howdex)
- **Tutorial code:** [`examples/build-your-own/agent_memory.py`](https://github.com/rossbuckley1990-hash/Howdex/blob/main/examples/build-your-own/agent_memory.py)
- **Quickstart:** `python examples/first_time_dev.py` (60-second full loop)
- **Issues & feedback:** [github.com/rossbuckley1990-hash/Howdex/issues](https://github.com/rossbuckley1990-hash/Howdex/issues)

*Further reading: the [Agent Workflow Memory (AWM) paper](https://arxiv.org/abs/2409.07429) for the academic foundation, the [Howdex Verification Receipt Spec](https://github.com/rossbuckley1990-hash/Howdex/blob/main/docs/RECEIPT_SPEC.md) for the production receipt standard, and the [Awesome Agent Memory](https://github.com/rossbuckley1990-hash/awesome-agent-memory) list for the full landscape of agent memory research and systems.*
