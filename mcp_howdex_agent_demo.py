import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from benchmark_openai import get_openai_client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from howdex import Howdex


MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

demo_dir = Path.home() / ".howdex-mcp-agent-demo"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

db_path = demo_dir / "howdex.db"
env_file = demo_dir / ".env.production"
migration_file = demo_dir / "migration.sql"
trace_file = demo_dir / "mcp_tool_trace.log"
context_file = demo_dir / "howdex_context.txt"

mem = Howdex(path=str(db_path))
_CLIENT = None


def _openai_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = get_openai_client()
    return _CLIENT

TASK = "deploy api to production with database migration"


def howdex_context() -> str:
    memories = mem.recall(
        "safe production deployment DATABASE_URL migration previous failure learned procedure",
        top_k=8,
        min_score=0.0,
    )

    proc = mem.get_procedure(TASK)

    lines = []

    if memories:
        lines.append("Relevant Howdex memories:")
        for r in memories:
            content = r.memory.content.replace("\n", " ")
            lines.append(f"- score={r.score:.3f}: {content[:220]}")
    else:
        lines.append("Relevant Howdex memories: none")

    if proc and proc.steps:
        lines.append("\nLearned Howdex procedure:")
        for i, step in enumerate(proc.steps, start=1):
            action = step.get("action", step) if isinstance(step, dict) else step
            lines.append(f"{i}. {action}")
    elif proc:
        lines.append("\nHowdex has a procedure record, but no stable steps yet.")
    else:
        lines.append("\nLearned Howdex procedure: none")

    text = "\n".join(lines)
    context_file.write_text(text)
    return text


def read_clean_trace() -> list[dict[str, str]]:
    if not trace_file.exists():
        return []

    trace = []
    for line in trace_file.read_text().splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            continue
        name, output = line.split("\t", 1)
        trace.append({"name": name, "output": output})
    return trace


def clear_trace():
    trace_file.write_text("")


def mcp_tool_to_openai_tool(tool: Any) -> dict[str, Any]:
    """
    Convert an MCP tool listing into an OpenAI function tool schema.
    The MCP Python SDK exposes tool.inputSchema on current versions.
    """
    input_schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or f"MCP tool: {tool.name}",
            "parameters": input_schema,
        },
    }


def determine_outcome(trace: list[dict[str, str]], final_output: str) -> tuple[str, str | None]:
    outcome = "failure"
    error = None

    for item in trace:
        name = item["name"]
        output = item["output"]

        if name == "check_DATABASE_URL" and output == "missing":
            outcome = "failure"
            error = "DATABASE_URL missing"

        elif name == "check_migration_file" and output in {"missing", "empty"}:
            outcome = "failure"
            error = "migration file missing"

        elif output.startswith("failed"):
            outcome = "failure"
            error = output

        elif name == "deploy_service" and output == "success":
            outcome = "success"
            error = None

    final_text = final_output.lower()

    if "successfully deployed" in final_text or "deployment succeeded" in final_text:
        outcome = "success"
        error = None

    return outcome, error


async def run_openai_mcp_agent(session: ClientSession, tool_schemas: list[dict[str, Any]], attempt_name: str) -> str:
    messages = [
        {
            "role": "system",
            "content": f"""
You are a cautious production deployment agent.

You are using MCP tools discovered from a real MCP server.

Your task is:
{TASK}

Rules:
- Always call inspect_howdex before choosing deployment actions.
- Prefer any learned Howdex procedure if it exists.
- If Howdex or tool results mention DATABASE_URL failures, check_DATABASE_URL before deploying.
- If Howdex or tool results mention migration failures, check_migration_file before migration or deployment.
- Never deploy if DATABASE_URL is missing.
- Never deploy if the migration file is missing.
- Stop when deployment succeeds or when safely blocked.
- Return a short final answer describing the outcome.
""".strip(),
        },
        {
            "role": "user",
            "content": f"Deploy the API to production with database migration. Attempt: {attempt_name}",
        },
    ]

    for _ in range(10):
        response = _openai_client().chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
            temperature=0,
        )

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return msg.content or ""

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args_text = tool_call.function.arguments or "{}"

            try:
                args = json.loads(args_text)
            except json.JSONDecodeError:
                args = {}

            result = await session.call_tool(name, args)

            # MCP result.content is usually a list of TextContent-like items.
            content_parts = []
            for c in result.content:
                text = getattr(c, "text", None)
                if text is not None:
                    content_parts.append(text)
                else:
                    content_parts.append(str(c))

            tool_output = "\n".join(content_parts)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_output,
                }
            )

    return "Stopped after max tool iterations."


