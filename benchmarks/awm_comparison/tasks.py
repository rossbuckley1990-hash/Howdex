"""Reproducible task family for the AWM vs Howdex benchmark.

Each task is a simulated agent scenario with:
- A task description (the "goal")
- A set of tool actions that solve it (the "solution path")
- Paraphrased variants (to test generalization)
- A deterministic verifier (exit code check)

The tasks are designed to test both seen-task-family (where Howdex
should match AWM) and novel-task generalization (where AWM's LLM
extraction should lead).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field


@dataclass
class BenchmarkTask:
    """A single benchmark task."""
    task_id: str
    task_description: str
    family: str  # e.g., "fix_missing_dep", "fix_wrong_path"
    solution_steps: list[dict]  # the correct action sequence
    verifier: str  # deterministic check description
    is_novel: bool = False  # True for generalization-test tasks
    prompt_hash: str = ""  # for framing-equivalence verification

    def __post_init__(self):
        self.prompt_hash = hashlib.sha256(
            self.task_description.encode()
        ).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Task families — each family has a "seen" variant (training) and a
# "novel" variant (generalization test). The novel variant uses different
# vocabulary for the same underlying task, testing whether the extraction
# method can generalize.
# --------------------------------------------------------------------------- #

def generate_task_family(seed: int = 42) -> tuple[list[BenchmarkTask], list[BenchmarkTask]]:
    """Generate training and test tasks.

    Returns (training_tasks, test_tasks) where test_tasks include both
    seen-family variants (same family, different instance) and novel
    variants (paraphrased descriptions that test generalization).
    """
    rng = random.Random(seed)

    families = [
        {
            "family": "fix_missing_dep",
            "seen_desc": "Fix a Node app that cannot find module {module}",
            "novel_desc": "Resolve an import error in a JavaScript project — the {module} package isn't installed",
            "modules": ["express", "cors", "bcrypt", "lodash", "axios",
                       "mongoose", "jsonwebtoken", "dotenv", "helmet", "morgan"],
            "solution": [
                {"action": "read package.json", "observation": "dependency listed"},
                {"action": "run node app.js", "observation": "Error: Cannot find module"},
                {"action": "run npm install {module}", "observation": "added 1 package"},
                {"action": "run node app.js", "observation": "App running"},
            ],
            "verifier": "node app.js exits 0",
        },
        {
            "family": "fix_wrong_path",
            "seen_desc": "Fix a Python app with a hardcoded path to {old_path}",
            "novel_desc": "A Python script is crashing because it references {old_path} which doesn't exist — make it portable",
            "modules": [],  # not used for this family
            "old_paths": ["/etc/config/app.json", "/var/log/app.log", "/opt/data/db.sqlite",
                         "/usr/local/etc/settings.yaml", "/tmp/app_state.json"],
            "solution": [
                {"action": "read the source file", "observation": "found hardcoded path"},
                {"action": "search for the path string", "observation": "found in config.py"},
                {"action": "edit the file to use relative path", "observation": "updated"},
                {"action": "run python app.py", "observation": "App started"},
            ],
            "verifier": "python app.py exits 0",
        },
    ]

    training_tasks = []
    test_tasks = []

    # Generate 5 training tasks per family (10 total)
    for fam in families:
        for i in range(5):
            if fam["family"] == "fix_missing_dep":
                module = rng.choice(fam["modules"])
                desc = fam["seen_desc"].format(module=module)
                steps = [
                    {"action": s["action"].format(module=module),
                     "observation": s["observation"]}
                    for s in fam["solution"]
                ]
            else:
                old_path = rng.choice(fam["old_paths"])
                desc = fam["seen_desc"].format(old_path=old_path)
                steps = [
                    {"action": s["action"].format(old_path=old_path),
                     "observation": s["observation"]}
                    for s in fam["solution"]
                ]

            task = BenchmarkTask(
                task_id=f"train_{fam['family']}_{i}",
                task_description=desc,
                family=fam["family"],
                solution_steps=steps,
                verifier=fam["verifier"],
                is_novel=False,
            )
            training_tasks.append(task)

    # Generate 5 test tasks per family: 3 seen-family + 2 novel
    for fam in families:
        for i in range(3):
            if fam["family"] == "fix_missing_dep":
                module = rng.choice(fam["modules"])
                desc = fam["seen_desc"].format(module=module)
                steps = [
                    {"action": s["action"].format(module=module),
                     "observation": s["observation"]}
                    for s in fam["solution"]
                ]
            else:
                old_path = rng.choice(fam["old_paths"])
                desc = fam["seen_desc"].format(old_path=old_path)
                steps = [
                    {"action": s["action"].format(old_path=old_path),
                     "observation": s["observation"]}
                    for s in fam["solution"]
                ]

            task = BenchmarkTask(
                task_id=f"test_seen_{fam['family']}_{i}",
                task_description=desc,
                family=fam["family"],
                solution_steps=steps,
                verifier=fam["verifier"],
                is_novel=False,
            )
            test_tasks.append(task)

        # 2 novel (paraphrased) tasks per family
        for i in range(2):
            if fam["family"] == "fix_missing_dep":
                module = rng.choice(fam["modules"])
                desc = fam["novel_desc"].format(module=module)
                steps = [
                    {"action": s["action"].format(module=module),
                     "observation": s["observation"]}
                    for s in fam["solution"]
                ]
            else:
                old_path = rng.choice(fam["old_paths"])
                desc = fam["novel_desc"].format(old_path=old_path)
                steps = [
                    {"action": s["action"].format(old_path=old_path),
                     "observation": s["observation"]}
                    for s in fam["solution"]
                ]

            task = BenchmarkTask(
                task_id=f"test_novel_{fam['family']}_{i}",
                task_description=desc,
                family=fam["family"],
                solution_steps=steps,
                verifier=fam["verifier"],
                is_novel=True,
            )
            test_tasks.append(task)

    return training_tasks, test_tasks


def simulate_agent_run(
    task: BenchmarkTask,
    guidance: str | None,
    rng: random.Random,
) -> dict:
    """Simulate an agent solving a task with or without guidance.

    The simulation models:
    - Without guidance: agent explores randomly, finds solution after
      some dead-ends (higher step count, lower success rate)
    - With guidance: agent follows the guidance, fewer dead-ends
      (lower step count, higher success rate)
    - Novel tasks: guidance helps less if the extraction method
      can't generalize to the paraphrased description

    Returns a dict with: success, steps, attempts, guidance_used.
    """
    # Base success rate without guidance
    base_success_rate = 0.35  # 35% without memory
    base_steps = rng.randint(8, 15)  # explores dead-ends

    if guidance is None:
        # No memory — agent explores from scratch
        success = rng.random() < base_success_rate
        steps = base_steps
        attempts = rng.randint(2, 5)
    else:
        # Has guidance — check if the guidance contains actionable steps
        guidance_lower = guidance.lower()
        guidance_has_steps = any(
            marker in guidance_lower
            for marker in ["steps", "workflow", "procedural", "operational memory",
                          "learned operational facts", "recommended steps",
                          "retrieval budget", "relevant memory"]
        )
        # Also check if guidance actually retrieved a procedure (not just "No prior")
        guidance_has_match = "no prior" not in guidance_lower and "selected procedures: 0" not in guidance_lower
        guidance_quality = 1.0 if not task.is_novel else 0.6

        if guidance_has_steps and guidance_has_match:
            # Guidance provides a roadmap — agent follows it
            success_rate = min(0.95, base_success_rate + 0.35 * guidance_quality)
            success = rng.random() < success_rate
            steps = max(4, base_steps - rng.randint(3, 6))  # fewer steps
            attempts = 1 if success else rng.randint(1, 3)
        else:
            # Guidance exists but isn't useful for this task
            success = rng.random() < base_success_rate
            steps = base_steps
            attempts = rng.randint(2, 5)

    return {
        "success": success,
        "steps": steps,
        "attempts": attempts,
        "guidance_used": guidance is not None,
    }
