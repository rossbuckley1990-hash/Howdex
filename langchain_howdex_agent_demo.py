import os
import shutil
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from howdex import Howdex


MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

demo_dir = Path.home() / ".howdex-langchain-agent-demo"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

db_path = demo_dir / "howdex.db"
env_file = demo_dir / ".env.production"
migration_file = demo_dir / "migration.sql"

mem = Howdex(path=str(db_path))

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

    return "\n".join(lines)


@tool
def inspect_howdex() -> str:
    """Inspect Howdex memory before planning deployment."""
    return howdex_context()


@tool
def run_tests() -> str:
    """Run the test suite before deployment."""
    return "passed"


@tool
def check_DATABASE_URL() -> str:
    """Check whether DATABASE_URL is available in the production environment."""
    if not env_file.exists():
        return "missing"
    text = env_file.read_text()
    return "present" if "DATABASE_URL=" in text else "missing"


@tool
def check_migration_file() -> str:
    """Check whether the database migration file exists."""
    if not migration_file.exists():
        return "missing"
    text = migration_file.read_text().strip()
    return "present" if text else "empty"


@tool
def build_docker_image() -> str:
    """Build the Docker image for the API service."""
    return "passed"


@tool
def run_database_migration() -> str:
    """Run the database migration."""
    if check_DATABASE_URL.invoke({}) != "present":
        return "failed: DATABASE_URL missing"
    if check_migration_file.invoke({}) != "present":
        return "failed: migration file missing"
    return "success"


@tool
def deploy_service() -> str:
    """Deploy the API service."""
    if check_DATABASE_URL.invoke({}) != "present":
        return "failed: DATABASE_URL missing"
    if check_migration_file.invoke({}) != "present":
        return "failed: migration was not prepared"
    return "success"


tools = [
    inspect_howdex,
    run_tests,
    check_DATABASE_URL,
    check_migration_file,
    build_docker_image,
    run_database_migration,
    deploy_service,
]

llm = ChatOpenAI(model=MODEL, temperature=0)

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=f"""
You are a cautious production deployment agent.

You are using LangChain as the agent framework.

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
)


def run_agent_attempt(attempt_name: str):
    print("\n" + "=" * 86)
    print(f"🚀 {attempt_name}: LangChain agent attempting deployment")
    print("=" * 86)

    mem.start_session(TASK)

    outcome = "failure"
    error = None

    response = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"Deploy the API to production with database migration. Attempt: {attempt_name}",
                }
            ]
        }
    )

    messages = response.get("messages", [])

    print("\nLangChain messages/tool trace:")

    for msg in messages:
        msg_type = getattr(msg, "type", msg.__class__.__name__)
        name = getattr(msg, "name", None)
        content = getattr(msg, "content", "")

        if msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", []) or []
            if tool_calls:
                print("   AI requested tools:")
                for call in tool_calls:
                    print(f"      - {call.get('name')}")
            elif content:
                print(f"   AI final: {content}")

        elif msg_type == "tool":
            print(f"   Tool result: {name} → {content}")
            mem.log_step(name or "tool", str(content))

            if name == "check_DATABASE_URL" and content == "missing":
                outcome = "failure"
                error = "DATABASE_URL missing"

            elif name == "check_migration_file" and content in {"missing", "empty"}:
                outcome = "failure"
                error = "migration file missing"

            elif name == "deploy_service" and content == "success":
                outcome = "success"
                error = None

            elif isinstance(content, str) and content.startswith("failed"):
                outcome = "failure"
                error = content

    mem.end_session(outcome, error=error)

    if outcome == "failure":
        mem.remember(
            f"LangChain deployment attempt failed. Error: {error}.",
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
            "Successful LangChain deployment procedure: check_DATABASE_URL, check_migration_file, run_database_migration, deploy_service.",
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


print("\n🧠 Howdex + LangChain Agent Framework Demo")
print("=========================================")
print(f"Model: {MODEL}")
print("This uses LangChain create_agent with real tools and Howdex memory.\n")

print("Initial environment:")
print(f"   DATABASE_URL exists?   {env_file.exists()}")
print(f"   migration.sql exists?  {migration_file.exists()}")

run_agent_attempt("Attempt 1")
run_agent_attempt("Attempt 2")

print("\n🛠️ Human/operator adds DATABASE_URL, but forgets migration.sql.")
env_file.write_text("DATABASE_URL=postgres://user:pass@localhost:5432/app\n")
print(f"   DATABASE_URL exists?   {env_file.exists()}")
print(f"   migration.sql exists?  {migration_file.exists()}")

run_agent_attempt("Attempt 3")

print("\n🛠️ Human/operator adds migration.sql.")
migration_file.write_text("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP;\n")
print(f"   DATABASE_URL exists?   {env_file.exists()}")
print(f"   migration.sql exists?  {migration_file.exists()}")

run_agent_attempt("Attempt 4")
run_agent_attempt("Attempt 5")
run_agent_attempt("Attempt 6")

print("\n" + "=" * 86)
print("FINAL PROOF")
print("=" * 86)

proc = mem.get_procedure(TASK)

if proc and proc.steps:
    print("\n✅ Howdex learned a LangChain-agent deployment procedure:")
    for i, step in enumerate(proc.steps, start=1):
        action = step.get("action", step) if isinstance(step, dict) else step
        print(f"   {i}. {action}")
elif proc:
    print("\n⚠️ Howdex created a procedure, but the steps are not stable yet.")
else:
    print("\n❌ No learned procedure found.")

print("\nDatabase stats:")
stats = mem.stats()
for key, value in stats.items():
    print(f"   {key}: {value}")

print("\n🔥 Demo line:")
print("   This is Howdex inside LangChain:")
print("   LangChain agent calls tools → Howdex remembers → Howdex learns → future attempts improve.")
