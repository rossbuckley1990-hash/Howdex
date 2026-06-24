# Howdex pilot tutorial

Shortest local path:

## 1. Install

```bash
python -m venv .venv
PATH="$PWD/.venv/bin:$PATH" python -m pip install -U pip
PATH="$PWD/.venv/bin:$PATH" python -m pip install howdex-ai
```

For repo development:

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pip install -e ".[dev]"
```

## 2. Start MCP

```bash
HOWDEX_EMBEDDER=hash howdex mcp --db ~/.howdex/howdex.db --codex ./codex
```

Connect your MCP-compatible client using the examples in `examples/pilot/`.

## 3. Ask for guidance

In your agent:

```text
Ask Howdex for guidance before starting the task.
```

Or in Python:

```python
from howdex import Howdex

memory = Howdex(path="howdex-pilot.db", embedder="hashing")
print(memory.guidance("Fix the failing local test command"))
```

## 4. Remember a trace

```python
memory.start_session("Fix the failing local test command")
memory.log_step("inspect package.json", "test script was missing")
memory.log_step("patch package.json test script", "added pytest command")
memory.log_step("run pytest", "12 passed")
memory.end_session("success")
```

## 5. Learn

```python
procedures = memory.learn(min_samples=1)
print([procedure.id for procedure in procedures])
```

## 6. Publish a candidate Codex entry

```python
memory.publish_codex("./codex")
```

Without receipts, this is a candidate entry.

## 7. Attach a receipt

```python
procedure = procedures[0]
memory.verify_procedure(
    procedure.id,
    verifier_type="test",
    verifier_command="python -m pytest",
    expected_signal="passed",
    observed_signal="12 passed",
    exit_code=0,
)
```

## 8. Submit feedback

Use:

- `.github/ISSUE_TEMPLATE/pilot_feedback.yml`
- `.github/ISSUE_TEMPLATE/procedure_submission.yml`

Do not include secrets, private source code, customer data, or raw logs with
sensitive content.
