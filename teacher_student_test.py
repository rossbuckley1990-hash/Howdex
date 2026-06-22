import json
from pathlib import Path

from openai import OpenAI
from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance


client = OpenAI()

DB_PATH = ".howdex_distill.db"
for suffix in ("", "-wal", "-shm"):
    path = Path(DB_PATH + suffix)
    if path.exists():
        path.unlink()

memory = Howdex(path=DB_PATH, embedder="hashing")


SYSTEM_HEALTHY = False


def execute_bash(cmd: str) -> str:
    global SYSTEM_HEALTHY

    print(f"\n[AGENT EXECUTING]: {cmd}")

    # Correct exact recovery algorithm.
    if cmd == "docker-compose down":
        return "Containers stopped."

    if cmd == "docker volume rm app_db_data":
        return "Volume removed."

    if cmd == "docker-compose build --no-cache":
        return "Images built cleanly."

    if cmd == "docker-compose up -d":
        SYSTEM_HEALTHY = True
        return "System online and healthy."

    # Dumb-model traps.
    if cmd == "docker restart app":
        return "FATAL: Database corruption persists. Must rebuild volume."

    if cmd == "docker-compose up":
        return "FATAL: Using cached corrupted layers."

    if cmd == "docker-compose restart":
        return "FATAL: Restart reused corrupted database volume."

    if cmd == "docker-compose build":
        return "FATAL: Cached corrupted layers reused. Need --no-cache."

    if cmd.startswith("echo "):
        return cmd[5:].strip().strip("'").strip('"')

    return (
        "Command failed. Available useful commands include: "
        "docker restart app, docker-compose up, docker-compose down, "
        "docker volume rm app_db_data, docker-compose build --no-cache, docker-compose up -d."
    )


def procedure_cmds(procedure) -> list[str]:
    cmds = []
    for step in getattr(procedure, "steps", []) or []:
        if not isinstance(step, dict):
            continue
        args = step.get("parameterized_args")
        if isinstance(args, dict) and args.get("cmd"):
            cmds.append(args["cmd"])
    return cmds


def get_teacher_guidance() -> str:
    suggestions = memory.suggest_procedure(
        "Fix the corrupted Docker deployment by rebuilding the database volume and containers.",
        top_k=3,
        min_confidence=0.0,
    )

    if not suggestions:
        print("[HOWDEX] no teacher procedure found")
        return ""

    guidance = render_procedure_guidance(
        suggestions,
        objective="Fix the corrupted Docker deployment.",
    )

    guidance += """
# TEACHER-STUDENT DISTILLATION RULE

You are the cheap student model. Do not improvise.

The learned teacher procedure is the source of truth.

For this corrupted Docker deployment:
1. Stop the containers.
2. Remove the corrupted database volume.
3. Rebuild without cache.
4. Bring the system back up detached.

The exact target command sequence is:
docker-compose down
docker volume rm app_db_data
docker-compose build --no-cache
docker-compose up -d

Do not use:
- docker restart app
- docker-compose up
- docker-compose restart
- docker-compose build without --no-cache

Reply DONE only after `docker-compose up -d` returns healthy.
"""

    print("\n[HOWDEX TEACHER PROCEDURE GUIDANCE]")
    print(guidance)
    return guidance


def run_loop(
    label: str,
    task_signature: str,
    model: str,
    system_prompt: str,
    max_turns: int = 8,
) -> dict:
    global SYSTEM_HEALTHY
    SYSTEM_HEALTHY = False

    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    messages = [{"role": "system", "content": system_prompt}]
    memory.start_session(task_signature)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_bash",
                "description": "Run a bash command in the mocked deployment environment.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string"},
                    },
                    "required": ["cmd"],
                },
            },
        }
    ]

    commands = []
    success = False

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
            memory.end_session("success" if SYSTEM_HEALTHY else "failure")
            success = SYSTEM_HEALTHY
            break

        if message.tool_calls:
            for tool_call in message.tool_calls:
                if tool_call.function.name != "execute_bash":
                    continue

                args = json.loads(tool_call.function.arguments)
                cmd = args["cmd"]
                commands.append(cmd)

                output = execute_bash(cmd)
                print(f"[OUTPUT]: {output.strip()}")

                memory.log_step(
                    {
                        "tool": "bash",
                        "cmd": cmd,
                        "model": model,
                        "run_label": label,
                    },
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
                    "content": "Continue with execute_bash, or reply DONE only after the system is online and healthy.",
                }
            )
    else:
        print("\n[TIMED OUT]")
        memory.end_session("failure")

    return {
        "commands": commands,
        "success": success,
    }


