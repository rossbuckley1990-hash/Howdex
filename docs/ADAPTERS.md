# Howdex Framework Adapters

Howdex is the open verification layer for agent know-how. It turns execution
traces into portable, receipt-backed procedures that any agent can reuse and
any enterprise can audit.

Howdex adapters let existing agent workflows use procedural memory without
manual calls to `start_session()`, `log_step()`, `learn()`, and `guidance()` at
every call site.

Adapters are optional. Importing them does not require LangGraph, LangChain,
OpenAI, network access, or a hosted service. Howdex stays local-first and uses
your local SQLite database.

Adapters do not make Howdex model-bound. They let different frameworks record
the same trace/procedure/receipt lifecycle while keeping source artifacts
excluded by default and candidate procedures clearly labelled.

## OpenAI Agents SDK

The OpenAI Agents adapter keeps Howdex vendor-neutral. It does not import
`openai` or the Agents SDK at module import time, and the core lifecycle works
with plain Python callables.

```python
from howdex import Howdex
from howdex.adapters.openai_agents import HowdexOpenAIAgentsAdapter

memory = Howdex(path="~/.howdex/howdex.db", embedder="hashing")
howdex = HowdexOpenAIAgentsAdapter(
    memory,
    verified_only=True,
    include_source=False,
    max_chars=4000,
)

instructions = howdex.instructions(
    "Recover Docker Compose health endpoint",
    constraints=["Stay inside the sandbox", "Verify with /health"],
    environment={"docker": "local"},
)
```

Pass `instructions` into your agent instructions/system prompt, then wrap tool
calls with the task lifecycle:

```python
session_id = howdex.start_task(
    "Recover Docker Compose health endpoint",
    metadata={"runtime": "openai-agents"},
)

try:
    observation = run_tool("bash", {"cmd": "cat runtime.env"})
    howdex.record_tool_call(
        "bash",
        {"cmd": "cat runtime.env"},
        observation,
        status="success",
    )
finally:
    learned = howdex.end_task(outcome="success", learn=True)
```

For runtimes that accept ordinary Python functions, use `as_tools()`:

```python
tools = howdex.as_tools()

tools["howdex_guidance"]("Recover Docker Compose health endpoint")
tools["howdex_remember"]("Verifier requires HTTP 200 from /health.")
tools["howdex_learn"](min_samples=1)
```

If you want Agents SDK `function_tool` objects, call `tools()` only in the live
runtime where the optional SDK is installed:

```python
sdk_tools = howdex.tools()
```

`include_source=False` is the default and should remain off unless the current
workflow is explicitly allowed to receive source artifacts. Use
`verified_only=True` when you want Codex-backed guidance restricted to
procedures with inspectable verification receipts; Howdex will not label
candidate procedures as verified without receipts.

## Framework-neutral integration

Use `howdex_task`, `howdex_tool`, or `HowdexMiddleware` when you have a plain
Python agent loop and do not want any framework dependency.

```python
from howdex import Howdex
from howdex.adapters.generic import howdex_task, howdex_tool

memory = Howdex(path="~/.howdex/howdex.db", embedder="hashing")

@howdex_tool(memory, name="bash")
def bash(cmd): ...

@howdex_task(memory, objective="Recover Docker health", learn=True)
def agent_loop():
    return bash("curl -sS -i http://127.0.0.1:52617/health")
```

Decorator usage:

```python
from pathlib import Path

@howdex_tool(memory, name="filesystem.read_file")
def read_file(path):
    return Path(path).read_text()

@howdex_task(memory, objective=lambda path: f"Inspect {path}", learn=True)
def inspect_config(path):
    return read_file(path)
```

Middleware usage:

```python
from howdex.adapters.generic import HowdexMiddleware

howdex = HowdexMiddleware(memory, include_source=False, verified_only=True)
guidance = howdex.before_task(
    "Recover Docker Compose health endpoint",
    constraints=["Stay inside the sandbox"],
    environment={"docker": "local"},
)
try:
    observation = run_tool("bash", {"cmd": "cat runtime.env"})
    howdex.after_tool("bash", {"cmd": "cat runtime.env"}, observation, "success")
    learned = howdex.after_task("success", learn=True)
except Exception as exc:
    howdex.after_task("failure", error=str(exc), learn=True)
    raise
```

Nested decorated tasks are isolated: the child task gets its own Howdex session,
then the parent session is restored before the parent continues.

## CrewAI

Use `HowdexCrewAIAdapter` around Crew kickoff and task callbacks. The adapter
does not import CrewAI, so it can be used from callbacks, custom memory flows,
or plain test harnesses.

```python
from howdex import Howdex
from howdex.adapters.crewai import HowdexCrewAIAdapter

memory = Howdex(path="~/.howdex/howdex.db", embedder="hashing")
howdex = HowdexCrewAIAdapter(
    memory,
    verified_only=False,
    include_source=False,
)

guidance = howdex.before_kickoff(
    "Recover Docker Compose health endpoint",
    constraints=["Stay inside the sandbox", "Verify /health before success"],
    environment={"docker": "local"},
)

session_id = howdex.start_task(
    "Recover Docker Compose health endpoint",
    metadata={"crew": "ops-recovery"},
)

howdex.record_step(
    "ops_agent",
    "cat runtime.env",
    "HEALTH_MODE=degraded",
)
howdex.record_step(
    "ops_agent",
    "curl -sS -i http://127.0.0.1:52617/health",
    "SUCCESS: HTTP 200 body=healthy",
)

learned = howdex.after_kickoff(outcome="success", learn=True)
```

