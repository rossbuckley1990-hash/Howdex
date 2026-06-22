import json
import os
from pathlib import Path

from openai import OpenAI
from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance


client = OpenAI()

DB_PATH = ".howdex_drift.db"
for suffix in ("", "-shm", "-wal"):
    path = Path(DB_PATH + suffix)
    if path.exists():
        path.unlink()

memory = Howdex(path=DB_PATH, embedder="hashing")

API_VERSION = "v1"


def execute_bash(cmd: str) -> str:
    print(f"\n[AGENT EXECUTING]: {cmd}")

    if cmd == "deploy_app":
        if API_VERSION == "v1":
            return "SUCCESS: App deployed using V1 architecture."
        return "FATAL ERROR: 'deploy_app' command deprecated. Use 'app_deployer --v2' instead."

    if cmd == "app_deployer --v2":
        if API_VERSION == "v2":
            return "SUCCESS: App deployed using V2 architecture."
        return "Command not found."

    if cmd.startswith("echo "):
        return cmd[5:].strip().strip("'").strip('"')

    return "Command failed. Available deployment commands are: deploy_app or app_deployer --v2."


def procedure_cmds(procedure) -> list[str]:
    cmds = []
    for step in getattr(procedure, "steps", []) or []:
        args = step.get("parameterized_args") if isinstance(step, dict) else None
        if isinstance(args, dict) and args.get("cmd"):
            cmds.append(args["cmd"])
    return cmds


def print_procedures(label: str):
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    procedures = memory.list_procedures(min_confidence=0.0, limit=None)
    if not procedures:
        print("[HOWDEX] no stored procedures")
        return []

    for i, proc in enumerate(procedures, start=1):
        print(
            f"[HOWDEX PROCEDURE {i}] "
            f"task={proc.task_signature!r} "
            f"confidence={getattr(proc, 'confidence', None)} "
            f"success={getattr(proc, 'success_count', None)} "
            f"failure={getattr(proc, 'failure_count', None)} "
            f"feedback_success={getattr(proc, 'feedback_success_count', None)} "
            f"feedback_failure={getattr(proc, 'feedback_failure_count', None)} "
            f"cmds={procedure_cmds(proc)}"
        )

    return procedures


def get_valid_guidance(objective: str, min_confidence: float = 0.80) -> tuple[str, list]:
    try:
        suggestions = memory.suggest_procedure(
            objective,
            top_k=5,
            min_confidence=min_confidence,
        )
    except Exception as exc:
        print(f"[HOWDEX] suggest_procedure failed: {exc}")
        suggestions = []

    if not suggestions:
        print("[HOWDEX] NO VALID MEMORY FOUND")
        return "", []

    print(f"[HOWDEX] valid suggestions returned: {len(suggestions)}")
    guidance = render_procedure_guidance(
        suggestions,
        objective=objective,
    )

    print("\n[HOWDEX AGENT GUIDANCE]")
    print(guidance)
    return guidance, suggestions


def run_agent(
    task_name: str,
    objective: str,
    max_turns: int = 8,
    use_memory: bool = True,
    strict_memory_only: bool = False,
    min_confidence: float = 0.80,
) -> dict:
    print("\n" + "=" * 80)
    print(f"STARTING TASK: {task_name} | API VERSION: {API_VERSION}")
    print("=" * 80)

    guidance = ""
    suggestions = []

    # Start the session BEFORE retrieving memory so Howdex can link
    # suggested procedures to this episode and penalize them on failure.
    memory.start_session("cloud_deploy")

    if use_memory:
        guidance, suggestions = get_valid_guidance(objective, min_confidence=min_confidence)

    if strict_memory_only:
        exploration_rule = """
Trap-mode rule:
- You are evaluating whether the learned procedure still works.
- Use the learned procedure only.
- Do not explore alternative commands.
- If the learned procedure keeps failing, keep trying until the run times out.
"""
    else:
        exploration_rule = """
Exploration rule:
- If no valid memory is provided, explore manually.
- If a command returns a deprecation error telling you the replacement command, use that replacement command.
- If a learned procedure fails repeatedly, stop trusting it and explore alternatives.
"""

    system_prompt = f"""You are an autonomous cloud deployment agent.

Objective:
{objective}

You are inside a mocked deployment shell. There are only two meaningful deployment commands available:
- deploy_app
- app_deployer --v2

Use the bash tool to execute commands.
Do not run git, ls, pwd, whoami, mkdir, touch, npm, curl, or filesystem discovery commands.
Output DONE: followed by a summary when deployment succeeds.
Do not use bash to print DONE. DONE must be a normal final assistant message.

{exploration_rule}

{guidance if guidance else "NO VALID MEMORY FOUND. Explore manually."}
"""

    messages = [{"role": "system", "content": system_prompt}]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_bash",
                "description": "Run a bash command.",
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
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0.0,
        )

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content and "DONE:" in message.content:
            print(f"\n[AGENT FINISHED]: {message.content}")
            memory.end_session("success")
            success = True
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
                        "api_version": API_VERSION,
                        "memory_injected": bool(suggestions),
                        "strict_memory_only": strict_memory_only,
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
                    "content": "Continue. Use execute_bash or reply DONE: only after deployment succeeds.",
                }
            )
    else:
        print("\n[AGENT TIMED OUT]")
        memory.end_session("failure")

    return {
        "success": success,
        "commands": commands,
        "had_memory": bool(suggestions),
    }


