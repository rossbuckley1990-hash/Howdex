from howdex import Howdex
from pathlib import Path
import shutil
import os
import random

demo_dir = Path.home() / ".howdex-real-agent-demo"

if demo_dir.exists():
    shutil.rmtree(demo_dir)

demo_dir.mkdir(parents=True, exist_ok=True)

db_path = demo_dir / "howdex.db"
env_file = demo_dir / ".env.production"

mem = Howdex(path=str(db_path))


class TinyDeployAgent:
    def __init__(self, memory: Howdex):
        self.memory = memory
        self.task = "deploy api to production"

    def ask_howdex_before_acting(self):
        print("\n🧠 Agent asks Howdex before acting:")
        print("   'What should I remember before I deploy api to production?'")

        results = self.memory.recall(
            "safe deploy api production DATABASE_URL previous failures procedure",
            top_k=5,
            min_score=0.0,
        )

        if not results:
            print("   Howdex has no useful memory yet.")
        else:
            for r in results:
                content = r.memory.content.replace("\n", " ")
                print(f"   [{r.score:.3f}] {content[:160]}")

        procedure = self.memory.get_procedure(self.task)

        if procedure:
            print("\n   ✅ Howdex found learned procedure:")
            for i, step in enumerate(procedure.steps, start=1):
                action = step.get("action", step)
                print(f"      {i}. {action}")
        else:
            print("\n   No learned procedure yet.")

        return procedure, results

    def run_tests(self):
        return "passed"

    def check_database_url(self):
        if not env_file.exists():
            return "missing"

        text = env_file.read_text()
        if "DATABASE_URL=" in text:
            return "present"

        return "missing"

    def build_docker_image(self):
        return "passed"

    def deploy_service(self):
        db_status = self.check_database_url()

        if db_status != "present":
            return "failed: DATABASE_URL missing"

        return "success"

    def choose_actions(self, procedure, memories):
        """
        This is the agent policy.

        First run:
          no memory/procedure exists, so it uses naive deploy actions.

        Later runs:
          if Howdex remembers DATABASE_URL failure or has a procedure,
          it checks DATABASE_URL before deploying.
        """

        remembered_database_failure = any(
            "DATABASE_URL" in r.memory.content and "fail" in r.memory.content.lower()
            for r in memories
        )

        if procedure:
            return [step.get("action", step) for step in procedure.steps]

        if remembered_database_failure:
            return [
                "run tests",
                "check DATABASE_URL",
                "build docker image",
                "deploy service",
            ]

        return [
            "run tests",
            "build docker image",
            "deploy service",
        ]

    def run(self, attempt_name):
        print("\n" + "=" * 68)
        print(f"🚀 {attempt_name}: Real agent attempting production deploy")
        print("=" * 68)

        procedure, memories = self.ask_howdex_before_acting()
        actions = self.choose_actions(procedure, memories)

        print("\n🤖 Agent chosen action plan:")
        for i, action in enumerate(actions, start=1):
            print(f"   {i}. {action}")

        self.memory.start_session(self.task)

        outcome = "success"
        error = None
        observations = []

        print("\n⚙️ Agent executing actions:")

        for action in actions:
            if action == "run tests":
                observation = self.run_tests()

            elif action == "check DATABASE_URL":
                observation = self.check_database_url()

                if observation == "missing":
                    outcome = "failure"
                    error = "blocked unsafe deploy because DATABASE_URL missing"
                    print(f"   - {action} → {observation}")
                    self.memory.log_step(action, observation)
                    observations.append((action, observation))
                    break

            elif action == "build docker image":
                observation = self.build_docker_image()

            elif action == "deploy service":
                observation = self.deploy_service()

                if observation != "success":
                    outcome = "failure"
                    error = observation

            else:
                observation = "skipped: unknown action"

            print(f"   - {action} → {observation}")
            self.memory.log_step(action, observation)
            observations.append((action, observation))

            if outcome == "failure":
                break

        self.memory.end_session(outcome, error=error)

        if outcome == "failure":
            self.memory.remember(
                f"Production deploy failed because DATABASE_URL was missing. Error: {error}",
                layer="semantic",
                type="fact",
                importance=0.95,
            )

        if outcome == "success":
            self.memory.remember(
                "Successful production deploy requires: run tests, check DATABASE_URL, build docker image, deploy service.",
                layer="semantic",
                type="fact",
                importance=0.9,
            )

        print(f"\n📌 Outcome: {outcome.upper()}")
        if error:
            print(f"   Error: {error}")

        print("\n🧠 Triggering Howdex learning...")
        procedures = self.memory.learn(min_samples=2)

        if procedures:
            for p in procedures:
                print(f"   Learned/updated procedure: {p.task_signature}")
                print(f"   Success rate: {p.success_rate:.0%}")
                print(f"   Evidence: {p.sample_count} attempts")
                print("   Steps:")
                for i, step in enumerate(p.steps, start=1):
                    action = step.get("action", step)
                    print(f"      {i}. {action}")
        else:
            print("   Not enough evidence to learn a procedure yet.")

        return outcome


print("\n🧠 Howdex Real Agent Demo")
print("========================")
print("This is no longer manually inserting sessions.")
print("A tiny agent asks Howdex, chooses actions, executes them, records outcomes, and learns.\n")

agent = TinyDeployAgent(mem)

print("Environment state:")
print(f"   DATABASE_URL file exists? {env_file.exists()}")

agent.run("Attempt 1")

agent.run("Attempt 2")

print("\n🛠️ Human/operator fixes environment by adding DATABASE_URL.")
env_file.write_text("DATABASE_URL=postgres://user:pass@localhost:5432/app\n")

print(f"   DATABASE_URL file exists? {env_file.exists()}")

agent.run("Attempt 3")

print("\n" + "=" * 68)
print("FINAL PROOF")
print("=" * 68)

proc = mem.get_procedure("deploy api to production")

if proc:
    print("\n✅ The agent now has learned deploy muscle memory:")
    for i, step in enumerate(proc.steps, start=1):
        action = step.get("action", step)
        print(f"   {i}. {action}")

print("\nDatabase stats:")
stats = mem.stats()
for key, value in stats.items():
    print(f"   {key}: {value}")

print("\n🔥 Demo line:")
print("   This is a real agent loop: recall → act → observe → remember → learn → improve.")
