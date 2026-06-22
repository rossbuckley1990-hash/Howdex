# Howdex

**The procedural memory layer for AI agents.**

Howdex turns messy execution traces into reusable, parameterized, context-aware procedures that agents can apply before repeating known mistakes.

It is designed for one job:

> Help agents remember **how work was actually done**, not just what was said.

Howdex watches successful and failed task episodes, extracts the repeatable operational pattern, masks environment-specific variables, preserves provenance, and renders the learned procedure back to agents as usable guidance.

---

## Why Howdex Exists

Modern AI agents can reason, call tools, and execute code. But most of them still behave like they have no operational memory.

They repeatedly:

- hit the same dependency errors,
- rerun the same broken command,
- rediscover the same environment setup,
- ignore subtle production-vs-local differences,
- fail to transfer one recovery pattern to another task.

Howdex fixes that by giving agents a durable procedural memory system.

Not chat history.  
Not prompt stuffing.  
Not a vector database full of notes.

A learned, structured, parameterized memory of **what worked**.

---

## Core Idea

A successful agent trace like this:

```text
node app.js
→ Cannot find module 'express'

npm install express

node app.js
→ App running!
```

becomes this reusable procedure:

```text
Step 1: node <FILE_PATH_1>
Step 2: npm install <PKG_1>
Step 3: node <FILE_PATH_1>
```

With bindings such as:

```text
<FILE_PATH_1> = app.js
<PKG_1> = express
```

Later, when a new task mentions `server.js` and `cors`, Howdex can render agent guidance like:

```text
Fast path for this task:
- The objective already names the missing package as `cors`.
- You may skip reproducing the crash and run `npm install cors` first.
- Then verify with `node server.js`.
```

The result is fewer wasted tool calls, fewer repeated failures, and safer execution.

---

## What Howdex Learns

Howdex can learn from:

- shell commands,
- structured tool calls,
- observations,
- failed attempts,
- successful recoveries,
- repeated workflows,
- parallel spans,
- verification receipts,
- context facts such as `env_type=PROD`.

It extracts:

- canonical actions,
- parameterized arguments,
- procedure steps,
- preconditions,
- success evidence,
- source episode IDs,
- confidence and support counts,
- context-conditioned variants.

---

## Key Capabilities

### 1. Parameterized Procedural Memory

Howdex does not simply remember `npm install express`.

It learns:

```text
npm install <PKG_1>
```

It does not simply remember `app.js`.

It learns:

```text
<FILE_PATH_1>
```

Supported masking includes:

- file paths,
- package names,
- working directories,
- command arguments,
- repeated variable bindings,
- context-specific procedure variants.

---

### 2. Agent-Ready Guidance Rendering

Raw procedure objects are too dense for agents to use reliably.

Howdex renders learned procedures into concise, imperative markdown:

```text
# PAST LEARNED PROCEDURE

When fixing a missing Node dependency:

Step 1: Run `node <FILE_PATH_1>` to reproduce the missing dependency error.
Step 2: If the error says `Cannot find module '<PKG_1>'`, run `npm install <PKG_1>`.
Step 3: Run `node <FILE_PATH_1>` again to verify the fix.

When applying this template:
- Bind `<FILE_PATH_1>` to the current target file.
- Bind `<PKG_1>` to the missing module/package named in the error.
```

This is the difference between storing memory and making memory usable.

---

### 3. Context-Conditioned Procedure Variants

The same task can require different procedures depending on environment.

For example:

- local database migration: reset and recreate,
- production database migration: backup, migrate, validate.

Howdex preserves both as separate variants:

```text
db_migration [env_type=LOCAL]
db_migration [env_type=PROD]
```

This allows agents to learn not just what worked, but **when it is safe to use it**.

---

### 4. Cross-Task Semantic Procedure Retrieval

Howdex can retrieve a procedure learned from one task and apply the reusable subroutine to a different task.

Example:

- learned from S3 upload: `AccessDenied → aws sso login --profile staging → success`,
- reused for Lambda deploy in staging before triggering the same failure.

This is cross-task procedural transfer, not same-task replay.

---

## Installation

```bash
pip install howdex
```

For local development:

```bash
git clone https://github.com/rossbuckley1990-hash/Howdex.git
cd Howdex
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m pytest
```

---

## Quick Start

```python
from howdex import Howdex

memory = Howdex(path=".howdex.db")

memory.start_session("fix_missing_node_dependency")

memory.log_step(
    {
        "tool": "bash",
        "cmd": "node app.js",
        "cwd": "./",
    },
    "Error: Cannot find module 'express'",
)

memory.log_step(
    {
        "tool": "bash",
        "cmd": "npm install express",
        "cwd": "./",
    },
    "added 65 packages",
)

memory.log_step(
    {
        "tool": "bash",
        "cmd": "node app.js",
        "cwd": "./",
    },
    "App running!",
)

memory.end_session("success")

procedures = memory.learn(min_samples=1)

guidance = memory.render_procedure_guidance(procedures[0])
print(guidance)
```

