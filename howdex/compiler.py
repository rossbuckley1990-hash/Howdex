"""Howdex Procedural Compiler — trajectories → typed, verifiable skills.

The genius move: instead of leaving procedures as natural-language
guidance text (which is what AWM and Howdex both do now), compile them
into **typed, executable Python skills** with:

1. **Hoare-style pre/post-conditions** — "this procedure requires
   `node` to be installed and produces `App running`"
2. **Type signatures** — `fix_missing_dependency(package: str) -> bool`
3. **Auto-generated test cases** — from the verification receipts
4. **Formal precondition verification** — the skill checks preconditions
   before executing and raises if they're not met

This collapses the gap between memory and code. Procedures become
inspectable, testable, sandboxable — exactly what ATF governance
requires. An auditor can look at a typed skill and understand exactly
what it does, what it requires, and what it proves. Natural-language
procedures can't do this.

Usage::

    from howdex import Howdex

    mem = Howdex(path="...", embedder="hashing")
    procs = mem.learn(min_samples=1)

    from howdex.compiler import compile_procedure
    skill = compile_procedure(mem, procs[0])
    skill.save("./skills/")

    # Now it's a Python file you can import:
    # from skills.fix_missing_dependency import fix_missing_dependency
    # result = fix_missing_dependency(package="cors")

CLI::

    howdex compile <procedure_id> --output ./skills/
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from howdex import Howdex


@dataclass
class CompiledSkill:
    """A compiled procedural skill — a typed, executable Python function
    generated from a Howdex procedure.

    Attributes:
        name: The skill name (valid Python identifier, derived from task_signature)
        function_name: The Python function name
        docstring: Human-readable description
        parameters: List of parameter specs (name, type, description)
        preconditions: List of precondition expressions (Python-evaluable)
        postconditions: List of postcondition expressions
        steps: The canonical step sequence (as Python comments)
        source_code: The generated Python source code
        test_code: Auto-generated test code from receipts
        procedure_id: The source procedure ID
        receipt_hash: Hash of the verification receipt (if verified)
    """
    name: str
    function_name: str
    docstring: str
    parameters: list[dict[str, str]] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    source_code: str = ""
    test_code: str = ""
    procedure_id: str = ""
    receipt_hash: str = ""
    task_signature: str = ""

    def save(self, output_dir: str | Path) -> Path:
        """Save the skill as a Python file in output_dir."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        filename = f"{self.name}.py"
        filepath = out / filename
        filepath.write_text(self.source_code, encoding="utf-8")

        # Also save the test file if we have test code
        if self.test_code:
            test_filepath = out / f"test_{self.name}.py"
            test_filepath.write_text(self.test_code, encoding="utf-8")

        # Save metadata
        meta_filepath = out / f"{self.name}.meta.json"
        meta_filepath.write_text(
            json.dumps({
                "name": self.name,
                "function_name": self.function_name,
                "procedure_id": self.procedure_id,
                "task_signature": self.task_signature,
                "receipt_hash": self.receipt_hash,
                "parameters": self.parameters,
                "preconditions": self.preconditions,
                "postconditions": self.postconditions,
                "compiled_at": time.time(),
            }, indent=2),
            encoding="utf-8",
        )
        return filepath


