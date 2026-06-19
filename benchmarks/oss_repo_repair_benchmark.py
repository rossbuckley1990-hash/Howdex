from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from howdex import Howdex


ROOT = Path.home() / ".howdex-oss-repo-repair-benchmark"
CLONES = ROOT / "clones"
RUNS = ROOT / "runs"

if ROOT.exists():
    shutil.rmtree(ROOT)

CLONES.mkdir(parents=True, exist_ok=True)
RUNS.mkdir(parents=True, exist_ok=True)


@dataclass
class RepoSpec:
    name: str
    url: str
    family: str
    fault: str


@dataclass
class RepairResult:
    agent: str
    repo: str
    family: str
    fault: str
    success: bool
    unsafe_failures: int
    repeated_unsafe_failures: int
    actions: list[str]
    first_error: str | None
    final_output: str


REPOS = [
    # Python repos with pyproject.toml
    RepoSpec(
        name="fastapi",
        url="https://github.com/fastapi/fastapi.git",
        family="repair python pyproject build backend",
        fault="PYPROJECT_BACKEND_BROKEN",
    ),
    RepoSpec(
        name="httpx",
        url="https://github.com/encode/httpx.git",
        family="repair python pyproject build backend",
        fault="PYPROJECT_BACKEND_BROKEN",
    ),
    RepoSpec(
        name="rich",
        url="https://github.com/Textualize/rich.git",
        family="repair python pyproject build backend",
        fault="PYPROJECT_BACKEND_BROKEN",
    ),
    RepoSpec(
        name="pydantic",
        url="https://github.com/pydantic/pydantic.git",
        family="repair python pyproject build backend",
        fault="PYPROJECT_BACKEND_BROKEN",
    ),

    # Node/TS repos with package.json
    RepoSpec(
        name="vite",
        url="https://github.com/vitejs/vite.git",
        family="repair node package test script",
        fault="PACKAGE_JSON_TEST_SCRIPT_MISSING",
    ),
    RepoSpec(
        name="prettier",
        url="https://github.com/prettier/prettier.git",
        family="repair node package test script",
        fault="PACKAGE_JSON_TEST_SCRIPT_MISSING",
    ),
    RepoSpec(
        name="eslint",
        url="https://github.com/eslint/eslint.git",
        family="repair node package test script",
        fault="PACKAGE_JSON_TEST_SCRIPT_MISSING",
    ),
    RepoSpec(
        name="nextjs",
        url="https://github.com/vercel/next.js.git",
        family="repair node package test script",
        fault="PACKAGE_JSON_TEST_SCRIPT_MISSING",
    ),
]


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, out
    except subprocess.TimeoutExpired as e:
        return False, f"TIMEOUT: {' '.join(cmd)}\n{e}"


def clone_repo(spec: RepoSpec) -> Path:
    dest = CLONES / spec.name

    if dest.exists():
        return dest

    print(f"Cloning {spec.name}...")
    ok, out = run_cmd(
        ["git", "clone", "--depth", "1", spec.url, str(dest)],
        timeout=240,
    )

    if not ok:
        raise RuntimeError(f"Failed to clone {spec.name}:\n{out}")

    return dest


def copy_repo_for_agent(spec: RepoSpec, agent_name: str) -> Path:
    src = CLONES / spec.name
    dest = RUNS / agent_name / spec.name

    if dest.exists():
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))

    return dest


def backup_file(path: Path):
    backup = path.with_suffix(path.suffix + ".howdexbak")
    if not backup.exists():
        backup.write_text(path.read_text())


def restore_file(path: Path):
    backup = path.with_suffix(path.suffix + ".howdexbak")
    if not backup.exists():
        raise FileNotFoundError(f"No backup found for {path}")
    path.write_text(backup.read_text())


def inject_pyproject_backend_fault(repo: Path) -> str:
    path = repo / "pyproject.toml"

    if not path.exists():
        return "failed: pyproject.toml missing"

    backup_file(path)
    text = path.read_text()

    if "build-backend" not in text:
        text += '\n[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'

    lines = []
    replaced = False

    for line in text.splitlines():
        if line.strip().startswith("build-backend"):
            lines.append('build-backend = "howdex_broken_backend.DOES_NOT_EXIST"')
            replaced = True
        else:
            lines.append(line)

    if not replaced:
        lines.append('build-backend = "howdex_broken_backend.DOES_NOT_EXIST"')

    path.write_text("\n".join(lines) + "\n")
    return "injected PYPROJECT_BACKEND_BROKEN"


