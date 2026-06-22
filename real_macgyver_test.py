import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI
from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance


client = OpenAI()

DB_PATH = ".howdex_real_macgyver.db"
for suffix in ("", "-wal", "-shm"):
    p = Path(DB_PATH + suffix)
    if p.exists():
        p.unlink()

memory = Howdex(path=DB_PATH, embedder="hashing")
LAST_SOURCE_SIGNAL = False


def hydrate_raw_examples_from_sqlite(procedures, db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in conn.execute("SELECT * FROM procedures")]
    finally:
        conn.close()

    for procedure in procedures:
        task_signature = str(getattr(procedure, "task_signature", ""))
        procedure_id = str(getattr(procedure, "procedure_id", "") or getattr(procedure, "id", ""))

        matching_row = None
        for row in rows:
            if procedure_id and procedure_id in {str(row.get("procedure_id", "")), str(row.get("id", ""))}:
                matching_row = row
                break
            if task_signature and task_signature == str(row.get("task_signature", "")):
                matching_row = row
                break

        if not matching_row:
            continue

        raw_examples = matching_row.get("raw_examples")
        if not raw_examples:
            continue

        try:
            parsed = json.loads(raw_examples)
        except Exception:
            parsed = []

        try:
            setattr(procedure, "raw_examples", parsed)
        except Exception:
            try:
                setattr(procedure, "raw_supporting_examples", parsed)
            except Exception:
                pass

    return procedures


def safe_path(workdir: Path, file_path: str) -> Path:
    candidate = (workdir / file_path).resolve()
    root = workdir.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError(f"Unsafe path outside sandbox: {file_path}")
    return candidate


def execute_fs_write(workdir: Path, file_path: str, content: str) -> str:
    print(f"\n[REAL FS WRITE]: {file_path}")
    print(f"[CODE PREVIEW]: {content[:160].replace(chr(10), ' ')}...")

    if file_path != "custom_parser.py":
        return "FATAL: only custom_parser.py may be written in this benchmark."

    target = safe_path(workdir, file_path)
    target.write_text(content)
    return f"File {file_path} written successfully on real filesystem."


