"""
Real MacGyver A/B Hard Tool Benchmark

Purpose:
    Measure whether Howdex memory improves a student agent's success rate on a
    hard real-filesystem tool-reuse task versus a no-memory control arm.

This is intentionally different from real_macgyver_test.py.

real_macgyver_test.py proves:
    - Howdex can preserve and re-surface a source-code artifact.
    - A student can recreate and run that artifact on disk.

This benchmark asks a stronger question:
    - Does Howdex memory improve capability versus a no-memory baseline?

Rules:
    - Real temp filesystem.
    - Real binary files.
    - Real subprocess execution.
    - Same student model for control and treatment.
    - N trials per arm.
    - Treatment receives operational memory, not pasted source code.
    - PASS only if treatment success rate is higher than control.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_openai import get_openai_client

from howdex import Howdex
from howdex.core.guidance import render_agent_guidance


DB_PATH = ".howdex_real_macgyver_ab.db"

TEACHER_MODEL = os.getenv("HOWDEX_AB_TEACHER_MODEL", "gpt-4o")
STUDENT_MODEL = os.getenv("HOWDEX_AB_STUDENT_MODEL", "gpt-4o-mini")
N_TRIALS = int(os.getenv("HOWDEX_AB_TRIALS", "3"))
MAX_AGENT_TURNS = int(os.getenv("HOWDEX_AB_MAX_TURNS", "15"))

_CLIENT = None


def _openai_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = get_openai_client()
    return _CLIENT


@dataclass
class AgentResult:
    label: str
    success: bool
    extracted: str | None
    attempts: int
    actions: list[tuple[str, str]]
    used_howdex_memory: bool
    guidance_source_pasted: bool


def reset_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(DB_PATH + suffix)
        if p.exists():
            p.unlink()


def make_zb2(path: Path, value: int, *, key: int, offset: int, tag: str) -> None:
    """Create a deliberately awkward local binary-ish format.

    Layout:
        0..3    magic: b"ZB2!"
        4       xor key
        5       payload offset
        6       payload length
        7..     decoy/filler
        offset  encoded payload
        end     checksum byte

    Payload rule:
        plain = b"TARGET:<value>;TAG:<tag>;END"
        encoded = reverse(plain) XOR key
        checksum = sum(plain) % 251

    The file also contains misleading decoy text so naive string extraction is
    likely to pick the wrong value.
    """
    plain = f"TARGET:{value};TAG:{tag};END".encode("utf-8")
    encoded = bytes((b ^ key) for b in plain[::-1])
    checksum = sum(plain) % 251

    header = b"ZB2!" + bytes([key, offset, len(encoded)])

    filler = bytearray()
    filler.extend(b"DECOY TARGET:0000;")
    filler.extend(b"VAL=1111;")
    filler.extend(b"TARGET=2222;")
    filler.extend(b"not-the-answer;")

    while len(header) + len(filler) < offset:
        filler.extend(b"\x13JUNK\x00")

    filler = filler[: max(0, offset - len(header))]

    blob = header + bytes(filler) + encoded + bytes([checksum]) + b";TAIL TARGET:3333"
    path.write_bytes(blob)


def create_sandbox(prefix: str, value: int) -> Path:
    sandbox = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    make_zb2(
        sandbox / "challenge.zb2",
        value,
        key=0x5A,
        offset=47,
        tag="OMEGA",
    )
    return sandbox


def safe_path(workdir: Path, file_path: str) -> Path:
    candidate = (workdir / file_path).resolve()
    root = workdir.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Unsafe path outside sandbox: {file_path}")
    return candidate


def execute_fs_write(workdir: Path, file_path: str, content: str) -> str:
    allowed = {"decoder.py", "probe.py", "notes.txt"}
    if file_path not in allowed:
        return f"FATAL: only these files may be written: {sorted(allowed)}"

    target = safe_path(workdir, file_path)
    target.write_text(content)

    preview = content[:140].replace("\n", " ")
    print(f"[FS_WRITE] {file_path}: {preview}...")
    return f"wrote {file_path}"


def execute_bash(workdir: Path, cmd: str, expected_value: int) -> str:
    print(f"[EXEC] {cmd}")

    allowed = {
        "python3 decoder.py challenge.zb2",
        "python3 probe.py challenge.zb2",
    }

    if cmd not in allowed:
        return (
            "FATAL: command not allowed. Allowed commands are exactly: "
            "python3 decoder.py challenge.zb2 or python3 probe.py challenge.zb2"
        )

    script_name = cmd.split()[1]
    data_name = cmd.split()[2]

    script_path = safe_path(workdir, script_name)
    data_path = safe_path(workdir, data_name)

    if not script_path.exists():
        return f"FATAL: {script_name} does not exist"
    if not data_path.exists():
        return f"FATAL: {data_name} does not exist"

    try:
        result = subprocess.run(
            ["python3", str(script_path), str(data_path)],
            cwd=str(workdir),
            text=True,
            capture_output=True,
            timeout=4,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "FATAL: process timed out"

    output = (result.stdout + result.stderr).strip()

    if result.returncode != 0:
        return f"FATAL: exited {result.returncode}. Output: {output}"

    if script_name == "decoder.py":
        if str(expected_value) not in output:
            return f"FATAL: decoder returned wrong value. Expected {expected_value}. Got: {output}"
        return f"SUCCESS: decoded TARGET {expected_value}"

    # probe.py is allowed to print observations, but truncate to avoid dumping
    # the whole file as a shortcut.
    return output[:3000] if output else "probe produced no output"


def extract_raw_examples_from_sqlite() -> list[dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM procedures")]
    finally:
        conn.close()

    examples: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get("raw_examples")
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        if isinstance(parsed, list):
            examples.extend(x for x in parsed if isinstance(x, dict))

    return examples


def source_pasted_in_guidance(guidance: str) -> bool:
    """Detect decoder-source leakage conservatively in treatment guidance."""
    patterns = (
        r"```",
        r"(?m)^\s*(?:from\s+\S+\s+import\s+|import\s+\S+)",
        r"(?m)^\s*(?:async\s+)?def\s+\w+\s*\(",
        r"(?m)^\s*class\s+\w+",
        r"(?m)^\s*#!.*python",
        r"\bopen\s*\(",
        r"\bread_bytes\s*\(",
        r"\bread_text\s*\(",
        r"\bsys\.argv\b",
        r"\bPath\s*\(",
        r"\bbytes\s*\(\s*\([^)]*\^",
    )
    return any(re.search(pattern, guidance) for pattern in patterns)


def build_howdex_operational_memory(memory: Howdex) -> tuple[str, bool, bool]:
    """Return non-source operational memory.

    This deliberately does not paste the teacher's decoder.py source.

    It extracts high-level operational facts from Howdex's stored traces. That
    lets the treatment arm use prior memory without reducing the task to
    literal copy-paste.
    """
    suggestions = memory.suggest_procedure(
        "Decode challenge.zb2 and extract the hidden TARGET value.",
        top_k=5,
        min_confidence=0.0,
    )

    raw_examples = extract_raw_examples_from_sqlite()

    observed_decoder_source = ""
    observed_success = False
    observed_failed_attempts: list[str] = []

    for example in raw_examples:
        for step in example.get("steps", []) or []:
            if not isinstance(step, dict):
                continue

            tool_name = str(step.get("tool_name") or step.get("action") or "")
            args = step.get("tool_args") or step.get("args") or {}
            observation = str(step.get("observation") or step.get("output") or "")

            if not isinstance(args, dict):
                args = {}

            if tool_name == "execute_fs_write" and args.get("file_path") == "decoder.py":
                observed_decoder_source += "\n" + str(args.get("content") or "")

            if "SUCCESS: decoded TARGET" in observation:
                observed_success = True

            if "FATAL" in observation:
                cmd = args.get("cmd")
                if cmd:
                    observed_failed_attempts.append(str(cmd))

    source_lower = observed_decoder_source.lower()

    # The treatment memory is intentionally operational, not source code.
    learned_facts: list[str] = []

    if "b'zb2!'" in source_lower or '"zb2!"' in source_lower or "zb2!" in source_lower:
        learned_facts.append("check the first four bytes for magic ZB2!")

    if "data[4]" in source_lower or "[4]" in source_lower or "key" in source_lower:
        learned_facts.append("byte 4 is the XOR key")

    if "data[5]" in source_lower or "[5]" in source_lower or "offset" in source_lower:
        learned_facts.append("byte 5 is the payload offset")

    if "data[6]" in source_lower or "[6]" in source_lower or "length" in source_lower:
        learned_facts.append("byte 6 is the encoded payload length")

    if "[::-1]" in source_lower or "reverse" in source_lower or "reversed" in source_lower:
        learned_facts.append("the encoded payload must be reversed before/after XOR decoding")

    if "^" in source_lower or "xor" in source_lower:
        learned_facts.append("payload bytes are XOR-decoded using the dynamic key from byte 4")

    if "% 251" in source_lower or "checksum" in source_lower:
        learned_facts.append("validate checksum as sum(decoded_payload) % 251 against the trailing checksum byte")

    if "target:" in source_lower:
        learned_facts.append("extract the integer after TARGET: from the decoded text")

    if not learned_facts and suggestions:
        learned_facts.append("prior Howdex memory indicates this is a binary decode task, not plain text extraction")

    has_memory = bool(suggestions) and observed_success and bool(learned_facts)

    primary = suggestions[0] if suggestions else None
    payload = {
        "task_signature": (
            getattr(primary, "task_signature", None)
            or "hard ZB2 decoder transfer"
        ),
        "confidence": getattr(primary, "confidence", None),
        "support_count": getattr(primary, "support_count", None),
        "learned_facts": learned_facts,
        "failed_attempts": sorted(set(observed_failed_attempts)),
        "verification": [
            "Write a fresh decoder.py for the current challenge.",
            "Run exactly: python3 decoder.py challenge.zb2.",
            "Only mark done after the real verifier reports SUCCESS.",
            "The decoder output must contain the true hidden TARGET integer.",
        ],
    }
    rendered = render_agent_guidance(
        [payload],
        objective="Decode challenge.zb2 and extract the hidden TARGET integer.",
        constraints=[
            "Do not copy or paste a previous decoder implementation.",
            "Write a fresh decoder.py for the current challenge file.",
            "Treat readable TARGET and VAL strings as decoys.",
        ],
        target_environment="restricted Python filesystem tool sandbox",
        include_source=False,
        include_failed_attempts=True,
        include_verification=True,
    )

    return rendered, has_memory, source_pasted_in_guidance(rendered)


def run_agent(
    *,
    label: str,
    workdir: Path,
    expected_value: int,
    memory: Howdex | None,
    record_to_memory: bool,
    use_howdex_memory: bool,
    model: str,
    temperature: float,
) -> AgentResult:
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    used_howdex_memory = False
    guidance_source_pasted = False
    memory_guidance = ""

    if use_howdex_memory:
        assert memory is not None
        memory_guidance, used_howdex_memory, guidance_source_pasted = build_howdex_operational_memory(memory)
        print("\n[HOWDEX OPERATIONAL MEMORY]")
        print(memory_guidance)
        print(f"[HOWDEX MEMORY AVAILABLE]: {used_howdex_memory}")
        print(f"[HOWDEX SOURCE PASTED]: {guidance_source_pasted}")

    if record_to_memory:
        assert memory is not None
        memory.start_session("hard_zb2_decoder_teacher")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_fs_write",
                "description": "Write a file inside the temporary benchmark sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file_path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_bash",
                "description": "Run an allowed Python command inside the temporary benchmark sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string"},
                    },
                    "required": ["cmd"],
                },
            },
        },
    ]

    base_task = f"""
