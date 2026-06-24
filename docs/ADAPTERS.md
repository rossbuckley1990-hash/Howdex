# Howdex Framework Adapters

Howdex adapters let existing agent workflows use procedural memory without
manual calls to `start_session()`, `log_step()`, `learn()`, and `guidance()` at
every call site.

Adapters are optional. Importing them does not require LangGraph, LangChain,
OpenAI, network access, or a hosted service. Howdex stays local-first and uses
your local SQLite database.

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
- No adapter requires OpenAI, LangGraph, or LangChain at import time.

## Source artifacts

Source artifacts are off by default:

```python
HowdexOpenAIAgentsAdapter(memory, include_source=False)
HowdexLangGraphAdapter(memory, include_source=False)
HowdexMemory(memory, include_source=False)
```

Only set `include_source=True` when the current workflow is explicitly allowed
to receive source artifacts.

## Verified-only guidance

To restrict guidance to independently verified procedures:

```python
HowdexOpenAIAgentsAdapter(memory, verified_only=True)
HowdexLangGraphAdapter(memory, verified_only=True)
HowdexMemory(memory, verified_only=True)
```

Candidate procedures are still stored and learnable, but they are filtered from
adapter guidance when `verified_only=True`. Howdex never promotes a candidate
procedure to verified without an inspectable receipt.