def execute_bash(workdir: Path, cmd: str) -> str:
    print(f"\n[REAL EXECUTING]: {cmd}")

    banned = ("cat", "grep", "jq", "awk", "sed", "rm", "curl", "wget", "sh ", "bash ")
    if cmd.strip().split(" ")[0] in banned or any(cmd.startswith(x) for x in banned):
        return "FATAL: banned command in secure benchmark environment."

    parts = cmd.split()
    if len(parts) != 3 or parts[0] != "python3" or parts[1] != "custom_parser.py":
        return "FATAL: only allowed command is python3 custom_parser.py <file>."

    data_file = safe_path(workdir, parts[2])
    parser_file = safe_path(workdir, "custom_parser.py")

    if not parser_file.exists():
        return "FATAL: custom_parser.py does not exist."

    if not data_file.exists():
        return f"FATAL: data file does not exist: {parts[2]}"

    try:
        result = subprocess.run(
            ["python3", str(parser_file), str(data_file)],
            cwd=str(workdir),
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "FATAL: parser timed out."

    output = (result.stdout + result.stderr).strip()

    if result.returncode != 0:
        return f"FATAL: parser exited with {result.returncode}. Output: {output}"

    if not output:
        return "FATAL: parser produced no output."

    expected = "7781" if parts[2] == "data_1.zdat" else "9924"
    if expected not in output:
        return f"FATAL: parser returned wrong value. Expected {expected}. Got: {output}"

    return output


def get_macgyver_guidance() -> str:
    global LAST_SOURCE_SIGNAL
    LAST_SOURCE_SIGNAL = False

    suggestions = memory.suggest_procedure(
        "Extract the VAL from a ZDAT file using a custom parser script.",
        top_k=5,
        min_confidence=0.0,
    )

    if not suggestions:
        print("[HOWDEX] no MacGyver procedure found")
        LAST_SOURCE_SIGNAL = False
        return ""

    all_procedures = memory.list_procedures(min_confidence=0.0, limit=None)
    full_procedures = [
        procedure
        for procedure in all_procedures
        if "parse_custom_data" in str(getattr(procedure, "task_signature", ""))
    ] or all_procedures

    full_procedures = hydrate_raw_examples_from_sqlite(full_procedures)

    print(f"[HOWDEX FULL PROCEDURES FOR RENDERING]: {len(full_procedures)}")
    for procedure in full_procedures:
        print(
            "[HOWDEX FULL PROCEDURE]",
            getattr(procedure, "task_signature", None),
            "raw_examples=",
            bool(getattr(procedure, "raw_examples", None) or getattr(procedure, "raw_supporting_examples", None)),
        )

    howdex_guidance = render_procedure_guidance(
        full_procedures,
        objective="Extract the VAL from a ZDAT file using custom_parser.py.",
        bindings={
            "<FILE_PATH_1>": "custom_parser.py",
            "<SCRIPT_PATH_1>": "custom_parser.py",
        },
    )

    source_signal = (
        "custom_parser.py" in howdex_guidance
        and "VAL=" in howdex_guidance
        and "split" in howdex_guidance
        and "```" in howdex_guidance
    )

    guidance = howdex_guidance + """
# REAL MACGYVER TOOL RE-MANIFESTATION RULE

Use the learned Howdex source-code artifact.
Write `custom_parser.py` exactly from the learned guidance.
Then run `python3 custom_parser.py data_2.zdat`.

Do not use cat, grep, jq, awk, sed, shell scripts, or external network tools.
Reply DONE only after the real Python process extracts value 9924.
"""

    LAST_SOURCE_SIGNAL = source_signal

    print("\n[HOWDEX REAL MACGYVER GUIDANCE]")
    print(guidance)
    print(f"\n[HOWDEX SOURCE-CODE SIGNAL IN GUIDANCE]: {source_signal}")

    return guidance


def run_agent(workdir: Path, label: str, task_signature: str, objective: str, use_memory: bool, model: str) -> dict:
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    guidance = get_macgyver_guidance() if use_memory else ""

    if use_memory:
        system_prompt = f"""You are an autonomous student agent in a restricted real filesystem sandbox.

Objective:
{objective}

Available tools:
- execute_fs_write(file_path, content)
- execute_bash(cmd)

You must use Howdex memory to recreate the parser source.
Do not invent a different parser.
Do not use bash to print DONE.
Reply DONE only after the real Python process extracts the target value.

{guidance}
"""
    else:
        system_prompt = f"""You are an autonomous teacher agent in a restricted real filesystem sandbox.

Objective:
{objective}

Available tools:
- execute_fs_write(file_path, content)
- execute_bash(cmd)

Standard text tools are unavailable.
Write custom_parser.py using execute_fs_write.
The parser must read a filename from argv and extract the value after VAL=.
Then run python3 custom_parser.py data_1.zdat.
Do not use bash to print DONE.
Reply DONE only after the real Python process extracts 7781.
"""

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_fs_write",
                "description": "Write a file inside the benchmark sandbox.",
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
                "description": "Run an allowed command inside the benchmark sandbox.",
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

    memory.start_session(task_signature)

    messages = [{"role": "system", "content": system_prompt}]
    actions = []
    success = False
    extracted = None

    for _ in range(10):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0.0,
        )

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content and message.content.strip().upper().startswith("DONE"):
            if success:
                print(f"\n[FINISHED]: {message.content}")
                memory.end_session("success")
                break

            print(f"\n[REJECTED DONE]: {message.content}")
            messages.append(
                {
                    "role": "user",
                    "content": "You cannot mark DONE yet. The real parser has not returned the expected value. Fix the parser and run the allowed verification command again.",
                }
            )
            continue

        if not message.tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Continue using a tool call, or reply DONE only after successful extraction.",
                }
            )
            continue

        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments)

            if tool_call.function.name == "execute_fs_write":
                output = execute_fs_write(workdir, args["file_path"], args["content"])
                memory.log_tool_call(
                    "execute_fs_write",
                    {"file_path": args["file_path"], "content": args["content"]},
                    output,
                )
                actions.append(("fs_write", args["file_path"]))

            elif tool_call.function.name == "execute_bash":
                output = execute_bash(workdir, args["cmd"])
                memory.log_tool_call(
                    "execute_bash",
                    {"cmd": args["cmd"]},
                    output,
                )
                actions.append(("bash", args["cmd"]))

                if "7781" in output:
                    success = True
                    extracted = "7781"
                if "9924" in output:
                    success = True
                    extracted = "9924"

            else:
                output = "FATAL: unknown tool."

            print(f"[OUTPUT]: {output}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": output,
                }
            )
    else:
        print("\n[TIMED OUT]")
        memory.end_session("failure")

    return {
        "success": success,
        "extracted": extracted,
        "actions": actions,
        "howdex_source_signal": LAST_SOURCE_SIGNAL if use_memory else False,
    }