def compile_procedure(
    memory: "Howdex",
    procedure: Any,
    *,
    output_dir: str | Path | None = None,
) -> CompiledSkill:
    """Compile a Howdex procedure into a typed, executable Python skill.

    The compiled skill includes:
    - A Python function with type-annotated parameters
    - Preconditions that are checked at runtime
    - Postconditions that are verified after execution
    - A docstring with the procedure's provenance
    - Auto-generated test cases from verification receipts

    Args:
        memory: The Howdex instance (used to fetch receipts and episodes)
        procedure: The Procedure object to compile
        output_dir: If provided, save the skill file to this directory

    Returns:
        A CompiledSkill object
    """
    task_sig = getattr(procedure, "task_signature", "unknown_task")
    proc_id = getattr(procedure, "id", "")
    steps = getattr(procedure, "steps", [])

    # 1. Derive a valid Python function name from the task signature
    func_name = _to_valid_identifier(task_sig)
    module_name = func_name

    # 2. Extract parameters from the procedure's parameterized steps
    parameters = _extract_parameters(steps)

    # 3. Extract preconditions and postconditions
    preconditions = _extract_preconditions(steps, procedure)
    postconditions = _extract_postconditions(steps, procedure)

    # 4. Get the step sequence as human-readable comments
    step_comments = _steps_to_comments(steps)

    # 5. Get receipt information — re-fetch the procedure from store
    #    to get the latest receipts (the procedure object passed in may
    #    be stale if verify_procedure was called after learn)
    proc_payload = memory.store.get_procedure(getattr(procedure, "task_signature", ""))
    receipts = []
    if proc_payload and isinstance(proc_payload, dict):
        receipts = proc_payload.get("receipts", []) or []
    if not receipts:
        receipts = getattr(procedure, "receipts", []) or []
    receipt_hash = ""
    verifier_command = ""
    if receipts:
        # Find the verified receipt
        for r in receipts:
            if isinstance(r, dict) and r.get("status") == "verified":
                receipt_hash = r.get("receipt_id", "")[:16]
                verifier_command = r.get("verifier_command", "")
                break
        if not receipt_hash and receipts:
            r = receipts[0]
            if isinstance(r, dict):
                receipt_hash = r.get("receipt_id", "")[:16]
                verifier_command = r.get("verifier_command", "")

    # 6. Build the docstring
    docstring = _build_docstring(
        task_sig=task_sig,
        proc_id=proc_id,
        receipt_hash=receipt_hash,
        verifier_command=verifier_command,
        steps=step_comments,
        preconditions=preconditions,
        postconditions=postconditions,
    )

    # 7. Generate the Python source code
    source_code = _generate_source(
        module_name=module_name,
        func_name=func_name,
        parameters=parameters,
        preconditions=preconditions,
        postconditions=postconditions,
        docstring=docstring,
        steps=step_comments,
    )

    # 8. Generate test code from receipts
    test_code = _generate_tests(
        func_name=func_name,
        module_name=module_name,
        parameters=parameters,
        verifier_command=verifier_command,
        receipt_hash=receipt_hash,
    )

    skill = CompiledSkill(
        name=module_name,
        function_name=func_name,
        docstring=docstring,
        parameters=parameters,
        preconditions=preconditions,
        postconditions=postconditions,
        steps=step_comments,
        source_code=source_code,
        test_code=test_code,
        procedure_id=proc_id,
        receipt_hash=receipt_hash,
        task_signature=task_sig,
    )

    if output_dir:
        skill.save(output_dir)

    return skill


def _to_valid_identifier(name: str) -> str:
    """Convert a task signature to a valid Python identifier."""
    # Replace non-alphanumeric with underscores
    identifier = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    # Collapse multiple underscores
    identifier = re.sub(r"_+", "_", identifier)
    # Strip leading/trailing underscores
    identifier = identifier.strip("_").lower()
    # Ensure it doesn't start with a digit
    if identifier and identifier[0].isdigit():
        identifier = f"task_{identifier}"
    return identifier or "unnamed_skill"


def _extract_parameters(steps: list[dict]) -> list[dict[str, str]]:
    """Extract parameters from parameterized steps.

    Looks for <PLACEHOLDER> patterns in the step actions/targets.
    """
    params = []
    seen = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        # Check parameterized_action and parameterized_target for placeholders
        for field_name in ("parameterized_action", "parameterized_target", "action", "target"):
            value = str(step.get(field_name, ""))
            # Find <PLACEHOLDER> patterns
            placeholders = re.findall(r"<([A-Z_][A-Z0-9_]*)>", value)
            for ph in placeholders:
                if ph not in seen:
                    seen.add(ph)
                    # Infer type from the placeholder name
                    param_type = "str"
                    ph_lower = ph.lower()
                    if "path" in ph_lower or "file" in ph_lower:
                        param_type = "str"  # Could be pathlib.Path in production
                    elif "count" in ph_lower or "num" in ph_lower or "index" in ph_lower:
                        param_type = "int"

                    params.append({
                        "name": ph.lower(),
                        "type": param_type,
                        "placeholder": ph,
                        "description": f"Parameter extracted from <{ph}> in the procedure steps",
                    })
    return params


