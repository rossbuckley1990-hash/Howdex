import json
import sqlite3
from pathlib import Path

from openai import OpenAI
from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance


client = OpenAI()

DB_PATH = ".howdex_macgyver.db"
for suffix in ("", "-wal", "-shm"):
    path = Path(DB_PATH + suffix)
    if path.exists():
        path.unlink()

memory = Howdex(path=DB_PATH, embedder="hashing")

FILES = {
    "data_1.zdat": "ZDAT_V1|KEY=ALPHA|VAL=7781",
    "data_2.zdat": "ZDAT_V1|KEY=BETA|VAL=9924",
}

CUSTOM_TOOL_WRITTEN = False
CUSTOM_TOOL_CONTENT = ""


def execute_bash(cmd: str) -> str:
    global CUSTOM_TOOL_WRITTEN, CUSTOM_TOOL_CONTENT

    print(f"\n[AGENT EXECUTING]: {cmd}")

    if cmd.startswith(("cat", "grep", "jq", "awk", "sed")):
        return "FATAL: Standard text processing tools have been uninstalled from this secure environment."

    if cmd.startswith("python3 custom_parser.py"):
        if not CUSTOM_TOOL_WRITTEN:
            return "FATAL: custom_parser.py does not exist."

        if "VAL=" not in CUSTOM_TOOL_CONTENT or "split" not in CUSTOM_TOOL_CONTENT:
            return "FATAL: custom_parser.py exists but does not implement the ZDAT VAL parser."

        parts = cmd.split()
        if len(parts) < 3:
            return "PARSER ERROR: missing filename."

        filename = parts[2]
        if filename in FILES:
            value = FILES[filename].split("VAL=", 1)[1]
            return f"PARSER SUCCESS: Extracted value {value}"

        return "PARSER ERROR: File not found."

    if cmd.startswith("echo "):
        return cmd[5:].strip().strip("'").strip('"')

    return (
        "Command failed. Available useful action: write custom_parser.py with fs_write, "
        "then run python3 custom_parser.py <file>."
    )


def execute_fs_write(file_path: str, content: str) -> str:
    global CUSTOM_TOOL_WRITTEN, CUSTOM_TOOL_CONTENT

    print(f"\n[AGENT WRITING FILE]: {file_path}")
    print(f"[CODE PREVIEW]: {content[:120].replace(chr(10), ' ')}...")

    if file_path == "custom_parser.py":
        CUSTOM_TOOL_CONTENT = content
        if "VAL=" in content and "split" in content:
            CUSTOM_TOOL_WRITTEN = True
            return "File custom_parser.py written successfully."

    return "File written, but parser requirements were not met."


def procedure_cmds(procedure) -> list[str]:
    names = []
    for step in getattr(procedure, "steps", []) or []:
        if not isinstance(step, dict):
            continue
        names.append(step.get("canonical_name") or step.get("action") or str(step))
    return names




def hydrate_raw_examples_from_sqlite(procedures, db_path: str = DB_PATH):
    """Attach PROCEDURES.raw_examples JSON to loaded Procedure objects.

    Current storage rows contain raw_examples, but list_procedures() may not
    hydrate it onto the Procedure object yet. This benchmark needs the full
    source artifact for fs_write rendering.
    """
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
            if procedure_id and procedure_id in {
                str(row.get("procedure_id", "")),
                str(row.get("id", "")),
            }:
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
            # Frozen dataclass/object fallback: store under an alternate name the
            # guidance wrapper also understands.
            try:
                setattr(procedure, "raw_supporting_examples", parsed)
            except Exception:
                pass

    return procedures