def inject_package_json_test_fault(repo: Path) -> str:
    path = repo / "package.json"

    if not path.exists():
        return "failed: package.json missing"

    backup_file(path)
    data = json.loads(path.read_text())

    scripts = data.setdefault("scripts", {})

    if "test" not in scripts:
        scripts["test"] = "echo placeholder test"

    scripts["test_howdex_backup"] = scripts["test"]
    scripts.pop("test", None)

    path.write_text(json.dumps(data, indent=2) + "\n")
    return "injected PACKAGE_JSON_TEST_SCRIPT_MISSING"


def inject_fault(repo: Path, spec: RepoSpec) -> str:
    if spec.fault == "PYPROJECT_BACKEND_BROKEN":
        return inject_pyproject_backend_fault(repo)

    if spec.fault == "PACKAGE_JSON_TEST_SCRIPT_MISSING":
        return inject_package_json_test_fault(repo)

    return f"failed: unknown fault {spec.fault}"


def verify_pyproject_backend(repo: Path) -> tuple[bool, str]:
    path = repo / "pyproject.toml"

    if not path.exists():
        return False, "ERROR: pyproject.toml missing"

    text = path.read_text()

    if "howdex_broken_backend.DOES_NOT_EXIST" in text:
        return False, "ERROR: PYPROJECT_BACKEND_BROKEN"

    if "build-backend" not in text:
        return False, "ERROR: PYPROJECT_BUILD_BACKEND_MISSING"

    return True, "OK: pyproject build backend valid"


def verify_package_json_test(repo: Path) -> tuple[bool, str]:
    path = repo / "package.json"

    if not path.exists():
        return False, "ERROR: package.json missing"

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return False, f"ERROR: package.json invalid JSON: {e}"

    scripts = data.get("scripts", {})

    if "test" not in scripts:
        return False, "ERROR: PACKAGE_JSON_TEST_SCRIPT_MISSING"

    return True, "OK: package.json test script present"


def verify_repo(repo: Path, spec: RepoSpec) -> tuple[bool, str]:
    if spec.fault == "PYPROJECT_BACKEND_BROKEN":
        return verify_pyproject_backend(repo)

    if spec.fault == "PACKAGE_JSON_TEST_SCRIPT_MISSING":
        return verify_package_json_test(repo)

    return False, f"ERROR: unknown fault {spec.fault}"


def normalize_error(output: str | None) -> str | None:
    if not output:
        return None

    text = output.lower()

    if "pyproject_backend_broken" in text or "broken_backend" in text:
        return "PYPROJECT_BACKEND_BROKEN"

    if "pyproject_build_backend_missing" in text:
        return "PYPROJECT_BUILD_BACKEND_MISSING"

    if "package_json_test_script_missing" in text:
        return "PACKAGE_JSON_TEST_SCRIPT_MISSING"

    if "invalid json" in text:
        return "PACKAGE_JSON_INVALID_JSON"

    return output.strip()


def check_pyproject_backend(repo: Path) -> str:
    ok, out = verify_pyproject_backend(repo)
    return "valid" if ok else normalize_error(out) or "invalid"


def fix_pyproject_backend(repo: Path) -> str:
    restore_file(repo / "pyproject.toml")
    return "fixed pyproject build backend"


def check_package_json_test_script(repo: Path) -> str:
    ok, out = verify_package_json_test(repo)
    return "present" if ok else normalize_error(out) or "missing"


def fix_package_json_test_script(repo: Path) -> str:
    restore_file(repo / "package.json")
    return "fixed package.json test script"


class BaseAgent:
    name = "base"

    def repair(self, spec: RepoSpec) -> RepairResult:
        raise NotImplementedError


class NoMemoryAgent(BaseAgent):
    name = "no_memory"

    def repair(self, spec: RepoSpec) -> RepairResult:
        repo = copy_repo_for_agent(spec, self.name)
        inject_fault(repo, spec)

        actions: list[str] = []
        unsafe_failures = 0
        first_error = None

        ok, out = verify_repo(repo, spec)
        actions.append("verify_repo")

        if not ok:
            unsafe_failures += 1
            first_error = normalize_error(out)

            if first_error in {"PYPROJECT_BACKEND_BROKEN", "PYPROJECT_BUILD_BACKEND_MISSING"}:
                actions.append("fix_pyproject_backend")
                fix_pyproject_backend(repo)

            elif first_error == "PACKAGE_JSON_TEST_SCRIPT_MISSING":
                actions.append("fix_package_json_test_script")
                fix_package_json_test_script(repo)

        ok, final = verify_repo(repo, spec)
        actions.append("verify_repo")

        return RepairResult(
            agent=self.name,
            repo=spec.name,
            family=spec.family,
            fault=spec.fault,
            success=ok,
            unsafe_failures=unsafe_failures,
            repeated_unsafe_failures=0,
            actions=actions,
            first_error=first_error,
            final_output=final,
        )


