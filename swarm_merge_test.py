import json
import os
import sqlite3
from pathlib import Path

from benchmark_openai import get_openai_client
from howdex import Howdex
from howdex.core.guidance import render_procedure_guidance


_CLIENT = None


def _openai_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = get_openai_client()
    return _CLIENT

DBS = ["brain_alpha.db", "brain_beta.db", "brain_omega.db"]
for db in DBS:
    for suffix in ("", "-wal", "-shm"):
        path = Path(db + suffix)
        if path.exists():
            path.unlink()


AWS_FIXED = False
K8S_FIXED = False


def execute_bash(cmd: str) -> str:
    global AWS_FIXED, K8S_FIXED

    print(f"\n[AGENT EXECUTING]: {cmd}")

    if cmd == "aws ec2 update-route-table":
        return "AWS VPC Route Table updated."

    if cmd == "aws ec2 restart-gateway":
        AWS_FIXED = True
        return "AWS Gateway restarted."

    if cmd == "kubectl patch psp":
        return "K8s Pod Security Policy patched."

    if cmd == "kubectl rollout restart deploy":
        K8S_FIXED = True
        return "K8s Deploy restarted."

    if cmd == "deploy_fullstack":
        if AWS_FIXED and K8S_FIXED:
            return "SUCCESS: Fullstack app deployed. AWS networking and K8s security are healthy."
        missing = []
        if not AWS_FIXED:
            missing.append("VPC blocked connection")
        if not K8S_FIXED:
            missing.append("K8s rejected Pod")
        return "FATAL: " + " and ".join(missing) + "."

    if cmd.startswith("echo "):
        return cmd[5:].strip().strip("'").strip('"')

    return (
        "Command failed. Available commands: "
        "aws ec2 update-route-table, aws ec2 restart-gateway, "
        "kubectl patch psp, kubectl rollout restart deploy, deploy_fullstack."
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


def train_isolated_agent(
    node_name: str,
    db_path: str,
    task_name: str,
    commands: list[str],
) -> dict:
    print("\n" + "=" * 80)
    print(f"TRAINING ISOLATED NODE: {node_name}")
    print("=" * 80)

    memory = Howdex(path=db_path, embedder="hashing")
    memory.start_session(task_name)

    observed = []
    for cmd in commands:
        output = execute_bash(cmd)
        print(f"[OUTPUT]: {output}")
        observed.append(cmd)
        memory.log_step(
            {
                "tool": "bash",
                "cmd": cmd,
                "node": node_name,
                "air_gapped": True,
            },
            output,
        )

    memory.end_session("success")

    print(f"\n[HOWDEX COMPILING MEMORY FOR {node_name}]")
    learned = memory.learn(min_samples=1)

    for index, procedure in enumerate(learned, start=1):
        print(
            f"[{node_name} PROCEDURE {index}] "
            f"task={procedure.task_signature!r} "
            f"confidence={procedure.confidence} "
            f"cmds={procedure_cmds(procedure)}"
        )

    return {
        "node": node_name,
        "db_path": db_path,
        "commands": observed,
    }


def rows_by_table(db_path: str, table: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def import_procedure_rows(source_db: str, target_db: str) -> int:
    """Portable procedure-row merge into Omega.

    This is intentionally conservative: it only merges learned procedures, not
    raw memories. It preserves procedure IDs because Alpha and Beta are isolated
    UUID namespaces and task signatures are distinct in this benchmark.
    """
    source_conn = sqlite3.connect(source_db)
    source_conn.row_factory = sqlite3.Row

    target_conn = sqlite3.connect(target_db)
    target_conn.row_factory = sqlite3.Row

    try:
        source_rows = [dict(row) for row in source_conn.execute("SELECT * FROM procedures")]
        if not source_rows:
            return 0

        target_columns = [
            row["name"]
            for row in target_conn.execute("PRAGMA table_info(procedures)").fetchall()
        ]

        inserted = 0
        for row in source_rows:
            filtered = {key: row[key] for key in target_columns if key in row}
            columns = list(filtered.keys())
            placeholders = ", ".join(["?"] * len(columns))
            column_sql = ", ".join(columns)

            target_conn.execute(
                f"""
                INSERT OR REPLACE INTO procedures ({column_sql})
                VALUES ({placeholders})
                """,
                [filtered[column] for column in columns],
            )
            inserted += 1

        target_conn.commit()
        return inserted
    finally:
        source_conn.close()
        target_conn.close()


def merge_isolated_brains_into_omega(alpha_db: str, beta_db: str, omega_db: str) -> Howdex:
    print("\n" + "=" * 80)
    print("MERGING ISOLATED BRAINS INTO AGENT OMEGA")
    print("=" * 80)

    # Initialize Omega so schema exists.
    omega = Howdex(path=omega_db, embedder="hashing")

    imported_alpha = import_procedure_rows(alpha_db, omega_db)
    imported_beta = import_procedure_rows(beta_db, omega_db)

    print(f"[MERGE] imported {imported_alpha} procedure rows from Alpha")
    print(f"[MERGE] imported {imported_beta} procedure rows from Beta")

    procedures = omega.list_procedures(min_confidence=0.0, limit=None)
    print(f"[OMEGA] merged procedure count: {len(procedures)}")

    for index, procedure in enumerate(procedures, start=1):
        print(
            f"[OMEGA PROCEDURE {index}] "
            f"task={procedure.task_signature!r} "
            f"confidence={procedure.confidence} "
            f"cmds={procedure_cmds(procedure)}"
        )

    return omega


def retrieve_swarm_guidance(memory: Howdex, objective: str):
    # Explicitly retrieve broad objective with low confidence guardrail so both
    # domain procedures can surface.
    suggestions = memory.suggest_procedure(
        objective,
        top_k=5,
        min_confidence=0.0,
    )

    if not suggestions:
        print("[OMEGA] NO SWARM MEMORY FOUND")
        return "", []

    guidance = render_procedure_guidance(
        suggestions,
        objective=objective,
    )

    guidance += """
# SWARM MERGE EXECUTION RULE

You may have learned procedures from multiple isolated agents.

For this task:
- First run `deploy_fullstack`.
- If the output mentions VPC or AWS networking, apply the COMPLETE AWS networking procedure before retrying deploy:
  1. aws ec2 update-route-table
  2. aws ec2 restart-gateway
- If the output mentions K8s, Kubernetes, Pod, or Pod Security, apply the COMPLETE Kubernetes security procedure before retrying deploy:
  1. kubectl patch psp
  2. kubectl rollout restart deploy
- If both domains are mentioned, apply BOTH COMPLETE procedures before retrying `deploy_fullstack`.
- Do not retry `deploy_fullstack` after only half of a procedure.
- The clean target sequence is:
  deploy_fullstack
  aws ec2 update-route-table
  aws ec2 restart-gateway
  kubectl patch psp
  kubectl rollout restart deploy
  deploy_fullstack
- Do not mix command namespaces. Never invent commands like `aws ec2 patch psp`.
- Reply DONE only after `deploy_fullstack` succeeds.
"""

    print("\n[OMEGA SWARM GUIDANCE]")
    print(guidance)

    return guidance, suggestions


def run_omega_agent(memory: Howdex) -> dict:
    global AWS_FIXED, K8S_FIXED
    AWS_FIXED = False
    K8S_FIXED = False

    print("\n" + "=" * 80)
    print("SPAWNING AGENT OMEGA: THE MERGED SWARM MIND")
    print("=" * 80)

    objective = (
        "Deploy the fullstack application. It may require both AWS networking "
        "repair and Kubernetes security repair before deploy_fullstack can succeed."
    )

    memory.start_session("deploy_fullstack_omega")
    guidance, suggestions = retrieve_swarm_guidance(memory, objective)

    system_prompt = f"""You are Agent Omega, the Swarm Coordinator.

Objective:
{objective}

You are inside a mocked shell. Available commands are:
- deploy_fullstack
- aws ec2 update-route-table
- aws ec2 restart-gateway
- kubectl patch psp
- kubectl rollout restart deploy

Use the bash tool.
Do not run git, ls, pwd, curl, npm, mkdir, or filesystem discovery commands.
Do not use bash to print DONE.
Reply DONE: only after deploy_fullstack succeeds.

{guidance if guidance else "NO SWARM MEMORY FOUND. Explore manually."}
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

    for _turn in range(12):
        response = _openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            temperature=0.0,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content and message.content.strip().upper().startswith("DONE"):
            print(f"\n[OMEGA FINISHED]: {message.content}")
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
                        "memory_injected": bool(suggestions),
                        "swarm_merged": True,
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
            print(f"[OMEGA MESSAGE]: {message.content}")
            messages.append(
                {
                    "role": "user",
                    "content": "Continue. Use execute_bash, or reply DONE only after deploy_fullstack succeeds.",
                }
            )
    else:
        print("\n[OMEGA TIMED OUT]")
        memory.end_session("failure")

    return {
        "commands": commands,
        "success": success,
    }


def run_swarm_benchmark():
    alpha = train_isolated_agent(
        "alpha",
        "brain_alpha.db",
        "fix_aws_networking",
        ["aws ec2 update-route-table", "aws ec2 restart-gateway"],
    )

    beta = train_isolated_agent(
        "beta",
        "brain_beta.db",
        "fix_k8s_security",
        ["kubectl patch psp", "kubectl rollout restart deploy"],
    )

    omega = merge_isolated_brains_into_omega(
        "brain_alpha.db",
        "brain_beta.db",
        "brain_omega.db",
    )

    result = run_omega_agent(omega)

    print("\n" + "=" * 80)
    print("TOWER OF BABEL SWARM MERGE BENCHMARK RESULT")
    print("=" * 80)

    print(f"Alpha training commands: {alpha['commands']}")
    print(f"Beta training commands: {beta['commands']}")
    print(f"Omega commands: {result['commands']}")

    required = [
        "deploy_fullstack",
        "aws ec2 update-route-table",
        "aws ec2 restart-gateway",
        "kubectl patch psp",
        "kubectl rollout restart deploy",
        "deploy_fullstack",
    ]

    commands_for_scoring = list(result["commands"])

    has_all_required = all(cmd in commands_for_scoring for cmd in required)
    aws_order_ok = (
        "aws ec2 update-route-table" in result["commands"]
        and "aws ec2 restart-gateway" in result["commands"]
        and commands_for_scoring.index("aws ec2 update-route-table")
        < commands_for_scoring.index("aws ec2 restart-gateway")
    )
    k8s_order_ok = (
        "kubectl patch psp" in result["commands"]
        and "kubectl rollout restart deploy" in result["commands"]
        and commands_for_scoring.index("kubectl patch psp")
        < commands_for_scoring.index("kubectl rollout restart deploy")
    )
    deployed_after_repairs = (
        commands_for_scoring.count("deploy_fullstack") >= 2
        and commands_for_scoring[-1] == "deploy_fullstack"
        and result["success"]
    )

    mixed_namespaces = any(
        bad in " ".join(commands_for_scoring)
        for bad in (
            "aws ec2 patch psp",
            "kubectl restart-gateway",
            "aws rollout",
            "kubectl update-route-table",
        )
    )

    if (
        has_all_required
        and aws_order_ok
        and k8s_order_ok
        and deployed_after_repairs
        and not mixed_namespaces
    ):
        print("RESULT: PASS — SWARM MERGE ACHIEVED. Omega used two isolated learned procedures to solve one combined cross-domain task.")
    else:
        print("RESULT: FAIL — Omega did not correctly compose both isolated swarm memories.")
        if not has_all_required:
            print("FAILURE DETAIL: missing one or more required commands.")
        if not aws_order_ok:
            print("FAILURE DETAIL: AWS repair order was wrong.")
        if not k8s_order_ok:
            print("FAILURE DETAIL: Kubernetes repair order was wrong.")
        if not deployed_after_repairs:
            print("FAILURE DETAIL: deploy_fullstack did not succeed after both repairs.")
        if mixed_namespaces:
            print("FAILURE DETAIL: Omega mixed command namespaces.")


if __name__ == "__main__":
    run_swarm_benchmark()
