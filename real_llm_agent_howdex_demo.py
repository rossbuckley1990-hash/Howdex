import json
import os
import shutil
from pathlib import Path

from benchmark_openai import get_openai_client
from howdex import Howdex


MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

demo_dir = Path.home() / ".howdex-real-llm-agent-demo"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

db_path = demo_dir / "howdex.db"
env_file = demo_dir / ".env.production"
migration_file = demo_dir / "migration.sql"

mem = Howdex(path=str(db_path))
_CLIENT = None


def _openai_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = get_openai_client()
    return _CLIENT


TOOLS = [
    "inspect_previous_memory",
    "run_tests",
    "check_DATABASE_URL",
    "check_migration_file",
    "build_docker_image",
    "run_database_migration",
    "deploy_service",
    "stop",
]


def tool_run_tests():
    return "passed"


def tool_check_database_url():
    if not env_file.exists():
        return "missing"
    text = env_file.read_text()
    return "present" if "DATABASE_URL=" in text else "missing"


def tool_check_migration_file():
    if not migration_file.exists():
        return "missing"
    text = migration_file.read_text().strip()
    return "present" if text else "empty"


def tool_build_docker_image():
    return "passed"


def tool_run_database_migration():
    if tool_check_database_url() != "present":
        return "failed: DATABASE_URL missing"
    if tool_check_migration_file() != "present":
        return "failed: migration file missing"
    return "success"


def tool_deploy_service():
    if tool_check_database_url() != "present":
        return "failed: DATABASE_URL missing"
    if tool_check_migration_file() != "present":
        return "failed: migration was not prepared"
    return "success"


def execute_tool(action):
    if action == "run_tests":
        return tool_run_tests()
    if action == "check_DATABASE_URL":
        return tool_check_database_url()
    if action == "check_migration_file":
        return tool_check_migration_file()
    if action == "build_docker_image":
        return tool_build_docker_image()
    if action == "run_database_migration":
        return tool_run_database_migration()
    if action == "deploy_service":
        return tool_deploy_service()
    if action == "inspect_previous_memory":
        return "memory inspected before planning"
    if action == "stop":
        return "stopped"
    return f"unknown tool: {action}"


def howdex_context(task):
    memories = mem.recall(
        "safe production deployment database url migration previous failure learned procedure",
        top_k=8,
        min_score=0.0,
    )

    proc = mem.get_procedure(task)

    context_lines = []

    if memories:
        context_lines.append("Relevant Howdex memories:")
        for r in memories:
            content = r.memory.content.replace("\n", " ")
            context_lines.append(f"- score={r.score:.3f}: {content[:220]}")
    else:
        context_lines.append("Relevant Howdex memories: none")

    if proc and proc.steps:
        context_lines.append("\nLearned Howdex procedure:")
        for i, step in enumerate(proc.steps, start=1):
            action = step.get("action", step) if isinstance(step, dict) else step
            context_lines.append(f"{i}. {action}")
    elif proc:
        context_lines.append("\nHowdex has a procedure record, but no stable steps yet.")
    else:
        context_lines.append("\nLearned Howdex procedure: none")

    return "\n".join(context_lines)


def ask_llm_for_next_action(task, context, observations):
    prompt = f"""
You are a cautious production deployment agent.

Your job:
{task}

You can choose exactly one next action from this list:
{TOOLS}

Rules:
- Do not invent tools.
- If Howdex contains a learned procedure, prefer following it.
- If previous failures mention DATABASE_URL, check_DATABASE_URL before deploying.
- If previous failures mention migration, check_migration_file before running migration or deployment.
- Never deploy if DATABASE_URL is missing.
- Never deploy if the migration file is missing.
- Stop when the task is complete or safely blocked.

Howdex context:
{context}

Observations so far:
{json.dumps(observations, indent=2)}

Return ONLY valid JSON in this exact format:
{{
  "thought": "brief reason",
  "action": "one tool name from the allowed list"
}}
""".strip()

    response = _openai_client().responses.create(
        model=MODEL,
        input=prompt,
    )

    text = response.output_text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Repair attempt for models that wrap JSON in markdown.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(text[start:end + 1])
        else:
            raise RuntimeError(f"LLM did not return JSON:\n{text}")

    action = data.get("action")
    thought = data.get("thought", "")

    if action not in TOOLS:
        raise RuntimeError(f"LLM chose invalid action: {action}")

    return thought, action