async def run_attempt(session: ClientSession, tool_schemas: list[dict[str, Any]], attempt_name: str):
    print("\n" + "=" * 90)
    print(f"🚀 {attempt_name}: MCP agent attempting deployment")
    print("=" * 90)

    clear_trace()
    howdex_context()

    mem.start_session(TASK)

    final_output = await run_openai_mcp_agent(session, tool_schemas, attempt_name)

    print("\nAgent final output:")
    print(f"   {final_output}")

    trace = read_clean_trace()

    print("\nClean MCP tool trace:")
    if not trace:
        print("   ❌ No MCP tools were called.")
    else:
        for item in trace:
            print(f"   {item['name']} → {item['output']}")
            mem.log_step(item["name"], item["output"])

    outcome, error = determine_outcome(trace, final_output)

    mem.end_session(outcome, error=error)

    if outcome == "failure":
        mem.remember(
            f"MCP deployment attempt failed. Error: {error}.",
            layer="semantic",
            type="fact",
            metadata={
                "source": "tool",
                "verified": True,
                "trusted": True,
            },
            importance=0.95,
        )

    if outcome == "success":
        mem.remember(
            "Successful MCP deployment procedure: check_DATABASE_URL, check_migration_file, run_database_migration, deploy_service.",
            layer="semantic",
            type="fact",
            metadata={
                "source": "tool",
                "verified": True,
                "trusted": True,
            },
            importance=0.97,
        )

    print(f"\n📌 Outcome recorded in Howdex: {outcome.upper()}")
    if error:
        print(f"   Error: {error}")

    print("\n🧠 Triggering Howdex learning...")
    procedures = mem.learn(min_samples=3)

    if procedures:
        for p in procedures:
            print(f"   Learned/updated procedure: {p.task_signature}")
            print(f"   Success rate: {p.success_rate:.0%}")
            print(f"   Evidence: {p.sample_count} attempts")
            if p.steps:
                print("   Steps:")
                for i, step in enumerate(p.steps, start=1):
                    action = step.get("action", step) if isinstance(step, dict) else step
                    print(f"      {i}. {action}")
            else:
                print("   Steps: not stable yet")
    else:
        print("   Not enough evidence to learn a procedure yet.")


async def main():
    print("\n🧠 Howdex + MCP Agent Demo")
    print("=========================")
    print(f"Model: {MODEL}")
    print("This uses a real MCP server over stdio, MCP client calls, OpenAI tool selection, and Howdex memory.\n")

    print("Initial environment:")
    print(f"   DATABASE_URL exists?   {env_file.exists()}")
    print(f"   migration.sql exists?  {migration_file.exists()}")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["howdex_mcp_deploy_server.py"],
        env={
            **os.environ,
            "HOWDEX_MCP_DEMO_DIR": str(demo_dir),
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tool_schemas = [mcp_tool_to_openai_tool(t) for t in tools_result.tools]

            print("\nDiscovered MCP tools:")
            for t in tools_result.tools:
                print(f"   - {t.name}")

            await run_attempt(session, tool_schemas, "Attempt 1")
            await run_attempt(session, tool_schemas, "Attempt 2")

            print("\n🛠️ Human/operator adds DATABASE_URL, but forgets migration.sql.")
            env_file.write_text("DATABASE_URL=postgres://user:pass@localhost:5432/app\n")
            print(f"   DATABASE_URL exists?   {env_file.exists()}")
            print(f"   migration.sql exists?  {migration_file.exists()}")

            await run_attempt(session, tool_schemas, "Attempt 3")

            print("\n🛠️ Human/operator adds migration.sql.")
            migration_file.write_text("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP;\n")
            print(f"   DATABASE_URL exists?   {env_file.exists()}")
            print(f"   migration.sql exists?  {migration_file.exists()}")

            await run_attempt(session, tool_schemas, "Attempt 4")
            await run_attempt(session, tool_schemas, "Attempt 5")
            await run_attempt(session, tool_schemas, "Attempt 6")

    print("\n" + "=" * 90)
    print("FINAL PROOF")
    print("=" * 90)

    proc = mem.get_procedure(TASK)

    if proc and proc.steps:
        print("\n✅ Howdex learned a clean MCP-agent deployment procedure:")
        learned = []
        for i, step in enumerate(proc.steps, start=1):
            action = step.get("action", step) if isinstance(step, dict) else step
            learned.append(action)
            print(f"   {i}. {action}")

        if "unknown" in learned:
            print("\n❌ FAIL: Unknown tool names polluted the learned procedure.")
        elif "inspect_howdex" in learned:
            print("\n❌ FAIL: Cognitive memory tool leaked into executable procedure.")
        else:
            print("\n✅ PASS: Procedure contains only real executable MCP task actions.")

    elif proc:
        print("\n⚠️ Howdex created a procedure, but the steps are not stable yet.")
    else:
        print("\n❌ No learned procedure found.")

    print("\nDatabase stats:")
    stats = mem.stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print("\n🔥 Demo line:")
    print("   This is Howdex inside an MCP agent loop:")
    print("   MCP tools execute → Howdex remembers → Howdex learns → future attempts improve.")


if __name__ == "__main__":
    asyncio.run(main())