def get_macgyver_guidance() -> tuple[str, list]:
    suggestions = memory.suggest_procedure(
        "Extract the VAL from a ZDAT file using a custom parser script.",
        top_k=5,
        min_confidence=0.0,
    )

    if not suggestions:
        print("[HOWDEX] no MacGyver procedure found")
        return "", []

    # Load full procedures so guidance can render raw source-code artifacts
    # from raw_examples, not only the lightweight ProcedureSuggestion view.
    # For artifact/tool-memory rendering we need full Procedure objects,
    # because source code lives in Procedure.raw_examples, not in lightweight
    # ProcedureSuggestion objects.
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
            bool(
                getattr(procedure, "raw_examples", None)
                or getattr(procedure, "raw_supporting_examples", None)
            ),
        )

    howdex_guidance = render_procedure_guidance(
        full_procedures,
        objective="Extract the VAL from a ZDAT file using custom_parser.py.",
        bindings={
            "<FILE_PATH_1>": "custom_parser.py",
            "<SCRIPT_PATH_1>": "custom_parser.py",
        },
    )

    contains_source_signal = (
        "custom_parser.py" in howdex_guidance
        and "VAL=" in howdex_guidance
        and "split" in howdex_guidance
        and "```" in howdex_guidance
    )

    guidance = howdex_guidance + """
# MACGYVER TOOL RE-MANIFESTATION RULE

You are the student agent.

A prior teacher agent solved this by writing a custom parser script and then running it.

You must:
1. Recreate `custom_parser.py` using the learned fs_write/tool-write step from Howdex memory.
2. Then run `python3 custom_parser.py data_2.zdat`.
3. Do not use cat, grep, jq, awk, sed, or standard text-processing tools.
4. Do not infer a new parser from this prompt. Use the learned tool source from Howdex guidance.
5. Do not claim DONE until the parser returns `PARSER SUCCESS`.
"""

    print("\n[HOWDEX MACGYVER GUIDANCE]")
    print(guidance)
    print(f"\n[HOWDEX SOURCE-CODE SIGNAL IN GUIDANCE]: {contains_source_signal}")

    return guidance, suggestions


def run_loop(
    label: str,
    task_signature: str,
    model: str,
    objective: str,
    use_memory: bool,
    max_turns: int = 8,
) -> dict:
    global CUSTOM_TOOL_WRITTEN, CUSTOM_TOOL_CONTENT
    CUSTOM_TOOL_WRITTEN = False
    CUSTOM_TOOL_CONTENT = ""

    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    guidance = ""
    suggestions = []

    if use_memory:
        memory.start_session(task_signature)
        guidance, suggestions = get_macgyver_guidance()
    else:
        memory.start_session(task_signature)

    if use_memory:
        system_prompt = f"""You are an autonomous student agent in a restricted environment.

Objective:
{objective}

Standard text tools are unavailable: no cat, grep, jq, awk, or sed.
Use the available tools:
- execute_fs_write(file_path, content)
- execute_bash(cmd)

You are not expected to invent the parser from scratch. Use Howdex memory.
Do not use bash to print DONE.
Reply DONE only after `PARSER SUCCESS`.

{guidance if guidance else "NO HOWDEX MEMORY AVAILABLE."}
"""
    else:
        system_prompt = f"""You are a senior autonomous agent in a restricted environment.

Objective:
{objective}

Standard text tools are unavailable: no cat, grep, jq, awk, or sed.

You may create a new Python script using execute_fs_write.
Write `custom_parser.py`.
The script should read the file path from argv and extract the value after `VAL=`.
Then run it with execute_bash.

Use the available tools:
- execute_fs_write(file_path, content)
- execute_bash(cmd)

Do not use bash to print DONE.
Reply DONE only after `PARSER SUCCESS`.
"""

    messages = [{"role": "system", "content": system_prompt}]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_bash",
                "description": "Run a bash command in the mocked restricted environment.",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                    "required": ["cmd"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_fs_write",
                "description": "Write a file in the mocked restricted environment.",
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
    ]

    actions = []
    success = False
    extracted_value = None

    for _turn in range(max_turns):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0.0,
        )

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content and message.content.strip().upper().startswith("DONE"):
            print(f"\n[FINISHED]: {message.content}")
            memory.end_session("success" if success else "failure")
            break

        if message.tool_calls:
            for tool_call in message.tool_calls:
                args = json.loads(tool_call.function.arguments)

                if tool_call.function.name == "execute_bash":
                    output = execute_bash(args["cmd"])
                    action = {
                        "tool": "execute_bash",
                        "arguments": {"cmd": args["cmd"]},
                    }
                    actions.append(("bash", args["cmd"]))

                elif tool_call.function.name == "execute_fs_write":
                    output = execute_fs_write(args["file_path"], args["content"])
                    action = {
                        "tool": "execute_fs_write",
                        "arguments": {
                            "file_path": args["file_path"],
                            "content": args["content"],
                        },
                    }
                    actions.append(("fs_write", args["file_path"]))

                else:
                    continue

                print(f"[OUTPUT]: {output.strip()}")

                if "PARSER SUCCESS" in output:
                    success = True
                    extracted_value = output.rsplit(" ", 1)[-1]

                memory.log_tool_call(
                    action["tool"],
                    action["arguments"],
                    output,
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": output,
                    }
                )
        else:
            print(f"[AGENT MESSAGE]: {message.content}")
            messages.append(
                {
                    "role": "user",
                    "content": "Continue with a tool call, or reply DONE only after PARSER SUCCESS.",
                }
            )
    else:
        print("\n[TIMED OUT]")
        memory.end_session("failure")

    return {
        "success": success,
        "actions": actions,
        "tool_written": CUSTOM_TOOL_WRITTEN,
        "tool_content": CUSTOM_TOOL_CONTENT,
        "extracted_value": extracted_value,
    }