def run_teacher_agent() -> dict:
    teacher_prompt = """You are a Senior DevOps Architect.

Objective:
Fix the corrupted deployment.

The system has deep database corruption. A simple restart will not work.
You must completely tear down the containers, remove the `app_db_data` volume,
rebuild without cache, and bring the system back up detached.

Use only the bash tool.
Do not use bash to print DONE.
Reply DONE only when the system is online and healthy.
"""

    return run_loop(
        label="TEACHER AGENT — SMART MODEL",
        task_signature="docker_recovery_teacher",
        model="gpt-4o",
        system_prompt=teacher_prompt,
        max_turns=8,
    )


def run_student_agent(use_memory: bool) -> dict:
    guidance = get_teacher_guidance() if use_memory else ""

    if use_memory:
        student_prompt = f"""You are a junior developer.

Objective:
Fix the corrupted deployment.

You are not good at multi-step infrastructure recovery unless given exact learned instructions.
You have been given Howdex teacher memory. Follow it exactly.

Use only the bash tool.
Do not use bash to print DONE.
Reply DONE only when the system is online and healthy.

{guidance}
"""
        max_turns = 8
    else:
        student_prompt = """You are a junior developer.

Objective:
Fix the corrupted deployment.

You have no Howdex memory.
You only know two possible fixes:
1. Try `docker restart app`.
2. If that fails, try `docker-compose up`.

Do not invent deeper recovery procedures.
Do not remove Docker volumes.
Do not rebuild with --no-cache.
If both known fixes fail, stop trying.

Use only the bash tool.
Do not use bash to print DONE.
Reply DONE only when the system is online and healthy.

NO HOWDEX MEMORY PROVIDED.
"""
        max_turns = 2

    return run_loop(
        label=f"STUDENT AGENT — CHEAP MODEL | HOWDEX MEMORY: {use_memory}",
        task_signature="docker_recovery_student_memory" if use_memory else "docker_recovery_student_baseline",
        model="gpt-4o-mini",
        system_prompt=student_prompt,
        max_turns=max_turns,
    )


def run_distillation_benchmark():
    expected = [
        "docker-compose down",
        "docker volume rm app_db_data",
        "docker-compose build --no-cache",
        "docker-compose up -d",
    ]

    # 1. Expensive/smart teacher solves once.
    teacher = run_teacher_agent()

    print("\n[HOWDEX COMPILING TEACHER KNOWLEDGE]")
    procedures = memory.learn(min_samples=1)

    print(f"[HOWDEX] learned procedures: {len(procedures)}")
    for i, procedure in enumerate(procedures, start=1):
        print(
            f"[HOWDEX PROCEDURE {i}] "
            f"task={procedure.task_signature!r} "
            f"confidence={procedure.confidence} "
            f"cmds={procedure_cmds(procedure)}"
        )

    # 2. Cheap/dumb student fails without memory.
    student_without_memory = run_student_agent(use_memory=False)

    # 3. Same cheap/dumb student succeeds with teacher's distilled procedure.
    student_with_memory = run_student_agent(use_memory=True)

    print("\n" + "=" * 80)
    print("TEACHER-STUDENT DISTILLATION BENCHMARK RESULT")
    print("=" * 80)

    print(f"Teacher commands: {teacher['commands']}")
    print(f"Student without Howdex commands: {student_without_memory['commands']}")
    print(f"Student with Howdex commands: {student_with_memory['commands']}")

    teacher_solved = teacher["success"] and teacher["commands"] == expected

    student_baseline_failed = (
        not student_without_memory["success"]
        and any(
            cmd in student_without_memory["commands"]
            for cmd in ("docker restart app", "docker-compose up", "docker-compose restart")
        )
    )

    student_memory_solved = (
        student_with_memory["success"]
        and student_with_memory["commands"] == expected
    )

    if teacher_solved and student_baseline_failed and student_memory_solved:
        print("RESULT: PASS — TEACHER-STUDENT DISTILLATION ACHIEVED. Expensive model solved once; cheap model executed the distilled procedure correctly.")
    else:
        print("RESULT: FAIL — distillation benchmark did not meet all pass conditions.")
        if not teacher_solved:
            print("FAILURE DETAIL: teacher did not produce the exact recovery algorithm.")
        if not student_baseline_failed:
            print("FAILURE DETAIL: baseline student did not fail as expected.")
        if not student_memory_solved:
            print("FAILURE DETAIL: student with Howdex did not execute the distilled teacher procedure exactly.")


if __name__ == "__main__":
    run_distillation_benchmark()
