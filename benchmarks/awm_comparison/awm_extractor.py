"""AWM-style LLM workflow induction — faithful reimplementation for benchmarking.

This module reimplements the extraction step of Agent Workflow Memory
(AWM, Wang et al., ICML 2025, arXiv:2409.07429) for head-to-head
comparison with Howdex's deterministic extraction.

AWM's approach:
1. Take successful agent trajectories
2. Use an LLM to extract reusable "workflows" (ordered action sequences)
3. Store workflows keyed by task type
4. At test time, retrieve matching workflows and inject as guidance

Key difference from Howdex: AWM uses an LLM for extraction (which
generalizes better across environments but costs tokens and is opaque);
Howdex uses deterministic rules (which are inspectable and free but
bounded by the canonicalizer).

This implementation is deliberately simple and faithful to AWM's
core idea — not a production system. It exists so the benchmark can
run Arm C (AWM-style) alongside Arm B (Howdex) and Arm A (no memory).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


AWM_EXTRACTION_PROMPT = """\
You are a workflow extraction system. Given a successful agent trajectory,
extract a reusable workflow as a JSON object.

Rules:
- Identify the key steps that led to success.
- Generalize specific values to placeholders (e.g., "express" -> "<PACKAGE>").
- Remove environment-specific details.
- Output ONLY a JSON object with "task_type" and "steps" fields.

Trajectory:
{trajectory}

Output the workflow as JSON:"""


class AWMStyleExtractor:
    """LLM-based workflow extractor (Arm C of the benchmark).

    Two modes:
    1. With an LLM provider (real AWM extraction — costs tokens)
    2. Without (deterministic mock that simulates LLM extraction quality)
    """

    def __init__(self, llm_provider=None):
        self.llm_provider = llm_provider
        self.workflows: dict[str, dict] = {}
        self.total_tokens_used = 0
        self.extraction_calls = 0

    def extract_workflow(self, episode: dict) -> dict | None:
        if episode.get("outcome") != "success":
            return None
        steps = episode.get("steps", [])
        if not steps:
            return None
        self.extraction_calls += 1
        if self.llm_provider is not None:
            return self._extract_with_llm(episode, steps)
        else:
            return self._extract_mock(episode, steps)

    def _extract_with_llm(self, episode: dict, steps: list) -> dict:
        trajectory = "\n".join(
            f"  {i+1}. {s.get('action', '?')} -> {s.get('observation', '?')[:80]}"
            for i, s in enumerate(steps)
        )
        prompt = AWM_EXTRACTION_PROMPT.format(trajectory=trajectory)
        response = self.llm_provider.complete(prompt)
        self.total_tokens_used += len(prompt) + len(response)
        try:
            workflow = json.loads(response)
            workflow["source_episode"] = episode.get("id", "")
            workflow["extraction_method"] = "llm"
            return workflow
        except (json.JSONDecodeError, TypeError):
            return self._extract_mock(episode, steps)

    def _extract_mock(self, episode: dict, steps: list) -> dict:
        """Deterministic mock that simulates LLM-style extraction.

        Generalizes BETTER than Howdex's rule-based canonicalizer
        (recognizes synonyms and paraphrases) but is reproducible.
        """
        LLM_STYLE_MAP = {
            "read": "read_config", "check": "read_config",
            "inspect": "read_config", "view": "read_config",
            "look": "read_config", "cat": "read_config",
            "examine": "read_config", "open": "read_config",
            "show": "read_config",
            "run": "execute_app", "start": "execute_app",
            "launch": "execute_app", "node": "execute_app",
            "python": "execute_app",
            "install": "install_dependency", "npm": "install_dependency",
            "pip": "install_dependency", "yarn": "install_dependency",
            "add": "install_dependency", "apt": "install_dependency",
            "build": "build_project", "make": "build_project",
            "compile": "build_project", "webpack": "build_project",
            "test": "run_tests", "pytest": "run_tests",
            "jest": "run_tests", "mocha": "run_tests",
            "fix": "apply_fix", "edit": "apply_fix",
            "patch": "apply_fix", "modify": "apply_fix",
            "update": "apply_fix", "change": "apply_fix",
            "rename": "apply_fix", "move": "apply_fix",
            "deploy": "deploy_service", "push": "deploy_service",
            "release": "deploy_service",
            "search": "search_code", "find": "search_code",
            "grep": "search_code", "locate": "search_code",
        }

        canonical_steps = []
        for step in steps:
            action = str(step.get("action", "")).lower()
            canonical = "unknown"
            for keyword in sorted(LLM_STYLE_MAP.keys(), key=len, reverse=True):
                if keyword in action:
                    canonical = LLM_STYLE_MAP[keyword]
                    break
            canonical_steps.append(canonical)

        return {
            "task_type": episode.get("task", ""),
            "steps": canonical_steps,
            "source_episode": episode.get("id", ""),
            "extraction_method": "llm_mock",
            "generalized": True,
        }

    def get_extraction_cost(self) -> dict:
        cost_usd = (self.total_tokens_used / 1_000_000) * 5 if self.total_tokens_used > 0 else 0
        return {
            "tokens": self.total_tokens_used,
            "cost_usd": round(cost_usd, 4),
            "extraction_calls": self.extraction_calls,
            "method": "llm" if self.llm_provider else "llm_mock",
        }


def awm_retrieve_guidance(workflows: dict[str, dict], task: str) -> dict | None:
    if not workflows:
        return None
    best = None
    best_score = 0
    task_words = set(task.lower().split())
    for wf_key, wf in workflows.items():
        wf_words = set(wf.get("task_type", "").lower().split())
        step_words = set()
        for s in wf.get("steps", []):
            step_words.update(s.lower().split("_"))
        score = len(task_words & (wf_words | step_words))
        if score > best_score:
            best = wf
            best_score = score
    return best if best_score > 0 else None


def render_awm_guidance(workflow: dict) -> str:
    lines = [
        "# AWM WORKFLOW MEMORY",
        "",
        "Use this as prior guidance. Verify in the current environment.",
        "",
        f"Task type: {workflow.get('task_type', '?')}",
        f"Method: {workflow.get('extraction_method', 'llm')}",
        "",
        "Workflow steps:",
    ]
    for i, step in enumerate(workflow.get("steps", []), 1):
        lines.append(f"  {i}. {step}")
    lines.extend([
        "",
        "Rules:",
        "- Adapt these steps to the current environment.",
        "- Do not claim success until a real verifier passes.",
    ])
    return "\n".join(lines)