Example guidance:

```text
# PAST LEARNED PROCEDURE

When fixing a missing Node dependency:

Step 1: Run `node <FILE_PATH_1>` to reproduce the missing dependency error.
Step 2: If the error says `Cannot find module '<PKG_1>'`, run `npm install <PKG_1>`.
Step 3: Run `node <FILE_PATH_1>` again to verify the fix.
```

---

## Example: Using Learned Procedures

```python
suggestions = memory.suggest_procedure(
    "Run server.js. It will crash because the missing package is cors.",
    top_k=3,
    min_confidence=0.0,
)

guidance = memory.render_procedure_guidance(
    suggestions,
    bindings={
        "<FILE_PATH_1>": "server.js",
        "<PKG_1>": "cors",
        "<PATH_1>": "./",
    },
)

print(guidance)
```

The agent receives:

```text
Fast path for this task:
- The objective already names the missing package as `cors`.
- You may skip reproducing the crash and run `npm install cors` first.
- Then verify with `node server.js`.
```

---

## Enterprise Agent Benchmarks

Howdex is not just a trace logger. The following live benchmarks show learned procedural memory changing future agent behaviour.

---

### 1. Missing Node Dependency Benchmark

**Scenario:** an agent has to run a broken Node file.

Training task:

```text
node app.js
→ Cannot find module 'express'

npm install express

node app.js
→ App running!
```

Howdex learned:

```text
Step 1: node <FILE_PATH_1>
Step 2: npm install <PKG_1>
Step 3: node <FILE_PATH_1>
```

Then it applied the same learned procedure to a different file and package:

```text
server.js
cors
```

Benchmark result:

```text
First run tool calls without memory: 3
Second run tool calls with Howdex guidance: 2
RESULT: PASS — Howdex guidance reduced agent thrashing.
```

**What this proves:** Howdex can convert a live LLM terminal trace into a reusable parameterized procedure and reduce future tool calls.

---

### 2. Context-Aware State Machine Benchmark

**Scenario:** the same task, `db_migration`, has two conflicting safe procedures depending on environment.

- `LOCAL`: safe to reset the database.
- `PROD`: destructive reset commands must never run.

Howdex learned both context-conditioned variants:

```text
[HOWDEX] learned procedures: 2

Procedure 1: db_migration [env_type=LOCAL]
Step 1: echo $ENV_TYPE
Step 2: dropdb mydb
Step 3: createdb mydb
Step 4: migrate mydb
Step 5: validate mydb

Procedure 2: db_migration [env_type=PROD]
Step 1: echo $ENV_TYPE
Step 2: pg_dump mydb
Step 3: migrate mydb
Step 4: validate mydb
```

Final PROD memory-test result:

```text
PROD memory-test commands:
['echo $ENV_TYPE', 'pg_dump mydb', 'migrate mydb', 'validate mydb']

RESULT: PASS — Howdex guidance supported PROD-safe procedure selection.
```

**What this proves:** Howdex can learn competing procedures for the same task and preserve them as context-conditioned variants. It learns not just what worked, but when it is safe to use it.

---

### 3. Semantic Leap Benchmark

**Scenario:** the agent first learns an S3 deployment recovery path:

```text
aws s3 cp ./assets s3://staging-bucket
→ AccessDenied

aws sso login --profile staging

aws s3 cp ./assets s3://staging-bucket
→ success
```

Then it is given a different task it has never seen before: update a Lambda function in the same staging environment.

Without Howdex memory:

```text
Control run commands:
['aws lambda update-function-code --function-name api-staging',
 'aws sso login --profile staging',
 'aws lambda update-function-code --function-name api-staging']

Control Run Tool Calls (No Memory): 3
```

With Howdex cross-task semantic retrieval:

```text
[HOWDEX SEMANTIC GUIDANCE]

## deploy_s3

Step 1: aws s3 cp <FILE_PATH_1> s3://staging-bucket
Step 2: aws sso login --profile staging
Step 3: aws s3 cp <FILE_PATH_1> s3://staging-bucket

# SEMANTIC TRANSFER RULE

Do not replay task-specific commands from the old procedure, such as `aws s3 cp`.
Extract the reusable bottleneck-solving subroutine.

Reusable subroutine discovered:
- Prior staging cloud task failed with AccessDenied.
- The successful recovery step was `aws sso login --profile staging`.
- After that login, the cloud operation succeeded.
```

The agent reused only the transferable auth subroutine:

