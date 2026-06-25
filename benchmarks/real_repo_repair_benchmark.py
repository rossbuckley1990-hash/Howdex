from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

from howdex import Howdex


ROOT = Path.home() / ".howdex-real-repo-repair-benchmark"

if ROOT.exists():
    shutil.rmtree(ROOT)

ROOT.mkdir(parents=True, exist_ok=True)

FIXTURES = ROOT / "fixtures"
RUNS = ROOT / "runs"

FIXTURES.mkdir(parents=True, exist_ok=True)
RUNS.mkdir(parents=True, exist_ok=True)


@dataclass
class RepoCase:
    name: str
    family: str
    missing: str


@dataclass
class RepairResult:
    agent: str
    repo: str
    family: str
    success: bool
    unsafe_failures: int
    repeated_unsafe_failures: int
    actions: list[str]
    first_error: str | None
    final_output: str


def write_file(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def create_repo_fixture(case: RepoCase):
    repo = FIXTURES / case.name

    if repo.exists():
        shutil.rmtree(repo)

    repo.mkdir(parents=True)

    write_file(
        repo / "README.md",
        f"""# {case.name}

A tiny intentionally broken service repo.

Family: {case.family}
Missing: {case.missing}
""",
    )

    write_file(
        repo / "app.py",
        """\
def start():
    return "service started"
""",
    )

    verifier = f"""\
from pathlib import Path
import sys

ROOT = Path(__file__).parent

missing = {case.missing!r}

if missing == "DATABASE_URL":
    env = ROOT / ".env.production"
    if not env.exists() or "DATABASE_URL=" not in env.read_text():
        print("ERROR: DATABASE_URL missing")
        sys.exit(1)

elif missing == "MIGRATION_FILE":
    migration = ROOT / "migration.sql"
    if not migration.exists() or not migration.read_text().strip():
        print("ERROR: migration file missing")
        sys.exit(1)

elif missing == "API_KEY":
    env = ROOT / ".env"
    if not env.exists() or "API_KEY=" not in env.read_text():
        print("ERROR: API_KEY missing")
        sys.exit(1)

print("OK: repository verifies")
sys.exit(0)
"""

    write_file(repo / "verify.py", verifier)

    # Pre-fill some repos with partial state so this is not a one-file toy.
    if case.missing == "MIGRATION_FILE":
        write_file(repo / ".env.production", "DATABASE_URL=postgres://local/test\n")

    if case.missing == "DATABASE_URL":
        write_file(repo / "migration.sql", "CREATE TABLE IF NOT EXISTS users(id INTEGER);\n")


def create_all_fixtures() -> list[RepoCase]:
    cases: list[RepoCase] = []

    # Repeated task family 1: DB env failure.
    for i in range(1, 7):
        cases.append(
            RepoCase(
                name=f"service_db_{i}",
                family="repair python service missing database url",
                missing="DATABASE_URL",
            )
        )

    # Repeated task family 2: API key failure.
    for i in range(1, 7):
        cases.append(
            RepoCase(
                name=f"service_api_{i}",
                family="repair python service missing api key",
                missing="API_KEY",
            )
        )

    # Repeated task family 3: migration failure.
    for i in range(1, 5):
        cases.append(
            RepoCase(
                name=f"service_migration_{i}",
                family="repair python service missing migration file",
                missing="MIGRATION_FILE",
            )
        )

    for case in cases:
        create_repo_fixture(case)

    return cases


def copy_repo(case: RepoCase, agent_name: str) -> Path:
    src = FIXTURES / case.name
    dest = RUNS / agent_name / case.name

    if dest.exists():
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)

    return dest


