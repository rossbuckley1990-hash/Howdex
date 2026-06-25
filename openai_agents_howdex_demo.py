import os
import shutil
from pathlib import Path

from agents import Agent, Runner, function_tool

from howdex import Howdex


MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

demo_dir = Path.home() / ".howdex-openai-agents-demo"

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


@function_tool
def inspect_howdex() -> str:
    """Inspect Howdex memory before planning deployment."""
    return howdex_context()


@function_tool
def run_tests() -> str:
    """Run the test suite before deployment."""
    return "passed"


@function_tool
def check_DATABASE_URL() -> str:
    """Check whether DATABASE_URL is available in the production environment."""
    if not env_file.exists():
        return "missing"
    text = env_file.read_text()
    return "present" if "DATABASE_URL=" in text else "missing"


@function_tool
def check_migration_file() -> str:
    """Check whether the database migration file exists."""
    if not migration_file.exists():
        return "missing"
    text = migration_file.read_text().strip()
    return "present" if text else "empty"


@function_tool
def build_docker_image() -> str:
    """Build the Docker image for the API service."""
    return "passed"


@function_tool
def run_database_migration() -> str:
    """Run the database migration."""
    if not env_file.exists() or "DATABASE_URL=" not in env_file.read_text():
        return "failed: DATABASE_URL missing"
    if not migration_file.exists() or not migration_file.read_text().strip():
        return "failed: migration file missing"
    return "success"


@function_tool
def deploy_service() -> str:
    """Deploy the API service."""
    if not env_file.exists() or "DATABASE_URL=" not in env_file.read_text():
        return "failed: DATABASE_URL missing"
    if not migration_file.exists() or not migration_file.read_text().strip():
        return "failed: migration was not prepared"
    return "success"


agent = Agent(
    name="HowdexDeploymentAgent",
    model=MODEL,
    instructions=f"""
You are a cautious production deployment agent.

You are using the OpenAI Agents SDK.

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
    tools=[
        inspect_howdex,
        run_tests,
        check_DATABASE_URL,
        check_migration_file,
        build_docker_image,
        run_database_migration,
        deploy_service,
    ],
)


def extract_tool_trace(result):
    trace = []

    new_items = getattr(result, "new_items", []) or []

    for item in new_items:
        raw = getattr(item, "raw_item", None)
        name = getattr(raw, "name", None) or getattr(item, "name", None)
        output = getattr(raw, "output", None) or getattr(item, "output", None)
        item_type = getattr(item, "type", None) or item.__class__.__name__

        if name or output:
            trace.append(
                {
                    "type": str(item_type),
                    "name": str(name) if name else "unknown",
                    "output": str(output) if output is not None else "",
                }
            )

    return trace


def run_agent_attempt(attempt_name: str):
    print("\n" + "=" * 90)
    print(f"🚀 {attempt_name}: OpenAI Agents SDK attempting deployment")
    print("=" * 90)

    mem.start_session(TASK)

    outcome = "failure"
    error = None

    result = Runner.run_sync(
        agent,
        f"Deploy the API to production with database migration. Attempt: {attempt_name}",
    )

    print("\nAgent final output:")
    print(f"   {result.final_output}")

    trace = extract_tool_trace(result)

    print("\nTool trace:")
    if not trace:
        print("   Could not extract detailed tool trace from SDK result; recording final output only.")
        mem.log_step("agent_final_output", str(result.final_output))
    else:
        for t in trace:
            name = t["name"]
            output = t["output"]
            print(f"   {name} → {output}")
            mem.log_step(name, output)

            if name == "check_DATABASE_URL" and output == "missing":
                outcome = "failure"
                error = "DATABASE_URL missing"

            elif name == "check_migration_file" and output in {"missing", "empty"}:
                outcome = "failure"
                error = "migration file missing"

            elif name == "deploy_service" and output == "success":
                outcome = "success"
                error = None

            elif output.startswith("failed"):
                outcome = "failure"
                error = output

    final_text = str(result.final_output).lower()

    if "successfully deployed" in final_text or "deployment succeeded" in final_text:
        outcome = "success"
        error = None
    elif "database_url" in final_text and "missing" in final_text:
        outcome = "failure"
        error = "DATABASE_URL missing"
    elif "migration" in final_text and "missing" in final_text:
        outcome = "failure"
        error = "migration file missing"

    mem.end_session(outcome, error=error)

    if outcome == "failure":
        mem.remember(
            f"OpenAI Agents SDK deployment attempt failed. Error: {error}.",
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
            "Successful OpenAI Agents SDK deployment procedure: check_DATABASE_URL, check_migration_file, run_database_migration, deploy_service.",
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


print("\n🧠 Howdex + OpenAI Agents SDK Demo")
print("==================================")
print(f"Model: {MODEL}")
print("This uses OpenAI Agents SDK with function tools and Howdex memory.\n")

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

print("\n" + "=" * 90)
print("FINAL PROOF")
print("=" * 90)

proc = mem.get_procedure(TASK)

if proc and proc.steps:
    print("\n✅ Howdex learned an OpenAI-Agents-SDK deployment procedure:")
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
print("   This is Howdex inside OpenAI Agents SDK:")
print("   Agent uses function tools → Howdex remembers → Howdex learns → future attempts improve.")