For custom CrewAI memory integrations, `memory_bridge()` returns plain methods
that can be wired into your own task or callback layer:

```python
bridge = howdex.memory_bridge()
bridge["guidance"]("Recover Docker Compose health endpoint")
```

## AutoGen

Use `HowdexAutoGenAdapter.system_message()` to build the assistant/system
message and record conversation/tool evidence as the task proceeds.

```python
from howdex import Howdex
from howdex.adapters.autogen import HowdexAutoGenAdapter

memory = Howdex(path="~/.howdex/howdex.db", embedder="hashing")
howdex = HowdexAutoGenAdapter(
    memory,
    verified_only=True,
    include_source=False,
)

system_message = howdex.system_message(
    "Recover Docker Compose health endpoint",
    constraints=["Use approved local tools only"],
    environment={"docker": "local"},
)

session_id = howdex.start_conversation_task(
    "Recover Docker Compose health endpoint",
    metadata={"runtime": "autogen"},
)

howdex.record_message(
    "assistant",
    "Inspect runtime configuration before changing files.",
)
howdex.record_tool_call(
    "bash",
    {"cmd": "cat runtime.env"},
    "HEALTH_MODE=degraded",
)
howdex.record_tool_call(
    "bash",
    {"cmd": "curl -sS -i http://127.0.0.1:52617/health"},
    "SUCCESS: HTTP 200 body=healthy",
)

learned = howdex.end_conversation_task(outcome="success", learn=True)
```

## Publishing learned procedures to Codex

Adapters learn into the normal local Howdex store. After a successful run, use
the core Codex publisher to create candidate or receipt-backed Codex entries:

```python
learned = howdex.after_kickoff(outcome="success", learn=True)
published = memory.publish_codex("./codex")
```

Unverified learned procedures publish as candidates. A procedure is marked
verified only when it has an attached inspectable receipt.

## LangGraph

```python
from howdex import Howdex
from howdex.adapters.langgraph import HowdexLangGraphAdapter

memory = Howdex(path="~/.howdex/howdex.db", embedder="hashing")
howdex = HowdexLangGraphAdapter(
    memory,
    max_chars=4000,
    verified_only=False,
)


def worker_node(state):
    # state["howdex_guidance"] is available here.
    ...
    return state


worker_node = howdex.middleware(worker_node)
```

For explicit lifecycle wiring:

```python
state = {"objective": "Recover Docker Compose health endpoint"}
state = howdex.start_task(state)
state = howdex.before_node(state)

# After each tool call:
state = howdex.after_tool_call(
    state,
    "bash",
    {"cmd": "cat runtime.env"},
    "HEALTH_MODE=degraded",
)

state = howdex.end_task(state, outcome="success")
print(state["howdex_learned_procedures"])
```

`before_node()` returns a copy of the state with `howdex_guidance` added. It
does not mutate unrelated state fields.

## LangChain

Use `HowdexMemory` as a LangChain-style memory/context provider:

```python
from howdex import Howdex
from howdex.adapters.langchain import HowdexMemory

memory = Howdex(path="~/.howdex/howdex.db", embedder="hashing")
howdex_memory = HowdexMemory(
    memory,
    max_chars=4000,
    verified_only=True,
)

variables = howdex_memory.load_memory_variables(
    {"input": "Recover Docker Compose health endpoint"}
)
print(variables["howdex_guidance"])

howdex_memory.save_context(
    {"input": "Recover Docker Compose health endpoint"},
    {"output": "HTTP verifier passed", "status": "success"},
)
howdex_memory.clear()
```

The existing tool helper remains available:

```python
from howdex.adapters.langchain import create_howdex_tools

tools = create_howdex_tools(memory)
```

`create_howdex_tools()` lazily imports `langchain_core.tools` only when called.
If LangChain is not installed, importing `howdex.adapters.langchain` still
works.

## Local-first defaults

- Use `Howdex(path="~/.howdex/howdex.db")` or another local SQLite path.
- Use `embedder="hashing"` for deterministic offline operation.
- No adapter makes network calls.
- No adapter requires OpenAI, CrewAI, AutoGen, LangGraph, LangChain, or any
  other framework at import time.

## Source artifacts

Source artifacts are off by default:

```python
HowdexOpenAIAgentsAdapter(memory, include_source=False)
HowdexCrewAIAdapter(memory, include_source=False)
HowdexAutoGenAdapter(memory, include_source=False)
HowdexMiddleware(memory, include_source=False)
HowdexLangGraphAdapter(memory, include_source=False)
HowdexMemory(memory, include_source=False)
```

Only set `include_source=True` when the current workflow is explicitly allowed
to receive source artifacts.

## Verified-only guidance

To restrict guidance to independently verified procedures:

```python
HowdexOpenAIAgentsAdapter(memory, verified_only=True)
HowdexCrewAIAdapter(memory, verified_only=True)
HowdexAutoGenAdapter(memory, verified_only=True)
HowdexMiddleware(memory, verified_only=True)
HowdexLangGraphAdapter(memory, verified_only=True)
HowdexMemory(memory, verified_only=True)
```

Candidate procedures are still stored and learnable, but they are filtered from
adapter guidance when `verified_only=True`. Howdex never promotes a candidate
procedure to verified without an inspectable receipt.