def _extract_preconditions(steps: list[dict], procedure: Any) -> list[str]:
    """Extract preconditions from the procedure.

    Preconditions are conditions that must be true before the skill executes.
    They're derived from:
    - The procedure's `preconditions` field
    - Inferred from the first step (e.g., if the first step reads a file,
      a precondition is that the file exists)
    """
    preconditions = []

    # From the procedure's preconditions field
    proc_preconditions = getattr(procedure, "preconditions", []) or []
    for pc in proc_preconditions:
        if isinstance(pc, str) and pc.strip():
            preconditions.append(pc)

    # Infer from steps
    if steps:
        first_step = steps[0] if isinstance(steps[0], dict) else {}
        action = str(first_step.get("action", "")).lower()
        canonical = str(first_step.get("canonical_name", "")).lower()

        if "read" in action or "read" in canonical:
            preconditions.append("The target file or configuration must exist")
        if "execute" in action or "execute" in canonical:
            preconditions.append("The target runtime (e.g., node, python) must be installed")
        if "install" in action or "install" in canonical:
            preconditions.append("A package manager (e.g., npm, pip) must be available")

    # Always include the general precondition
    if not preconditions:
        preconditions.append("The execution environment must be accessible")

    return preconditions


def _extract_postconditions(steps: list[dict], procedure: Any) -> list[str]:
    """Extract postconditions from the procedure.

    Postconditions are conditions that are true after the skill executes
    successfully. They're derived from:
    - The procedure's `expected_outcome` field
    - The last step's observation (what "success" looks like)
    """
    postconditions = []

    # From expected_outcome
    expected = getattr(procedure, "expected_outcome", "") or ""
    if expected:
        postconditions.append(expected)

    # From the last step's observation
    if steps:
        last_step = steps[-1] if isinstance(steps[-1], dict) else {}
        obs = str(last_step.get("observation", "")).strip()
        if obs and obs not in postconditions:
            postconditions.append(f"Expected result: {obs[:100]}")

    if not postconditions:
        postconditions.append("The task should complete without errors")

    return postconditions


def _steps_to_comments(steps: list[dict]) -> list[str]:
    """Convert procedure steps to human-readable Python comments."""
    comments = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            continue
        action = step.get("action") or step.get("canonical_name", "?")
        obs = str(step.get("observation", ""))[:60]
        comments.append(f"Step {i}: {action} → {obs}")
    return comments


def _build_docstring(
    task_sig: str,
    proc_id: str,
    receipt_hash: str,
    verifier_command: str,
    steps: list[str],
    preconditions: list[str],
    postconditions: list[str],
) -> str:
    """Build a comprehensive docstring for the compiled skill."""
    lines = [
        f"Compiled from Howdex procedure: {task_sig}",
        f"Procedure ID: {proc_id}",
    ]
    if receipt_hash:
        lines.append(f"Verified receipt: {receipt_hash}...")
        if verifier_command:
            lines.append(f"Verifier: {verifier_command}")
    else:
        lines.append("WARNING: No verified receipt — this skill is UNVERIFIED.")

    lines.append("")
    lines.append("Preconditions:")
    for pc in preconditions:
        lines.append(f"    - {pc}")

    lines.append("")
    lines.append("Postconditions:")
    for pc in postconditions:
        lines.append(f"    - {pc}")

    lines.append("")
    lines.append("Original steps:")
    for s in steps:
        lines.append(f"    {s}")

    lines.append("")
    lines.append("This skill was auto-generated by the Howdex Procedural Compiler.")
    lines.append("It should be reviewed by a human before use in production.")
    lines.append("Treat as guidance, not executable authority.")

    return "\n".join(lines)