def run_epistemic_drift_benchmark():
    global API_VERSION

    # 1. Train V1 memory.
    train_v1 = run_agent(
        "train_v1",
        "Deploy the app.",
        max_turns=6,
        use_memory=False,
    )

    print("\n[HOWDEX LEARNING V1...]")
    memory.learn(min_samples=1)
    print_procedures("AFTER V1 TRAINING")

    # 2. Drift the environment.
    API_VERSION = "v2"

    print("\n" + "*" * 80)
    print("THE TRAP: V1 MEMORY IN A V2 WORLD")
    print("*" * 80)

    # This deliberately gives the agent no room to recover.
    # The purpose is to see whether a failed memory-guided episode penalizes the obsolete procedure.
    trap = run_agent(
        "fail_v2",
        "Deploy the app.",
        max_turns=1,
        use_memory=True,
        strict_memory_only=True,
        min_confidence=0.80,
    )

    print("\n[HOWDEX EVALUATING FAILED MEMORY-GUIDED EPISODE...]")
    memory.learn(min_samples=1)
    procedures_after_trap = print_procedures("AFTER V2 TRAP FAILURE")

    print("\n" + "*" * 80)
    print("THE UNLEARNING TEST: DOES HOWDEX STOP INJECTING BAD MEMORY?")
    print("*" * 80)

    guidance, suggestions_after_trap = get_valid_guidance(
        "Deploy the app.",
        min_confidence=0.80,
    )

    obsolete_memory_still_injected = any(
        "deploy_app" in procedure_cmds(proc)
        for proc in suggestions_after_trap
    )

    recover_v2 = run_agent(
        "recover_v2",
        "Deploy the app.",
        max_turns=8,
        use_memory=True,
        strict_memory_only=False,
        min_confidence=0.80,
    )

    print("\n" + "=" * 80)
    print("EPISTEMIC DRIFT BENCHMARK RESULT")
    print("=" * 80)

    print(f"V1 training commands: {train_v1['commands']}")
    print(f"Trap commands: {trap['commands']}")
    print(f"Recovery commands: {recover_v2['commands']}")

    learned_v1 = train_v1["commands"] == ["deploy_app"] and train_v1["success"]
    trap_failed_with_old_memory = (
        trap["had_memory"]
        and not trap["success"]
        and trap["commands"]
        and all(cmd == "deploy_app" for cmd in trap["commands"])
    )
    v2_recovered = (
        recover_v2["success"]
        and "app_deployer --v2" in recover_v2["commands"]
    )

    if learned_v1 and trap_failed_with_old_memory and not obsolete_memory_still_injected and v2_recovered:
        print("RESULT: PASS — EPISTEMIC DRIFT HANDLED. Howdex stopped injecting obsolete memory and the agent discovered the new V2 procedure.")
    elif learned_v1 and trap_failed_with_old_memory and obsolete_memory_still_injected and v2_recovered:
        print("RESULT: FAIL — V2 recovery succeeded, but Howdex still injected obsolete V1 memory after it caused failure.")
        print("FAILURE DETAIL: confidence decay / invalidation protocol is missing or not connected to failed suggested procedures.")
    elif learned_v1 and trap_failed_with_old_memory and obsolete_memory_still_injected and not v2_recovered:
        print("RESULT: FAIL — poisoned memory persisted and blocked recovery.")
        print("FAILURE DETAIL: Howdex needs to penalize failed injected procedures below the suggestion threshold.")
    else:
        print("RESULT: INCONCLUSIVE — benchmark setup did not reach the intended train/trap/recover states.")

    print("\nExpected architecture if fixed:")
    print("- V1 procedure learned: deploy_app")
    print("- V2 trap fails using deploy_app")
    print("- Howdex lowers confidence or marks procedure invalid")
    print("- Next retrieval returns NO VALID MEMORY FOUND")
    print("- Agent explores, reads deprecation message, runs app_deployer --v2")
    print("- Howdex learns the V2 procedure")


if __name__ == "__main__":
    run_epistemic_drift_benchmark()