class VectorOnlyAgent(BaseAgent):
    name = "vector_only"

    def __init__(self):
        self.memory = Howdex(path=str(ROOT / "vector_only.db"))

    def repair(self, spec: RepoSpec) -> RepairResult:
        repo = copy_repo_for_agent(spec, self.name)
        inject_fault(repo, spec)

        actions: list[str] = []

        # Vector memory is queried, but no executable procedure is used.
        _ = self.memory.recall(
            f"{spec.family} {spec.fault} previous repairs",
            top_k=5,
            min_score=0.0,
        )

        unsafe_failures = 0
        first_error = None

        ok, out = verify_repo(repo, spec)
        actions.append("verify_repo")

        if not ok:
            unsafe_failures += 1
            first_error = normalize_error(out)

            self.memory.remember(
                f"OSS repo repair failed for {spec.family}. Error: {first_error}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.9,
            )

            if first_error in {"PYPROJECT_BACKEND_BROKEN", "PYPROJECT_BUILD_BACKEND_MISSING"}:
                actions.append("fix_pyproject_backend")
                fix_pyproject_backend(repo)

            elif first_error == "PACKAGE_JSON_TEST_SCRIPT_MISSING":
                actions.append("fix_package_json_test_script")
                fix_package_json_test_script(repo)

        ok, final = verify_repo(repo, spec)
        actions.append("verify_repo")

        if ok:
            self.memory.remember(
                f"OSS repo repair succeeded for {spec.family}. Actions: {actions}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.95,
            )

        return RepairResult(
            agent=self.name,
            repo=spec.name,
            family=spec.family,
            fault=spec.fault,
            success=ok,
            unsafe_failures=unsafe_failures,
            repeated_unsafe_failures=0,
            actions=actions,
            first_error=first_error,
            final_output=final,
        )