You are in a restricted temporary filesystem.

Task:
Decode challenge.zb2 and extract the hidden TARGET integer.

You may write:
- probe.py
- decoder.py
- notes.txt

You may run only:
- python3 probe.py challenge.zb2
- python3 decoder.py challenge.zb2

Important:
- challenge.zb2 is not a plain text file.
- Naive strings like VAL=1111, TARGET=2222, or TARGET:3333 are decoys.
- If you output a decoy value, the verifier will reject it.
- You must make decoder.py output the true hidden TARGET.
- The verifier expects {expected_value}.
- You cannot mark DONE until execute_bash returns SUCCESS.
"""

    if use_howdex_memory:
        system_prompt = base_task + "\n\n" + memory_guidance
    elif record_to_memory:
        system_prompt = (
            base_task
            + """

You are the teacher run. Explore the binary format if needed.

Teacher-only exploration scaffold:
- Start with probe.py and inspect raw bytes, byte indexes, and integer byte values.
- Treat the first bytes as a possible compact header.
- If the file starts with b"ZB2!", test this hypothesis:
  - data[4] may be a dynamic XOR key.
  - data[5] may be the payload offset.
  - data[6] may be the encoded payload length.
  - payload may be data[offset:offset+length].
  - decoded candidate may be bytes(b ^ key for b in payload)[::-1].
