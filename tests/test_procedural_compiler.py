"""Tests for the procedural compiler — trajectories → typed skills."""

import ast
import importlib.util
import tempfile
from pathlib import Path

import pytest

from howdex import Howdex, compile_procedure, CompiledSkill


def _seed_verified_procedure(mem):
    """Seed a verified procedure and return it."""
    mem.start_session("fix_missing_dependency")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "Error: Cannot find module 'express'")
    mem.log_tool_call("execute_bash", {"cmd": "npm install express"}, "added packages")
    mem.log_tool_call("execute_bash", {"cmd": "node app.js"}, "App running")
    mem.end_session("success")
    procs = mem.learn(min_samples=1)
    assert procs
    proc = procs[0]
    mem.verify_procedure(
        procedure_id=proc.id,
        verifier_type="bash",
        verifier_command="node app.js | grep -q 'App running'",
        expected_signal="App running",
        observed_signal="App running",
        exit_code=0,
    )
    return proc


def test_compile_produces_valid_python(tmp_path):
    """The compiled skill should be valid, importable Python."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc, output_dir=str(tmp_path / "skills"))

        # The source code should be valid Python
        ast.parse(skill.source_code)

        # The file should exist
        assert (tmp_path / "skills" / f"{skill.name}.py").exists()
    finally:
        mem.close()


def test_compiled_skill_has_function(tmp_path):
    """The compiled skill should define a function with the right name."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc)

        # Parse the AST and find the function
        tree = ast.parse(skill.source_code)
        func_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert skill.function_name in func_names
        assert "verify" in func_names
    finally:
        mem.close()


def test_compiled_skill_has_preconditions(tmp_path):
    """The compiled skill should include preconditions."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc)

        assert len(skill.preconditions) > 0
        # Should mention the runtime since the first step executes
        assert any("runtime" in pc.lower() or "execute" in pc.lower() or "environment" in pc.lower()
                   for pc in skill.preconditions)
    finally:
        mem.close()


def test_compiled_skill_has_postconditions(tmp_path):
    """The compiled skill should include postconditions."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc)

        assert len(skill.postconditions) > 0
    finally:
        mem.close()


def test_compiled_skill_has_receipt_hash(tmp_path):
    """The compiled skill should include the verification receipt hash."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc)

        assert skill.receipt_hash  # non-empty
        assert len(skill.receipt_hash) >= 12
    finally:
        mem.close()


def test_compiled_skill_generates_tests(tmp_path):
    """The compiled skill should generate test code from receipts."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc)

        assert skill.test_code
        # Test code should be valid Python
        ast.parse(skill.test_code)
        # Should include the function name
        assert skill.function_name in skill.test_code
        assert "verify" in skill.test_code
    finally:
        mem.close()


def test_compiled_skill_saves_metadata(tmp_path):
    """Saving a skill should produce a .py file, test file, and metadata JSON."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc, output_dir=str(tmp_path / "skills"))

        skills_dir = tmp_path / "skills"
        assert (skills_dir / f"{skill.name}.py").exists()
        assert (skills_dir / f"test_{skill.name}.py").exists()
        assert (skills_dir / f"{skill.name}.meta.json").exists()

        # Metadata should be valid JSON
        import json
        meta = json.loads((skills_dir / f"{skill.name}.meta.json").read_text())
        assert meta["name"] == skill.name
        assert meta["procedure_id"] == skill.procedure_id
        assert meta["receipt_hash"] == skill.receipt_hash
    finally:
        mem.close()


def test_compiled_skill_is_importable(tmp_path):
    """The compiled .py file should be importable as a Python module."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        proc = _seed_verified_procedure(mem)
        skill = compile_procedure(mem, proc, output_dir=str(tmp_path / "skills"))

        # Import the module
        skills_dir = tmp_path / "skills"
        module_path = skills_dir / f"{skill.name}.py"

        spec = importlib.util.spec_from_file_location(skill.name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # The function should exist
        assert hasattr(module, skill.function_name)
        func = getattr(module, skill.function_name)

        # Calling it should return a bool — pass the extracted parameters
        params = [p["name"] for p in skill.parameters]
        if params:
            args = ["test_value" for _ in params]
            result = func(*args)
        else:
            result = func()
        assert isinstance(result, bool)

        # The verify function should also exist
        assert hasattr(module, "verify")
    finally:
        mem.close()


def test_function_name_is_valid_identifier(tmp_path):
    """The function name should be a valid Python identifier."""
    from howdex.compiler import _to_valid_identifier

    assert _to_valid_identifier("fix_missing_dependency") == "fix_missing_dependency"
    assert _to_valid_identifier("Fix Missing Dep!") == "fix_missing_dep"
    assert _to_valid_identifier("123start") == "task_123start"
    assert _to_valid_identifier("") == "unnamed_skill"
    assert _to_valid_identifier("a-b-c") == "a_b_c"


def test_parameters_extracted_from_placeholders(tmp_path):
    """Parameters should be extracted from <PLACEHOLDER> patterns in steps."""
    from howdex.compiler import _extract_parameters

    steps = [
        {"action": "run node <FILE_PATH_1>", "parameterized_action": "run node <FILE_PATH_1>"},
        {"action": "npm install <PKG_1>", "parameterized_action": "npm install <PKG_1>"},
        {"action": "run node <FILE_PATH_1>", "parameterized_action": "run node <FILE_PATH_1>"},
    ]
    params = _extract_parameters(steps)
    assert len(params) == 2  # FILE_PATH_1 and PKG_1
    names = [p["name"] for p in params]
    assert "file_path_1" in names
    assert "pkg_1" in names