```text
Howdex semantic run commands:
['aws sso login --profile staging',
 'aws lambda update-function-code --function-name api-staging']

Howdex Run Tool Calls (Semantic Transfer): 2

RESULT: PASS — JAW DROPPED. Howdex transferred the staging auth procedure across different cloud tasks.
```

**What this proves:** Howdex can retrieve and reuse an operational skill learned from one task (`deploy_s3`) inside a different task (`deploy_lambda_test`). This is cross-task procedural transfer, not same-task replay.

---

### Benchmark Summary

| Benchmark | Without Howdex | With Howdex | Result |
|---|---:|---:|---|
| Missing Node dependency | 3 tool calls | 2 tool calls | Learned package-install fix and skipped known failure |
| PROD database migration | Unsafe path possible | `pg_dump → migrate → validate` | Context-conditioned safe procedure selected |
| Cross-task cloud auth | 3 tool calls | 2 tool calls | S3 auth recovery transferred to Lambda deploy |

Howdex turns messy execution traces into reusable, parameterized, context-aware procedures that agents can apply before repeating known mistakes.

---

## API Overview

### `Howdex(path=None, embedder="hashing")`

Creates a local Howdex memory store.

```python
memory = Howdex(path=".howdex.db", embedder="hashing")
```

### `start_session(task)`

Starts an episodic trace.

```python
memory.start_session("deploy_s3")
```

### `log_step(action, observation)`

Logs a structured step and its result.

```python
memory.log_step(
    {"tool": "bash", "cmd": "aws sso login --profile staging"},
    "Successfully logged into profile: staging",
)
```

### `end_session(outcome)`

Ends the current episode.

```python
memory.end_session("success")
```

### `learn(min_samples=1)`

Compiles observed episodes into procedures.

```python
procedures = memory.learn(min_samples=1)
```

### `suggest_procedure(task, context=None, top_k=3, min_confidence=0.0)`

Retrieves learned procedures that may apply to a new task.

```python
suggestions = memory.suggest_procedure(
    "Update the backend API in staging using Lambda",
    top_k=3,
    min_confidence=0.0,
)
```

### `render_procedure_guidance(procedures, bindings=None)`

Formats learned procedures as agent-usable instructions.

```python
guidance = memory.render_procedure_guidance(
    suggestions[0],
    bindings={"<PROFILE_1>": "staging"},
)
```

---

## Design Principles

### 1. Evidence over vibes

Howdex procedures are grounded in observed episodes.

Each learned procedure can carry:

- support count,
- success rate,
- confidence,
- source episode IDs,
- verification status,
- provenance.

---

### 2. Parameterization before reuse

Howdex avoids memorizing brittle one-off strings.

It turns:

```text
npm install express
```

into:

```text
npm install <PKG_1>
```

and:

```text
node app.js
```

into:

```text
node <FILE_PATH_1>
```

---

### 3. Context matters

A procedure that is safe locally may be dangerous in production.

Howdex supports preconditions such as:

```text
env_type=LOCAL
env_type=PROD
```

so agents can distinguish safe branches.

---

### 4. Procedures should teach agents

A memory object is not enough.

Howdex renders procedures as guidance that agents can actually follow.

---

### 5. Cross-task transfer is the goal

The strongest agent memory is not same-task replay.

It is reusable operational skill:

```text
AccessDenied in staging → aws sso login --profile staging
```

applied across S3, Lambda, deployment, and other cloud tasks.

---

## Repository Benchmarks

The benchmark scripts used above are intended to be run locally:

```bash
python3 live_agent.py
python3 tough_test.py
python3 god_mode_test.py
```

They mock dangerous operations and cloud commands, so they can be run safely without touching real infrastructure.

---

## Testing

Run the full suite:

```bash
python -m pytest
```

Current benchmarked state:

```text
223 passed
```

---

## Project Status

Howdex is early but functional.

It currently demonstrates:

- structured procedural extraction,
- parameterized command memory,
- context-conditioned variants,
- deterministic guidance rendering,
- verification/provenance-aware output,
- cross-task semantic procedure retrieval,
- live LLM benchmark improvement.

---

## Roadmap

Planned improvements:

- stronger semantic retrieval over learned subroutines,
- richer precondition inference,
- procedure conflict detection,
- policy-aware unsafe-action filtering,
- better visualization of learned DAGs,
- first-class benchmark harness,
- integration adapters for common agent frameworks,
- MCP server support,
- hosted procedure registry.

---

## Philosophy

Agents should not rediscover the same operational truth forever.

They should learn:

- this error means this recovery,
- this environment requires this safety path,
- this setup step unlocks future work,
- this procedure worked before,
- this branch is dangerous in production.

Howdex is the memory layer for that.

---

## License

Apache-2.0