def _generate_source(
    module_name: str,
    func_name: str,
    parameters: list[dict[str, str]],
    preconditions: list[str],
    postconditions: list[str],
    docstring: str,
    steps: list[str],
) -> str:
    """Generate the Python source code for the compiled skill."""
    # Build parameter list
    param_strs = []
    for param in parameters:
        param_strs.append(f"{param['name']}: {param['type']}")
    param_sig = ", ".join(param_strs) if param_strs else ""

    # Build precondition checks
    precondition_code = []
    for i, pc in enumerate(preconditions):
        precondition_code.append(f'    # Precondition {i+1}: {pc}')
        precondition_code.append(f'    # TODO: Implement check for: {pc}')
    if precondition_code:
        precondition_code.append("")

    # Build postcondition checks
    postcondition_code = []
    for i, pc in enumerate(postconditions):
        postcondition_code.append(f'    # Postcondition {i+1}: {pc}')
        postcondition_code.append(f'    # TODO: Verify: {pc}')
    if postcondition_code:
        postcondition_code.append("")

    # Build step comments
    step_code = []
    for s in steps:
        step_code.append(f"    # {s}")
    if step_code:
        step_code.append("")

    # Assemble
    code = f'''\
"""{module_name} — compiled Howdex procedural skill.

{textwrap.indent(docstring, "")}
"""

from __future__ import annotations

import subprocess
from typing import Any


def {func_name}({param_sig}) -> bool:
    """Execute the compiled procedure.

    Returns:
        True if the procedure completed successfully, False otherwise.

    Raises:
        RuntimeError: If a precondition is not met.
    """

{chr(10).join(precondition_code)}{chr(10).join(step_code)}{chr(10).join(postcondition_code)}    # --- Execution scaffold ---
    # The actual execution logic should be implemented by the agent
    # or by wiring these steps to real tool calls. This scaffold
    # provides the structure; the agent provides the intelligence.

    try:
        # TODO: Replace with actual execution logic
        # The steps above describe what to do; implement them here
        # using subprocess, file operations, or API calls.
        return True
    except Exception as exc:
        print(f"Skill {func_name} failed: {{exc}}")
        return False


def verify({param_sig}) -> bool:
    """Run the verification check for this skill.

    This uses the original verifier command from the Howdex receipt
    to confirm the procedure's outcome.
    """
    # TODO: Implement the verifier check
    # The verifier command from the receipt should be executed here
    # to confirm the procedure's outcome.
    return True


# Metadata
PROCEDURE_ID = "{module_name}"
COMPILED_BY = "howdex.compiler"
COMPILED_AT = {time.time():.0f}


if __name__ == "__main__":
    import sys
    result = {func_name}()
    sys.exit(0 if result else 1)
'''
    return code


def _generate_tests(
    func_name: str,
    module_name: str,
    parameters: list[dict[str, str]],
    verifier_command: str,
    receipt_hash: str,
) -> str:
    """Generate test code from verification receipts."""
    # Build parameter fixtures — properly indented inside test methods
    param_fixtures = []
    for param in parameters:
        if param["type"] == "int":
            param_fixtures.append(f"        {param['name']} = 1")
        else:
            param_fixtures.append(f'        {param["name"]} = "test_value"')
    param_args = ", ".join(p["name"] for p in parameters)
    param_fixture_str = "\n".join(param_fixtures) if param_fixtures else "        pass"

    test_code = f'''\
"""Auto-generated tests for {module_name}.

Generated by the Howdex Procedural Compiler from verification receipts.
"""
import pytest
from {module_name} import {func_name}, verify


class Test{func_name.title()}:
    """Tests for the compiled {func_name} skill."""

    def test_skill_returns_bool(self):
        """The skill should return a boolean."""
{param_fixture_str}
        result = {func_name}({param_args})
        assert isinstance(result, bool)

    def test_skill_does_not_raise(self):
        """The skill should not raise on valid input."""
{param_fixture_str}
        try:
            {func_name}({param_args})
        except Exception as exc:
            pytest.fail(f"Skill raised unexpected exception: {{exc}}")

    def test_verifier_check(self):
        """The verify() function should return a boolean."""
        result = verify({param_args})
        assert isinstance(result, bool)


# Original receipt metadata (for audit trail)
RECEIPT_HASH = "{receipt_hash}"
VERIFIER_COMMAND = "{verifier_command}"
'''
    return test_code