def run_real_macgyver_benchmark():
    sandbox = Path(tempfile.mkdtemp(prefix="howdex_real_macgyver_")).resolve()
    print(f"[REAL SANDBOX]: {sandbox}")

    try:
        (sandbox / "data_1.zdat").write_text("ZDAT_V1|KEY=ALPHA|VAL=7781")
        (sandbox / "data_2.zdat").write_text("ZDAT_V1|KEY=BETA|VAL=9924")

        teacher = run_agent(
            sandbox,
            "TEACHER AGENT — REAL TOOL INVENTION",
            "parse_custom_data_teacher",
            "Extract the VAL from data_1.zdat by writing and running custom_parser.py.",
            use_memory=False,
            model="gpt-4o",
        )

        print("\n[HOWDEX COMPILING REAL MACGYVER MEMORY]")
        procedures = memory.learn(min_samples=1)
        print(f"[HOWDEX] learned procedures: {len(procedures)}")
        for p in procedures:
            print("[HOWDEX PROCEDURE]", p.task_signature, p.confidence)

        parser = sandbox / "custom_parser.py"
        if parser.exists():
            parser.unlink()
            print("[REAL SANDBOX]: deleted custom_parser.py before student run")

        student = run_agent(
            sandbox,
            "STUDENT AGENT — REAL TOOL RE-MANIFESTATION",
            "parse_custom_data_student",
            "Extract the VAL from data_2.zdat.",
            use_memory=True,
            model="gpt-4o-mini",
        )

        print("\n" + "=" * 80)
        print("REAL MACGYVER FILESYSTEM BENCHMARK RESULT")
        print("=" * 80)
        print(f"Teacher actions: {teacher['actions']}")
        print(f"Teacher extracted: {teacher['extracted']}")
        print(f"Student actions: {student['actions']}")
        print(f"Student extracted: {student['extracted']}")
        print(f"Sandbox: {sandbox}")

        teacher_passed = (
            teacher["success"]
            and teacher["extracted"] == "7781"
            and ("fs_write", "custom_parser.py") in teacher["actions"]
        )

        student_passed = (
            student["success"]
            and student["extracted"] == "9924"
            and student.get("howdex_source_signal") is True
            and ("fs_write", "custom_parser.py") in student["actions"]
            and ("bash", "python3 custom_parser.py data_2.zdat") in student["actions"]
        )

        if teacher_passed and student_passed:
            print("RESULT: PASS — REAL MACGYVER FILESYSTEM TEST ACHIEVED. Howdex preserved and re-injected a teacher-created source-code tool that ran successfully on the real filesystem.")
        else:
            print("RESULT: FAIL — real filesystem MacGyver test did not meet pass conditions.")

    finally:
        # Keep this commented while debugging if you want to inspect the sandbox.
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    run_real_macgyver_benchmark()