class RealLLMDeployAgent:
    def __init__(self, memory):
        self.memory = memory
        self.task = "deploy api to production with database migration"

    def run(self, attempt_name, max_steps=8):
        print("\n" + "=" * 82)
        print(f"🚀 {attempt_name}: Real LLM agent attempting deployment")
        print("=" * 82)

        observations = []
        self.memory.start_session(self.task)

        outcome = "failure"
        error = None

        for step_num in range(1, max_steps + 1):
            context = howdex_context(self.task)

            thought, action = ask_llm_for_next_action(
                self.task,
                context,
                observations,
            )

            print(f"\nLLM step {step_num}")
            print(f"   Thought: {thought}")
            print(f"   Action:  {action}")

            observation = execute_tool(action)
            print(f"   Result:  {observation}")

            observations.append(
                {
                    "step": step_num,
                    "thought": thought,
                    "action": action,
                    "observation": observation,
                }
            )

            self.memory.log_step(action, observation)

            if action == "deploy_service" and observation == "success":
                outcome = "success"
                error = None
                break

            if "failed" in observation or "missing" in observation:
                outcome = "failure"
                error = observation

                # A cautious agent should stop after a blocking failure.
                if action in {
                    "check_DATABASE_URL",
                    "check_migration_file",
                    "run_database_migration",
                    "deploy_service",
                }:
                    break

            if action == "stop":
                outcome = "stopped"
                error = None
                break

        self.memory.end_session(outcome, error=error)

        if outcome == "failure":
            self.memory.remember(
                f"Deployment attempt failed. Error: {error}. Observations: {observations}",
                layer="semantic",
                type="fact",
                importance=0.95,
            )

        if outcome == "success":
            self.memory.remember(
                "Successful production deployment with migration requires: run tests, check DATABASE_URL, check migration file, build docker image, run database migration, deploy service.",
                layer="semantic",
                type="fact",
                importance=0.97,
            )

        print(f"\n📌 Outcome: {outcome.upper()}")
        if error:
            print(f"   Error: {error}")

        print("\n🧠 Triggering Howdex learning...")
        procedures = self.memory.learn(min_samples=3)

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

        return outcome


print("\n🧠 Howdex + Real LLM Agent Demo")
print("==============================")
print(f"Model: {MODEL}")
print("The LLM chooses actions. Howdex supplies memory. Tools return real local observations.")
print("The agent should stop repeating deployment mistakes.\n")

agent = RealLLMDeployAgent(mem)

print("Initial environment:")
print(f"   DATABASE_URL exists?   {env_file.exists()}")
print(f"   migration.sql exists?  {migration_file.exists()}")

# Attempt 1: missing DATABASE_URL and migration.
agent.run("Attempt 1")

# Attempt 2: still missing both. Agent should remember and block earlier.
agent.run("Attempt 2")

print("\n🛠️ Human/operator adds DATABASE_URL, but forgets migration.sql.")
env_file.write_text("DATABASE_URL=postgres://user:pass@localhost:5432/app\n")
print(f"   DATABASE_URL exists?   {env_file.exists()}")
print(f"   migration.sql exists?  {migration_file.exists()}")

# Attempt 3: DATABASE_URL fixed, migration still missing.
agent.run("Attempt 3")

print("\n🛠️ Human/operator adds migration.sql.")
migration_file.write_text("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP;\n")
print(f"   DATABASE_URL exists?   {env_file.exists()}")
print(f"   migration.sql exists?  {migration_file.exists()}")

# Attempts 4-6: enough successful evidence to learn stable procedure.
agent.run("Attempt 4")
agent.run("Attempt 5")
agent.run("Attempt 6")

print("\n" + "=" * 82)
print("FINAL PROOF")
print("=" * 82)

proc = mem.get_procedure("deploy api to production with database migration")

if proc and proc.steps:
    print("\n✅ Howdex learned an LLM-agent deployment procedure:")
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
print("   This is Howdex inside a real LLM agent loop:")
print("   LLM plans → tools execute → Howdex remembers → Howdex learns → LLM behaves better.")