def run_verify(repo: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        ["python", "verify.py"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )

    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def normalize_error(output: str | None) -> str | None:
    if not output:
        return None

    text = output.lower()

    if "database_url" in text:
        return "DATABASE_URL_missing"

    if "api_key" in text or "api key" in text:
        return "API_KEY_missing"

    if "migration" in text:
        return "MIGRATION_FILE_missing"

    return text.strip() or None


def fix_database_url(repo: Path) -> str:
    write_file(repo / ".env.production", "DATABASE_URL=postgres://local/test\n")
    return "fixed DATABASE_URL"


def fix_api_key(repo: Path) -> str:
    write_file(repo / ".env", "API_KEY=test-key\n")
    return "fixed API_KEY"


def fix_migration_file(repo: Path) -> str:
    write_file(repo / "migration.sql", "CREATE TABLE IF NOT EXISTS users(id INTEGER);\n")
    return "fixed migration file"


def check_database_url(repo: Path) -> str:
    env = repo / ".env.production"
    return "present" if env.exists() and "DATABASE_URL=" in env.read_text() else "missing"


def check_api_key(repo: Path) -> str:
    env = repo / ".env"
    return "present" if env.exists() and "API_KEY=" in env.read_text() else "missing"


def check_migration_file(repo: Path) -> str:
    migration = repo / "migration.sql"
    return "present" if migration.exists() and migration.read_text().strip() else "missing"


class BaseRepairAgent:
    name = "base"

    def repair(self, case: RepoCase) -> RepairResult:
        raise NotImplementedError


class NoMemoryAgent(BaseRepairAgent):
    name = "no_memory"

    def repair(self, case: RepoCase) -> RepairResult:
        repo = copy_repo(case, self.name)
        actions: list[str] = []

        success, output = run_verify(repo)
        actions.append("run_verify")

        unsafe_failures = 0
        first_error = None

        if not success:
            unsafe_failures += 1
            first_error = normalize_error(output)

            if first_error == "DATABASE_URL_missing":
                actions.append("fix_database_url")
                fix_database_url(repo)

            elif first_error == "API_KEY_missing":
                actions.append("fix_api_key")
                fix_api_key(repo)

            elif first_error == "MIGRATION_FILE_missing":
                actions.append("fix_migration_file")
                fix_migration_file(repo)

        success, final_output = run_verify(repo)
        actions.append("run_verify")

        return RepairResult(
            agent=self.name,
            repo=case.name,
            family=case.family,
            success=success,
            unsafe_failures=unsafe_failures,
            repeated_unsafe_failures=0,
            actions=actions,
            first_error=first_error,
            final_output=final_output,
        )


class VectorOnlyAgent(BaseRepairAgent):
    """
    This stores memories as searchable facts, but does not consolidate or execute procedures.
    It can know what happened before, but it still runs the verification command first.
    """

    name = "vector_only"

    def __init__(self):
        self.memory = Howdex(path=str(ROOT / "vector_only.db"))

    def repair(self, case: RepoCase) -> RepairResult:
        repo = copy_repo(case, self.name)
        actions: list[str] = []

        # It searches memory, but it has no procedural executor.
        _ = self.memory.recall(case.family, top_k=5, min_score=0.0)

        success, output = run_verify(repo)
        actions.append("run_verify")

        unsafe_failures = 0
        first_error = None

        if not success:
            unsafe_failures += 1
            first_error = normalize_error(output)

            self.memory.remember(
                f"Repository repair failed in {case.family}: {first_error}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.9,
            )

            if first_error == "DATABASE_URL_missing":
                actions.append("fix_database_url")
                fix_database_url(repo)

            elif first_error == "API_KEY_missing":
                actions.append("fix_api_key")
                fix_api_key(repo)

            elif first_error == "MIGRATION_FILE_missing":
                actions.append("fix_migration_file")
                fix_migration_file(repo)

        success, final_output = run_verify(repo)
        actions.append("run_verify")

        if success:
            self.memory.remember(
                f"Repository repair succeeded in {case.family}. Actions: {actions}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.95,
            )

        return RepairResult(
            agent=self.name,
            repo=case.name,
            family=case.family,
            success=success,
            unsafe_failures=unsafe_failures,
            repeated_unsafe_failures=0,
            actions=actions,
            first_error=first_error,
            final_output=final_output,
        )


class HowdexProceduralAgent(BaseRepairAgent):
    """
    This is the real Howdex benchmark agent.

    It:
    - uses learned procedures if available
    - otherwise does one diagnostic verify
    - records clean repair steps
    - consolidates repeated traces into procedures
    """

    name = "howdex_procedural"

    def __init__(self):
        self.memory = Howdex(path=str(ROOT / "howdex_procedural.db"))

    def learned_plan(self, case: RepoCase) -> list[str] | None:
        proc = self.memory.get_procedure(case.family)

        if not proc or not proc.steps:
            return None

        return [
            step.get("action", step) if isinstance(step, dict) else step
            for step in proc.steps
        ]

    def execute_action(self, repo: Path, action: str) -> str:
        if action == "check_database_url":
            return check_database_url(repo)

        if action == "fix_database_url":
            return fix_database_url(repo)

        if action == "check_api_key":
            return check_api_key(repo)

        if action == "fix_api_key":
            return fix_api_key(repo)

        if action == "check_migration_file":
            return check_migration_file(repo)

        if action == "fix_migration_file":
            return fix_migration_file(repo)

        if action == "run_verify":
            ok, output = run_verify(repo)
            return "success" if ok else f"failed: {normalize_error(output)}"

        return f"unknown action: {action}"

    def plan_from_error(self, error: str | None) -> list[str]:
        if error == "DATABASE_URL_missing":
            return [
                "check_database_url",
                "fix_database_url",
                "run_verify",
            ]

        if error == "API_KEY_missing":
            return [
                "check_api_key",
                "fix_api_key",
                "run_verify",
            ]

        if error == "MIGRATION_FILE_missing":
            return [
                "check_migration_file",
                "fix_migration_file",
                "run_verify",
            ]

        return ["run_verify"]

    def repair(self, case: RepoCase) -> RepairResult:
        repo = copy_repo(case, self.name)
        actions: list[str] = []

        unsafe_failures = 0
        first_error = None

        learned = self.learned_plan(case)

        self.memory.start_session(case.family)

        if learned:
            plan = learned
        else:
            success, output = run_verify(repo)
            actions.append("run_verify")

            if success:
                self.memory.log_step("run_verify", "success")
                self.memory.end_session("success")
                return RepairResult(
                    agent=self.name,
                    repo=case.name,
                    family=case.family,
                    success=True,
                    unsafe_failures=0,
                    repeated_unsafe_failures=0,
                    actions=actions,
                    first_error=None,
                    final_output=output,
                )

            unsafe_failures += 1
            first_error = normalize_error(output)

            self.memory.remember(
                f"Repository repair failed in {case.family}: {first_error}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.95,
            )

            plan = self.plan_from_error(first_error)

        final_output = ""
        success = False

        for action in plan:
            actions.append(action)
            observation = self.execute_action(repo, action)
            self.memory.log_step(action, observation)

            if action == "run_verify":
                success = observation == "success"
                final_output = observation

        if not final_output:
            ok, output = run_verify(repo)
            actions.append("run_verify")
            self.memory.log_step("run_verify", "success" if ok else f"failed: {normalize_error(output)}")
            success = ok
            final_output = output

        self.memory.end_session("success" if success else "failure", error=None if success else final_output)

        if success:
            self.memory.remember(
                f"Repository repair succeeded in {case.family}. Clean procedure: {actions}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.97,
            )

        self.memory.learn(min_samples=3)

        return RepairResult(
            agent=self.name,
            repo=case.name,
            family=case.family,
            success=success,
            unsafe_failures=unsafe_failures,
            repeated_unsafe_failures=0,
            actions=actions,
            first_error=first_error,
            final_output=final_output,
        )


def count_repeated_unsafe_failures(results: list[RepairResult]) -> int:
    seen: set[tuple[str, str]] = set()
    repeated = 0

    for result in results:
        if not result.first_error:
            continue

        key = (result.family, result.first_error)

        if key in seen:
            repeated += 1
        else:
            seen.add(key)

    return repeated


def summarize(agent_name: str, results: list[RepairResult]):
    total = len(results)
    successes = sum(1 for r in results if r.success)
    unsafe_failures = sum(r.unsafe_failures for r in results)
    repeated = count_repeated_unsafe_failures(results)
    avg_actions = sum(len(r.actions) for r in results) / total

    return {
        "agent": agent_name,
        "repos": total,
        "successes": successes,
        "success_rate": successes / total if total else 0,
        "unsafe_failures": unsafe_failures,
        "repeated_unsafe_failures": repeated,
        "avg_actions": avg_actions,
    }


def print_agent_results(agent_name: str, results: list[RepairResult]):
    print("\n" + "=" * 100)
    print(f"{agent_name}")
    print("=" * 100)

    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(
            f"{status:4} | {result.repo:22} | error={str(result.first_error):22} | actions={result.actions}"
        )

    summary = summarize(agent_name, results)

    print("\nSummary:")
    print(json.dumps(summary, indent=2))

    return summary


def run():
    print("\n🧠 Howdex Real Repo Repair Benchmark")
    print("===================================")
    print("Creates real broken repo folders, runs real verify.py commands, repairs files, and compares agents.\n")

    cases = create_all_fixtures()

    agents: list[BaseRepairAgent] = [
        NoMemoryAgent(),
        VectorOnlyAgent(),
        HowdexProceduralAgent(),
    ]

    summaries = []
    all_results: dict[str, list[RepairResult]] = {}

    start = time.time()

    for agent in agents:
        results = [agent.repair(case) for case in cases]
        all_results[agent.name] = results
        summaries.append(print_agent_results(agent.name, results))

    baseline = summaries[0]
    vector = summaries[1]
    recall = summaries[2]

    print("\n" + "=" * 100)
    print("FINAL REAL REPO REPAIR SCORECARD")
    print("=" * 100)

    checks = {
        "howdex_success_rate_100_percent": recall["success_rate"] == 1.0,
        "howdex_beats_no_memory_repeated_failures": recall["repeated_unsafe_failures"] < baseline["repeated_unsafe_failures"],
        "howdex_beats_vector_only_repeated_failures": recall["repeated_unsafe_failures"] < vector["repeated_unsafe_failures"],
        "howdex_learns_procedures": True,
    }

    # Verify procedures exist for all three families.
    howdex_agent = agents[2]
    assert isinstance(howdex_agent, HowdexProceduralAgent)

    procedures = {}
    for family in sorted({c.family for c in cases}):
        proc = howdex_agent.memory.get_procedure(family)
        procedures[family] = [
            step.get("action", step) if isinstance(step, dict) else step
            for step in proc.steps
        ] if proc and proc.steps else []

    for family, steps in procedures.items():
        if not steps:
            checks["howdex_learns_procedures"] = False

    print("\nLearned procedures:")
    for family, steps in procedures.items():
        print(f"\n{family}")
        for i, step in enumerate(steps, start=1):
            print(f"   {i}. {step}")

    print("\nChecks:")
    for name, ok in checks.items():
        print(f"   {'✅' if ok else '❌'} {name}")

    passed = sum(1 for ok in checks.values() if ok)
    total = len(checks)

    print(f"\nScore: {passed}/{total}")

    if passed == total:
        print("\n🔥 REAL REPO REPAIR BENCHMARK PASS")
        print("Howdex beat no-memory and vector-only baselines on repeated unsafe failures.")
    else:
        print("\n⚠️ NOT 10/10 YET")
        print("The failing checks show what still needs improving.")

    print(f"\nRuntime: {time.time() - start:.2f}s")
    print(f"Benchmark data written to: {ROOT}")


if __name__ == "__main__":
    run()
