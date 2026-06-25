from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from benchmarks.swe_repeat.families import FAULT_FAMILIES, FaultFamily
from benchmarks.swe_repeat.tasks import ALL_TASKS, RepoSpec


def run_command(cwd: Path, command: list[str], timeout: int = 120) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "ok": result.returncode == 0,
            "output_tail": result.stdout[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "ok": False,
            "output_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "timeout",
            "timeout": True,
        }


def clone_repo(spec: RepoSpec, dest: Path) -> dict[str, Any]:
    return run_command(dest.parent, ["git", "clone", "--depth", "1", spec.url, dest.name], timeout=180)


def evaluate_task(work_root: Path, family: FaultFamily, spec: RepoSpec) -> dict[str, Any]:
    repo_dir = work_root / f"{family.name}__{spec.name}"

    result: dict[str, Any] = {
        "family": family.name,
        "repo": spec.name,
        "url": spec.url,
        "target_file": spec.target_file,
        "eligible": False,
        "passed": False,
        "stages": {},
    }

    clone = clone_repo(spec, repo_dir)
    result["stages"]["clone"] = clone
    if not clone["ok"]:
        result["reason"] = "clone_failed"
        return result

    install = run_command(repo_dir, spec.install_command, timeout=240)
    result["stages"]["install"] = install
    if not install["ok"]:
        result["reason"] = "install_failed"
        return result

    clean_test = run_command(repo_dir, spec.test_command, timeout=180)
    result["stages"]["clean_test"] = clean_test
    if not clean_test["ok"]:
        result["reason"] = "clean_test_failed"
        return result

    injected = family.inject(repo_dir, spec)
    result["stages"]["inject"] = {"ok": injected}
    if not injected:
        result["reason"] = "inject_failed"
        return result

    broken_test = run_command(repo_dir, spec.test_command, timeout=180)
    result["stages"]["broken_test"] = broken_test
    if broken_test["ok"]:
        result["reason"] = "fault_did_not_fail_tests"
        return result

    repaired = family.repair(repo_dir, spec)
    result["stages"]["repair"] = {"ok": repaired}
    if not repaired:
        result["reason"] = "repair_failed"
        return result

    repaired_test = run_command(repo_dir, spec.test_command, timeout=180)
    result["stages"]["repaired_test"] = repaired_test
    if not repaired_test["ok"]:
        result["reason"] = "repaired_test_failed"
        return result

    result["eligible"] = True
    result["passed"] = True
    result["reason"] = "passed"
    result["expected_procedure"] = list(family.expected_procedure)
    return result


def run_all(output_path: Path | None = None) -> dict[str, Any]:
    families_by_name = {family.name: family for family in FAULT_FAMILIES}
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="howdex-swe-repeat-") as tmp:
        work_root = Path(tmp)

        for family_name, specs in ALL_TASKS.items():
            family = families_by_name[family_name]
            for spec in specs:
                print(f"== {family.name} / {spec.name} ==")
                task_result = evaluate_task(work_root, family, spec)
                status = "✅" if task_result.get("passed") else "❌"
                print(f"{status} {task_result['reason']}")
                results.append(task_result)

    summary = {
        "families": len(FAULT_FAMILIES),
        "configured_tasks": sum(len(v) for v in ALL_TASKS.values()),
        "eligible_tasks": sum(1 for r in results if r.get("eligible")),
        "passed_tasks": sum(1 for r in results if r.get("passed")),
        "failed_tasks": sum(1 for r in results if not r.get("passed")),
    }

    payload = {
        "benchmark": "swe_repeat_multi_family",
        "summary": summary,
        "families": [asdict(f) | {"inject": f.inject.__name__, "repair": f.repair.__name__} for f in FAULT_FAMILIES],
        "results": results,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2))
        print(f"\n✅ wrote {output_path}")

    print("\n== Summary ==")
    for key, value in summary.items():
        print(f"{key}: {value}")

    if summary["eligible_tasks"] < 3:
        raise SystemExit("Not enough eligible tasks for benchmark signal.")

    return payload


if __name__ == "__main__":
    run_all(Path("benchmark_results/swe_repeat_multi_family_latest.json"))