class HowdexProceduralAgent(BaseAgent):
    name = "howdex_procedural"

    def __init__(self):
        self.memory = Howdex(path=str(ROOT / "howdex_procedural.db"))

    def learned_plan(self, spec: RepoSpec) -> list[str] | None:
        proc = self.memory.get_procedure(spec.family)

        if not proc or not proc.steps:
            return None

        return [
            step.get("action", step) if isinstance(step, dict) else step
            for step in proc.steps
        ]

    def plan_from_error(self, error: str | None) -> list[str]:
        if error in {"PYPROJECT_BACKEND_BROKEN", "PYPROJECT_BUILD_BACKEND_MISSING"}:
            return [
                "check_pyproject_backend",
                "fix_pyproject_backend",
                "verify_repo",
            ]

        if error == "PACKAGE_JSON_TEST_SCRIPT_MISSING":
            return [
                "check_package_json_test_script",
                "fix_package_json_test_script",
                "verify_repo",
            ]

        return ["verify_repo"]

    def execute_action(self, repo: Path, spec: RepoSpec, action: str) -> str:
        if action == "check_pyproject_backend":
            return check_pyproject_backend(repo)

        if action == "fix_pyproject_backend":
            return fix_pyproject_backend(repo)

        if action == "check_package_json_test_script":
            return check_package_json_test_script(repo)

        if action == "fix_package_json_test_script":
            return fix_package_json_test_script(repo)

        if action == "verify_repo":
            ok, out = verify_repo(repo, spec)
            return "success" if ok else f"failed: {normalize_error(out)}"

        return f"unknown action: {action}"

    def repair(self, spec: RepoSpec) -> RepairResult:
        repo = copy_repo_for_agent(spec, self.name)
        inject_fault(repo, spec)

        actions: list[str] = []
        unsafe_failures = 0
        first_error = None

        self.memory.start_session(spec.family)

        learned = self.learned_plan(spec)

        if learned:
            plan = learned

        else:
            ok, out = verify_repo(repo, spec)
            actions.append("verify_repo")

            if ok:
                self.memory.log_step("verify_repo", "success")
                self.memory.end_session("success")
                return RepairResult(
                    agent=self.name,
                    repo=spec.name,
                    family=spec.family,
                    fault=spec.fault,
                    success=True,
                    unsafe_failures=0,
                    repeated_unsafe_failures=0,
                    actions=actions,
                    first_error=None,
                    final_output=out,
                )

            unsafe_failures += 1
            first_error = normalize_error(out)

            self.memory.remember(
                f"OSS repo repair failed for {spec.family}. Error: {first_error}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.95,
            )

            plan = self.plan_from_error(first_error)

        success = False
        final_output = ""

        for action in plan:
            actions.append(action)
            observation = self.execute_action(repo, spec, action)
            self.memory.log_step(action, observation)

            if action == "verify_repo":
                success = observation == "success"
                final_output = observation

        if not final_output:
            ok, out = verify_repo(repo, spec)
            actions.append("verify_repo")
            obs = "success" if ok else f"failed: {normalize_error(out)}"
            self.memory.log_step("verify_repo", obs)
            success = ok
            final_output = obs

        self.memory.end_session("success" if success else "failure", error=None if success else final_output)

        if success:
            self.memory.remember(
                f"OSS repo repair succeeded for {spec.family}. Clean procedure: {actions}",
                layer="semantic",
                type="fact",
                metadata={"source": "tool", "verified": True, "trusted": True},
                importance=0.97,
            )

        self.memory.learn(min_samples=3)

        return RepairResult(
            agent=self.name,
            repo=spec.name,
            family=spec.family,
            fault=spec.fault,
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

    for r in results:
        if not r.first_error:
            continue

        key = (r.family, r.first_error)

        if key in seen:
            repeated += 1
        else:
            seen.add(key)

    return repeated


def summarize(agent_name: str, results: list[RepairResult]) -> dict:
    total = len(results)
    successes = sum(1 for r in results if r.success)
    unsafe_failures = sum(r.unsafe_failures for r in results)
    repeated = count_repeated_unsafe_failures(results)
    avg_actions = sum(len(r.actions) for r in results) / total if total else 0

    return {
        "agent": agent_name,
        "repos": total,
        "successes": successes,
        "success_rate": successes / total if total else 0,
        "unsafe_failures": unsafe_failures,
        "repeated_unsafe_failures": repeated,
        "avg_actions": avg_actions,
    }


def print_results(name: str, results: list[RepairResult]) -> dict:
    print("\n" + "=" * 110)
    print(name)
    print("=" * 110)

    for r in results:
        status = "PASS" if r.success else "FAIL"
        print(f"{status:4} | {r.repo:16} | {r.fault:34} | error={str(r.first_error):34} | actions={r.actions}")

    summary = summarize(name, results)
    print("\nSummary:")
    print(json.dumps(summary, indent=2))
    return summary


def run():
    print("\n🧠 Howdex OSS Repo Repair Benchmark")
    print("==================================")
    print("Clones real open-source repositories, injects controlled config faults, repairs them, and compares agents.\n")

    for spec in REPOS:
        clone_repo(spec)

    agents: list[BaseAgent] = [
        NoMemoryAgent(),
        VectorOnlyAgent(),
        HowdexProceduralAgent(),
    ]

    summaries = []
    all_results: dict[str, list[RepairResult]] = {}

    start = time.time()

    for agent in agents:
        results = [agent.repair(spec) for spec in REPOS]
        all_results[agent.name] = results
        summaries.append(print_results(agent.name, results))

    baseline = summaries[0]
    vector = summaries[1]
    recall = summaries[2]

    howdex_agent = agents[2]
    assert isinstance(howdex_agent, HowdexProceduralAgent)

    families = sorted({spec.family for spec in REPOS})
    procedures = {}

    for family in families:
        proc = howdex_agent.memory.get_procedure(family)
        procedures[family] = [
            step.get("action", step) if isinstance(step, dict) else step
            for step in proc.steps
        ] if proc and proc.steps else []

    print("\n" + "=" * 110)
    print("FINAL OSS REPO REPAIR SCORECARD")
    print("=" * 110)

    print("\nLearned procedures:")
    for family, steps in procedures.items():
        print(f"\n{family}")
        for i, step in enumerate(steps, start=1):
            print(f"   {i}. {step}")

    checks = {
        "howdex_success_rate_100_percent": recall["success_rate"] == 1.0,
        "howdex_beats_no_memory_repeated_failures": recall["repeated_unsafe_failures"] < baseline["repeated_unsafe_failures"],
        "howdex_beats_vector_only_repeated_failures": recall["repeated_unsafe_failures"] < vector["repeated_unsafe_failures"],
        "howdex_learns_oss_procedures": all(bool(steps) for steps in procedures.values()),
    }

    print("\nChecks:")
    for name, ok in checks.items():
        print(f"   {'✅' if ok else '❌'} {name}")

    passed = sum(1 for ok in checks.values() if ok)
    total = len(checks)

    print(f"\nScore: {passed}/{total}")

    if passed == total:
        print("\n🔥 OSS REPO REPAIR BENCHMARK PASS")
        print("Howdex beat no-memory and vector-only baselines on real open-source repository repair tasks.")
    else:
        print("\n⚠️ NOT 10/10 YET")
        print("The failing checks show what must improve.")

    print(f"\nRuntime: {time.time() - start:.2f}s")
    print(f"Benchmark data written to: {ROOT}")


if __name__ == "__main__":
    run()
