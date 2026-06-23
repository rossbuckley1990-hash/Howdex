"""Generic trace-derived operational guidance tests."""

from __future__ import annotations

import ast
from pathlib import Path

from howdex.core.guidance import (
    render_agent_guidance,
    suggest_procedures,
)
from howdex.core.types import Procedure


def _trace_evidence() -> list[dict]:
    return [
        {
            "episode_id": "teacher-episode",
            "outcome": "success",
            "steps": [
                {
                    "tool_name": "execute_fs_write",
                    "tool_args": {
                        "file_path": "decrypt.py",
                        "content": (
                            "import hashlib\n"
                            "def decrypt():\n"
                            "    seed = Path('seed.txt').read_text()\n"
                            "    digest = hashlib.sha256("
                            "seed[::-1].encode()).hexdigest()\n"
                        ),
                    },
                    "observation": "wrote decrypt.py",
                },
                {
                    "tool_name": "execute_bash",
                    "tool_args": {
                        "cmd": "cat seed.txt | rev | printf %s",
                    },
                    "observation": (
                        "FATAL: invalid Bash translation; command failed"
                    ),
                },
                {
                    "tool_name": "execute_bash",
                    "tool_args": {
                        "cmd": (
                            'printf %s "$(cat seed.txt | rev)" | '
                            "shasum -a 256 | awk '{print $1}'"
                        ),
                    },
                    "observation": "calculated digest",
                },
                {
                    "tool_name": "execute_bash",
                    "tool_args": {
                        "cmd": (
                            "openssl enc -d -aes-256-cbc -pbkdf2 "
                            "-in vault.enc -pass pass:<hash>"
                        ),
                    },
                    "observation": (
                        "SUCCESS: decrypted TARGET:EXAMPLE"
                    ),
                },
            ],
        }
    ]


def _procedure() -> Procedure:
    return Procedure(
        id="trace-procedure",
        task_signature="decrypt vault from seed",
        steps=[
            {
                "canonical_name": "execute_fs_write",
                "parameterized_args": {
                    "file_path": "<FILE_PATH_1>",
                    "content": "<CONTENT_1>",
                },
            },
            {
                "canonical_name": "execute_file",
                "parameterized_args": {
                    "cmd": "python3 <FILE_PATH_1>",
                },
            },
        ],
        success_rate=1.0,
        support_count=1,
        success_count=1,
        confidence=0.9,
        raw_supporting_examples=_trace_evidence(),
        source_episode_ids=["teacher-episode"],
    )


def test_trace_derived_facts_render_full_operational_structure():
    suggestion = suggest_procedures(
        [_procedure()],
        "decrypt vault from seed",
    )[0]

    guidance = render_agent_guidance(
        [suggestion],
        objective="Decrypt the current vault",
        include_source=False,
    )

    assert "read seed.txt" in guidance
    assert "reverse the input before hashing or decoding" in guidance
    assert (
        "calculate the SHA256 hex digest of the transformed input"
        in guidance
    )
    assert "hash bytes exactly; do not add a trailing newline" in guidance
    assert "decrypt with OpenSSL AES-256-CBC" in guidance
    assert "include -pbkdf2" in guidance
    assert (
        "use the derived digest as the OpenSSL password via "
        "-pass pass:<hash>"
    ) in guidance
    assert (
        "success requires revealing the expected TARGET string"
        in guidance
    )
    assert "read vault.enc" not in guidance


def test_trace_derived_guidance_renders_binding_aware_data_flow():
    suggestion = suggest_procedures(
        [_procedure()],
        "decrypt vault from seed",
    )[0]

    guidance = render_agent_guidance(
        [suggestion],
        objective="Decrypt the current vault",
        include_source=False,
    )

    assert "Data flow:" in guidance
    assert (
        "Use the contents of seed.txt as the password seed"
        in guidance
    )
    assert (
        "Reverse the contents of seed.txt before hashing"
        in guidance
    )
    assert (
        "Use that SHA256 hex digest as the OpenSSL password"
        in guidance
    )
    assert "Decrypt vault.enc with AES-256-CBC and PBKDF2" in guidance
    assert "For Bash:" in guidance
    assert (
        'printf %s "$(cat seed.txt | rev)" | sha256sum | '
        "awk '{print $1}'"
    ) in guidance
    assert "Do not hash the literal filename vault.enc" in guidance
    assert (
        "Do not hash the encrypted vault.enc bytes as the password seed"
        in guidance
    )


def test_include_source_false_excludes_python_source():
    suggestion = suggest_procedures(
        [_procedure()],
        "decrypt vault from seed",
    )[0]

    guidance = render_agent_guidance(
        [suggestion],
        include_source=False,
    )

    assert "import hashlib" not in guidance
    assert "def decrypt" not in guidance
    assert "```python" not in guidance
    assert "decrypt.py" not in guidance
    assert "Source artifacts excluded" in guidance


def test_failed_commands_are_separate_and_bash_correction_is_explicit():
    suggestion = suggest_procedures(
        [_procedure()],
        "decrypt vault from seed",
    )[0]

    guidance = render_agent_guidance(
        [suggestion],
        include_source=False,
    )

    avoid_section = guidance.split(
        "Avoid these failed attempts:",
        1,
    )[1].split("Verification:", 1)[0]
    assert "cat seed.txt | rev | printf %s" in avoid_section
    assert "Do not pipe into printf; printf does not read stdin." in (
        avoid_section
    )
    assert (
        'printf %s "$(cat seed.txt | rev)"'
        in avoid_section
    )
    facts_section = guidance.split(
        "Learned operational facts:",
        1,
    )[1].split("Source artifacts excluded:", 1)[0]
    assert "run `cat seed.txt | rev | printf %s`" not in facts_section


def test_trace_evidence_is_available_to_renderer_but_not_public_dict():
    suggestion = suggest_procedures(
        [_procedure()],
        "decrypt vault from seed",
    )[0]

    assert suggestion.trace_evidence == _trace_evidence()
    assert "trace_evidence" not in suggestion.to_dict()


def test_trace_derived_guidance_is_deterministic():
    suggestion = suggest_procedures(
        [_procedure()],
        "decrypt vault from seed",
    )[0]

    first = render_agent_guidance(
        [suggestion],
        objective="Decrypt the current vault",
        include_source=False,
    )
    second = render_agent_guidance(
        [suggestion],
        objective="Decrypt the current vault",
        include_source=False,
    )

    assert first == second


def test_no_synthesis_benchmark_keeps_strict_native_path():
    source_path = (
        Path(__file__).resolve().parents[1]
        / "polyglot_macgyver_nosynth_test.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    guidance_function = functions["native_procedure_guidance"]
    calls = [
        node
        for node in ast.walk(guidance_function)
        if isinstance(node, ast.Call)
    ]
    assert any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "suggest_procedure"
        for call in calls
    )
    render_calls = [
        call
        for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id == "render_agent_guidance"
    ]
    assert len(render_calls) == 1
    include_source = next(
        keyword.value
        for keyword in render_calls[0].keywords
        if keyword.arg == "include_source"
    )
    assert isinstance(include_source, ast.Constant)
    assert include_source.value is False
    assert "memory.learn(min_samples=1)" in source
    assert "learned_facts" not in source