- Print the key, offset, length, encoded payload bytes, decoded candidate repr, and nearby trailing byte.
- Decoys are present in readable text; do not trust plain visible TARGET/VAL strings.
- The true decoded text should contain TARGET:<number>.
- If there is a trailing validation byte, test checksum = sum(decoded_payload) % 251.
- Once you discover the format, write a robust decoder.py and verify it with the allowed command.

This teacher scaffold is not given to the control or treatment student arms.
Record a robust decoder.py once you discover the format.
"""
        )
    else:
        system_prompt = base_task + "\n\nNo prior memory is available."

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    actions: list[tuple[str, str]] = []
    attempts = 0
    success = False
    extracted: str | None = None

    for _turn in range(MAX_AGENT_TURNS):
        response = _openai_client().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content and message.content.strip().upper().startswith("DONE"):
            if success:
                print("[DONE accepted]")
                break

            print("[DONE rejected: verifier has not succeeded]")
            messages.append(
                {
                    "role": "user",
                    "content": "DONE is rejected. You must run decoder.py and receive SUCCESS from the verifier first.",
                }
            )
            continue

        if not message.tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Continue using tool calls. Write/probe/decode until the verifier reports SUCCESS.",
                }
            )
            continue

        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments)

            if tool_call.function.name == "execute_fs_write":
                output = execute_fs_write(workdir, args["file_path"], args["content"])
                actions.append(("fs_write", args["file_path"]))

                if record_to_memory:
                    assert memory is not None
                    memory.log_tool_call(
                        "execute_fs_write",
                        {"file_path": args["file_path"], "content": args["content"]},
                        output,
                    )

            elif tool_call.function.name == "execute_bash":
                attempts += 1
                output = execute_bash(workdir, args["cmd"], expected_value)
                actions.append(("bash", args["cmd"]))

                if record_to_memory:
                    assert memory is not None
                    memory.log_tool_call(
                        "execute_bash",
                        {"cmd": args["cmd"]},
                        output,
                    )

                if f"SUCCESS: decoded TARGET {expected_value}" in output:
                    success = True
                    extracted = str(expected_value)

            else:
                output = "FATAL: unknown tool"

            print(f"[OUTPUT] {output}")

            # Keep model context small. The full output is printed to terminal,
            # but the chat loop only needs the verifier result and a compact
            # diagnostic summary.
            chat_output = output
            if len(chat_output) > 1200:
                chat_output = chat_output[:1200] + "\n...[truncated in chat context]"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": chat_output,
                }
            )

        # The real verifier has succeeded. Stop immediately rather than asking
        # the model for another turn just to say DONE.
        if success:
            print("[VERIFIER SUCCESS — stopping agent loop]")
            break

    if record_to_memory:
        assert memory is not None
        memory.end_session("success" if success else "failure")

    return AgentResult(
        label=label,
        success=success,
        extracted=extracted,
        attempts=attempts,
        actions=actions,
        used_howdex_memory=used_howdex_memory,
        guidance_source_pasted=guidance_source_pasted,
    )


def run_teacher(memory: Howdex) -> AgentResult:
    sandbox = create_sandbox("howdex_ab_teacher_", 8642)
    try:
        result = run_agent(
            label="TEACHER — HARD ZB2 DECODER DISCOVERY",
            workdir=sandbox,
            expected_value=8642,
            memory=memory,
            record_to_memory=True,
            use_howdex_memory=False,
            model=TEACHER_MODEL,
            temperature=0.2,
        )

        print("\n[HOWDEX LEARN]")
        procedures = memory.learn(min_samples=1)
        print(f"learned_procedures={len(procedures)}")
        for p in procedures:
            print(f"- {getattr(p, 'task_signature', None)} confidence={getattr(p, 'confidence', None)}")

        return result
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def run_arm(
    *,
    arm_name: str,
    memory: Howdex,
    use_howdex_memory: bool,
    trials: int,
) -> list[AgentResult]:
    results: list[AgentResult] = []

    for i in range(1, trials + 1):
        expected = 9000 + i
        sandbox = create_sandbox(f"howdex_ab_{arm_name.lower()}_{i}_", expected)

        try:
            result = run_agent(
                label=f"{arm_name} TRIAL {i}/{trials}",
                workdir=sandbox,
                expected_value=expected,
                memory=memory,
                record_to_memory=False,
                use_howdex_memory=use_howdex_memory,
                model=STUDENT_MODEL,
                temperature=0.7,
            )
            results.append(result)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    return results


def summarize(results: list[AgentResult]) -> dict[str, Any]:
    successes = sum(1 for r in results if r.success)
    attempts = [r.attempts for r in results]
    memory_used = sum(1 for r in results if r.used_howdex_memory)
    source_pasted = sum(1 for r in results if r.guidance_source_pasted)

    return {
        "trials": len(results),
        "successes": successes,
        "success_rate": successes / max(1, len(results)),
        "avg_attempts": sum(attempts) / max(1, len(attempts)),
        "memory_used": memory_used,
        "source_pasted": source_pasted,
    }


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required to run this benchmark.")

    reset_db()
    memory = Howdex(path=DB_PATH, embedder="hashing")

    teacher = run_teacher(memory)

    if not teacher.success:
        print("\nREAL MACGYVER A/B HARD TOOL BENCHMARK")
        print("teacher_success=false")
        print("verdict=FAIL")
        print("reason=Teacher did not discover a working decoder, so no valid memory can be tested.")
        return

    control = run_arm(
        arm_name="CONTROL_NO_MEMORY",
        memory=memory,
        use_howdex_memory=False,
        trials=N_TRIALS,
    )

    treatment = run_arm(
        arm_name="TREATMENT_HOWDEX_MEMORY",
        memory=memory,
        use_howdex_memory=True,
        trials=N_TRIALS,
    )

    control_summary = summarize(control)
    treatment_summary = summarize(treatment)

    delta = treatment_summary["success_rate"] - control_summary["success_rate"]
    attempt_reduction = control_summary["avg_attempts"] - treatment_summary["avg_attempts"]

    source_not_pasted = treatment_summary["source_pasted"] == 0
    memory_available = treatment_summary["memory_used"] == treatment_summary["trials"]

    pass_condition = (
        teacher.success
        and memory_available
        and source_not_pasted
        and treatment_summary["success_rate"] >= 0.80
        and treatment_summary["success_rate"] > control_summary["success_rate"]
    )

    print("\n" + "=" * 80)
    print("REAL MACGYVER A/B HARD TOOL BENCHMARK")
    print("=" * 80)

    print("\nTeacher:")
    print(f"  success: {teacher.success}")
    print(f"  attempts: {teacher.attempts}")
    print(f"  actions: {teacher.actions}")

    print("\nControl:")
    print(f"  trials: {control_summary['trials']}")
    print(f"  successes: {control_summary['successes']}")
    print(f"  success_rate: {control_summary['success_rate']:.2f}")
    print(f"  avg_attempts: {control_summary['avg_attempts']:.2f}")

    print("\nTreatment:")
    print(f"  trials: {treatment_summary['trials']}")
    print(f"  successes: {treatment_summary['successes']}")
    print(f"  success_rate: {treatment_summary['success_rate']:.2f}")
    print(f"  avg_attempts: {treatment_summary['avg_attempts']:.2f}")
    print(f"  howdex_memory_used: {treatment_summary['memory_used']}/{treatment_summary['trials']}")
    print(f"  source_pasted: {treatment_summary['source_pasted']}/{treatment_summary['trials']}")

    print("\nDelta:")
    print(f"  success_rate_lift: {delta:+.2f}")
    print(f"  attempt_reduction: {attempt_reduction:+.2f}")

    print("\nVerdict:")
    if pass_condition:
        print("  PASS")
        print("  Howdex improved student success on a hard real-filesystem tool-reuse task without pasting source code.")
    else:
        print("  FAIL")
        print("  No defensible capability-lift claim. Inspect control/treatment deltas.")

    print("\nMachine summary:")
    print(
        json.dumps(
            {
                "teacher_success": teacher.success,
                "control": control_summary,
                "treatment": treatment_summary,
                "success_rate_lift": delta,
                "attempt_reduction": attempt_reduction,
                "source_not_pasted": source_not_pasted,
                "memory_available": memory_available,
                "pass": pass_condition,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