def run_macgyver_benchmark():
    teacher = run_loop(
        label="TEACHER AGENT — INVENT CUSTOM TOOL",
        task_signature="parse_custom_data_teacher",
        model="gpt-4o",
        objective="Extract the VAL from `data_1.zdat`. Standard tools are missing. Write `custom_parser.py` to parse ZDAT and split by `VAL=`.",
        use_memory=False,
        max_turns=8,
    )

    print("\n[HOWDEX COMPILING MACGYVER MEMORY]")
    procedures = memory.learn(min_samples=1)

    print(f"[HOWDEX] learned procedures: {len(procedures)}")
    for i, procedure in enumerate(procedures, start=1):
        print(
            f"[HOWDEX PROCEDURE {i}] "
            f"task={procedure.task_signature!r} "
            f"confidence={procedure.confidence} "
            f"steps={procedure_cmds(procedure)}"
        )

    print("\n" + "*" * 80)
    print("THE MACGYVER TEST: ZERO-SHOT TOOL RE-MANIFESTATION")
    print("*" * 80)

    student = run_loop(
        label="STUDENT AGENT — USE INVENTED TOOL FROM HOWDEX MEMORY",
        task_signature="parse_custom_data_student",
        model="gpt-4o-mini",
        objective="Extract the VAL from `data_2.zdat`.",
        use_memory=True,
        max_turns=8,
    )

    print("\n" + "=" * 80)
    print("MACGYVER TOOL-SYNTHESIS BENCHMARK RESULT")
    print("=" * 80)

    print(f"Teacher actions: {teacher['actions']}")
    print(f"Teacher extracted: {teacher['extracted_value']}")
    print(f"Student actions: {student['actions']}")
    print(f"Student extracted: {student['extracted_value']}")

    teacher_passed = (
        teacher["success"]
        and teacher["tool_written"]
        and teacher["extracted_value"] == "7781"
    )

    guidance, _ = get_macgyver_guidance()
    source_code_preserved = (
        "custom_parser.py" in guidance
        and "VAL=" in guidance
        and "split" in guidance
        and "```" in guidance
    )

    student_passed = (
        source_code_preserved
        and student["success"]
        and student["tool_written"]
        and student["extracted_value"] == "9924"
        and ("fs_write", "custom_parser.py") in student["actions"]
        and ("bash", "python3 custom_parser.py data_2.zdat") in student["actions"]
    )

    if teacher_passed and student_passed:
        print("RESULT: PASS — MACGYVER TOOL SYNTHESIS ACHIEVED. Howdex preserved a teacher-invented tool and enabled a student agent to re-manifest it for a new file.")
    elif teacher_passed and not student_passed:
        print("RESULT: FAIL — teacher invented the tool, but Howdex/student did not re-manifest it correctly.")
        print("LIKELY CAUSE: procedure guidance may not preserve fs_write source content strongly enough.")
    else:
        print("RESULT: FAIL — teacher did not invent and execute the custom tool successfully.")


if __name__ == "__main__":
    run_macgyver_benchmark()
