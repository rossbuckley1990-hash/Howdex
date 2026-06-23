"""
Real Docker Recovery A/B Benchmark

Question:
    Can Howdex transfer a hard-won operational recovery procedure into a
    fresh broken local Docker Compose runtime?

The benchmark is deliberately local and disposable:
    - every teacher/control/treatment environment is a fresh temp directory;
    - every Compose project has an isolated project name and host port;
    - the only writable challenge file is runtime.env;
    - every success is confirmed by a real HTTP /health request;
    - cleanup always runs ``docker compose down -v`` before deleting files.

If Docker, Docker Compose, or the pinned local base image is unavailable, the
benchmark prints SKIP and exits successfully. It never pulls images itself.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from howdex import Howdex

DB_PATH = ".howdex_real_docker_recovery.db"
BASE_IMAGE = "python:3.12-alpine"
TEACHER_MODEL = os.getenv("HOWDEX_DOCKER_TEACHER_MODEL", "gpt-4o")
STUDENT_MODEL = os.getenv("HOWDEX_DOCKER_STUDENT_MODEL", "gpt-4o-mini")
N_TRIALS = int(os.getenv("HOWDEX_DOCKER_TRIALS", "5"))
MAX_TURNS = int(os.getenv("HOWDEX_DOCKER_MAX_TURNS", "15"))


@dataclass(frozen=True)
class DockerAvailability:
    available: bool
    reason: str


@dataclass(frozen=True)
class DockerSandbox:
    path: Path
    port: int
    project_name: str


@dataclass(frozen=True)
class CommandDecision:
    allowed: bool
    reason: str
    argv: tuple[str, ...] = ()


@dataclass
class AgentResult:
    label: str
    success: bool
    attempts: int
    actions: list[tuple[str, str]]
    used_memory: bool
    source_pasted: bool


def reset_db() -> None:
    """Remove only this benchmark's known local database files."""
    for suffix in ("", "-wal", "-shm"):
        path = Path(DB_PATH + suffix)
        if path.exists():
            path.unlink()


def _run_probe(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def check_docker_available() -> DockerAvailability:
    """Confirm the daemon, Compose plugin, and pinned local image are ready."""
    if shutil.which("docker") is None:
        return DockerAvailability(False, "docker executable was not found")
    try:
        daemon = _run_probe(["docker", "version", "--format", "{{.Server.Version}}"])
        if daemon.returncode != 0:
            detail = (daemon.stderr or daemon.stdout).strip()
            return DockerAvailability(
                False,
                f"Docker daemon is unavailable: {detail or 'unknown error'}",
            )

        compose = _run_probe(["docker", "compose", "version"])
        if compose.returncode != 0:
            detail = (compose.stderr or compose.stdout).strip()
            return DockerAvailability(
                False,
                f"Docker Compose is unavailable: {detail or 'unknown error'}",
            )

        image = _run_probe(["docker", "image", "inspect", BASE_IMAGE])
        if image.returncode != 0:
            return DockerAvailability(
                False,
                (
                    f"required base image {BASE_IMAGE!r} is not present "
                    "locally; benchmark policy forbids network pulls"
                ),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return DockerAvailability(False, f"Docker probe failed: {exc}")
    return DockerAvailability(True, "Docker runtime is ready")


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def create_docker_sandbox(prefix: str) -> DockerSandbox:
    """Create one broken, isolated Compose application."""
    root = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    port = _reserve_local_port()
    project_name = re.sub(r"[^a-z0-9]", "", root.name.lower())[:40]

    (root / "Dockerfile").write_text(
        "\n".join(
            [
                f"FROM {BASE_IMAGE}",
                "WORKDIR /app",
                "COPY app.py health-policy.conf ./",
                'CMD ["python", "app.py"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "docker-compose.yml").write_text(
        "\n".join(
            [
                "services:",
                "  app:",
                "    build:",
                "      context: .",
                "    env_file:",
                "      - runtime.env",
                "    ports:",
                f'      - "127.0.0.1:{port}:8000"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "health-policy.conf").write_text(
        "required_health_mode=ready\n",
        encoding="utf-8",
    )
    (root / "runtime.env").write_text(
        "APP_PORT=9000\nHEALTH_MODE=degraded\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text(
        _application_source(),
        encoding="utf-8",
    )
    return DockerSandbox(root, port, project_name)


def _application_source() -> str:
    return """\
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def required_mode():
    line = Path("health-policy.conf").read_text().strip()
    return line.split("=", 1)[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        mode = os.environ.get("HEALTH_MODE", "")
        if mode != required_mode():
            print(
                f"health rejected: mode={mode!r}; inspect health policy",
                flush=True,
            )
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"unhealthy\\n")
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"healthy\\n")

    def log_message(self, format, *args):
        print(format % args, flush=True)


port = int(os.environ.get("APP_PORT", "8000"))
print(f"starting HTTP service on 0.0.0.0:{port}", flush=True)
HTTPServer(("0.0.0.0", port), Handler).serve_forever()
"""


def _compose_environment(sandbox: DockerSandbox) -> dict[str, str]:
    environment = os.environ.copy()
    environment["COMPOSE_PROJECT_NAME"] = sandbox.project_name
    environment["COMPOSE_FILE"] = str(sandbox.path / "docker-compose.yml")
    return environment


def validate_bash_command(cmd: str, sandbox_port: int) -> CommandDecision:
    """Allow a small, inspectable set of local recovery commands."""
    if not isinstance(cmd, str) or not cmd.strip():
        return CommandDecision(False, "empty command")
    if len(cmd) > 300:
        return CommandDecision(False, "command is too long")
    if any(character in cmd for character in ("\n", "\r", "\x00")):
        return CommandDecision(False, "control characters are forbidden")
    if re.search(r"[;&|<>`]|\$\(", cmd):
        return CommandDecision(False, "shell composition is forbidden")

    try:
        argv = tuple(shlex.split(cmd))
    except ValueError:
        return CommandDecision(False, "command could not be parsed")

    allowed_compose = {
        ("docker", "compose", "build"),
        ("docker", "compose", "ps"),
        ("docker", "compose", "logs"),
        ("docker", "compose", "logs", "app"),
        ("docker", "compose", "logs", "--tail", "100", "app"),
        ("docker", "compose", "up", "-d"),
        ("docker", "compose", "up", "-d", "--build"),
        (
            "docker",
            "compose",
            "up",
            "-d",
            "--build",
            "--force-recreate",
        ),
        (
            "docker",
            "compose",
            "up",
            "-d",
            "--force-recreate",
        ),
        ("docker", "compose", "down", "-v"),
    }
    allowed_reads = {
        ("cat", "docker-compose.yml"),
        ("cat", "Dockerfile"),
        ("cat", "app.py"),
        ("cat", "runtime.env"),
        ("cat", "health-policy.conf"),
    }
    allowed_health = {
        (
            "curl",
            "-sS",
            "-i",
            f"http://127.0.0.1:{sandbox_port}/health",
        ),
        (
            "curl",
            "-sS",
            "-i",
            f"http://localhost:{sandbox_port}/health",
        ),
    }
    if argv in allowed_compose | allowed_reads | allowed_health:
        return CommandDecision(True, "allowed benchmark command", argv)
    return CommandDecision(
        False,
        (
            "command is outside the benchmark allowlist; use only cat on "
            "challenge files, approved docker compose recovery commands, "
            "or the exact localhost health curl"
        ),
    )


def _validate_runtime_env(content: str) -> tuple[bool, str]:
    if len(content.encode("utf-8")) > 512:
        return False, "runtime.env is too large"
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            return False, "runtime.env must contain KEY=value assignments"
        key, value = line.split("=", 1)
        if key in values:
            return False, f"duplicate runtime.env key: {key}"
        values[key] = value
    if set(values) != {"APP_PORT", "HEALTH_MODE"}:
        return False, "runtime.env must define APP_PORT and HEALTH_MODE only"
    if not re.fullmatch(r"\d{2,5}", values["APP_PORT"]):
        return False, "APP_PORT must be a numeric TCP port"
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", values["HEALTH_MODE"]):
        return False, "HEALTH_MODE contains unsafe characters"
    return True, "valid runtime.env"


def execute_fs_write(
    sandbox: DockerSandbox,
    file_path: str,
    content: str,
) -> str:
    """Permit only a validated rewrite of the runtime environment file."""
    if file_path != "runtime.env":
        return "FATAL: only runtime.env may be modified in this benchmark"
    valid, reason = _validate_runtime_env(content)
    if not valid:
        return f"FATAL: {reason}"
    target = (sandbox.path / file_path).resolve()
    if target.parent != sandbox.path:
        return "FATAL: path escaped the benchmark sandbox"
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    return "wrote runtime.env"


def verify_health(sandbox_port: int) -> tuple[bool, str]:
    """Run the independent real HTTP success verifier."""
    url = f"http://127.0.0.1:{sandbox_port}/health"
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            body = response.read(200).decode("utf-8", errors="replace").strip()
            if response.status == 200 and body == "healthy":
                return True, "HTTP 200 body=healthy"
            return False, f"HTTP {response.status} body={body!r}"
    except urllib.error.HTTPError as exc:
        body = exc.read(200).decode("utf-8", errors="replace").strip()
        return False, f"HTTP {exc.code} body={body!r}"
    except (OSError, urllib.error.URLError) as exc:
        return False, f"health request failed: {exc}"


def execute_bash(sandbox: DockerSandbox, cmd: str) -> str:
    """Execute one approved argv without invoking a shell."""
    decision = validate_bash_command(cmd, sandbox.port)
    if not decision.allowed:
        return f"FATAL: {decision.reason}"

    timeout = (
        120
        if decision.argv[:3]
        == (
            "docker",
            "compose",
            "up",
        )
        or decision.argv == ("docker", "compose", "build")
        else 30
    )
    try:
        result = subprocess.run(
            list(decision.argv),
            cwd=str(sandbox.path),
            env=_compose_environment(sandbox),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "FATAL: approved command timed out"
    except OSError as exc:
        return f"FATAL: approved command could not start: {exc}"

    combined = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    combined = combined[:4000]
    if decision.argv and decision.argv[0] == "curl":
        healthy, verifier = verify_health(sandbox.port)
        if healthy:
            return f"SUCCESS: real health verifier passed ({verifier})"
        return (
            f"FATAL: real health verifier failed ({verifier}). curl output: {combined or '[empty]'}"
        )
    if result.returncode != 0:
        return f"FATAL: command exited {result.returncode}. Output: {combined or '[empty]'}"
    return combined or "command completed successfully"


def cleanup_sandbox(sandbox: DockerSandbox) -> None:
    """Remove containers/volumes first, then the disposable directory."""
    try:
        subprocess.run(
            ["docker", "compose", "down", "-v"],
            cwd=str(sandbox.path),
            env=_compose_environment(sandbox),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    shutil.rmtree(sandbox.path, ignore_errors=True)


def source_pasted_in_guidance(guidance: str) -> bool:
    """Conservatively detect application or shell-script source leakage."""
    patterns = (
        r"```",
        r"(?m)^\s*#!",
        r"(?m)^\s*(?:from\s+\S+\s+import\s+|import\s+\S+)",
        r"(?m)^\s*(?:async\s+)?def\s+\w+\s*\(",
        r"(?m)^\s*class\s+\w+",
        r"\bBaseHTTPRequestHandler\b",
        r"\bHTTPServer\s*\(",
        r"\bserve_forever\s*\(",
        r"(?m)^\s*set\s+-[a-zA-Z]+",
        r"(?m)^\s*services:\s*$",
        r"(?m)^\s*FROM\s+\S+",
    )
    return any(re.search(pattern, guidance) for pattern in patterns)


def native_recovery_guidance(
    memory: Howdex,
    sandbox_port: int,
) -> tuple[str, bool, bool]:
    """Render only native Howdex guidance from learned procedure memory."""
    from howdex.core.guidance import render_procedure_guidance

    objective = (
        "Recover the broken Docker Compose HTTP service and make "
        f"http://127.0.0.1:{sandbox_port}/health return HTTP 200."
    )
    suggestions = memory.suggest_procedure(
        "recover broken Docker Compose HTTP health endpoint",
        top_k=3,
        min_confidence=0.0,
    )
    agent_guidance = memory.guidance(
        objective,
        query="recover broken Docker Compose HTTP health endpoint",
        top_k=3,
        min_confidence=0.0,
        constraints=[
            "Operate only inside the disposable benchmark sandbox.",
            "Modify only runtime.env.",
            "Use only approved Docker Compose, cat, and localhost curl commands.",
            "Require the real HTTP verifier before claiming success.",
        ],
        target_environment="isolated local Docker Compose sandbox",
        include_source=False,
        include_failed_attempts=True,
        include_verification=True,
    )
    procedure_guidance = render_procedure_guidance(
        suggestions,
        objective=objective,
        max_chars=3500,
    )
    guidance = agent_guidance.rstrip() + "\n\n" + procedure_guidance
    return (
        guidance,
        bool(suggestions),
        source_pasted_in_guidance(guidance),
    )


def _tool_definitions(sandbox_port: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_bash",
                "description": (
                    "Run one allowlisted local inspection, Docker Compose, "
                    f"or curl command. Health URL port is {sandbox_port}."
                ),
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
                "description": (
                    "Replace runtime.env inside the sandbox. Content must "
                    "define APP_PORT and HEALTH_MODE only."
                ),
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


def _base_prompt(sandbox_port: int) -> str:
    return f"""
You are recovering a broken HTTP application in an isolated temporary Docker
Compose sandbox.

Objective:
Make http://127.0.0.1:{sandbox_port}/health return HTTP 200.

Available files:
- docker-compose.yml
- Dockerfile
- app.py
- runtime.env
- health-policy.conf

Only runtime.env may be modified. It must contain APP_PORT and HEALTH_MODE.

Allowed execute_bash commands:
- cat docker-compose.yml
- cat Dockerfile
- cat app.py
- cat runtime.env
- cat health-policy.conf
- docker compose build
- docker compose up -d
- docker compose up -d --build
- docker compose up -d --force-recreate
- docker compose up -d --build --force-recreate
- docker compose ps
- docker compose logs
- docker compose logs app
- docker compose logs --tail 100 app
- docker compose down -v
- curl -sS -i http://127.0.0.1:{sandbox_port}/health

Use execute_fs_write to change runtime.env. Do not use shell redirects, sed,
sudo, docker exec, docker run, docker pull, external URLs, or host paths.
Do not claim completion until execute_bash reports SUCCESS from the real health
verifier.
""".strip()


def run_agent(
    *,
    client: Any,
    label: str,
    sandbox: DockerSandbox,
    memory: Howdex,
    record_to_memory: bool,
    use_memory: bool,
    model: str,
    temperature: float,
) -> AgentResult:
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    guidance = ""
    used_memory = False
    source_pasted = False
    if use_memory:
        guidance, used_memory, source_pasted = native_recovery_guidance(
            memory,
            sandbox.port,
        )
        print("\n[HOWDEX DOCKER RECOVERY MEMORY]")
        print(guidance)
        print(f"[HOWDEX MEMORY AVAILABLE]: {used_memory}")
        print(f"[HOWDEX SOURCE PASTED]: {source_pasted}")

    if record_to_memory:
        memory.start_session("recover broken Docker Compose HTTP service until /health is 200")

    prompt = _base_prompt(sandbox.port)
    if record_to_memory:
        prompt += """

You are the teacher. Diagnose the service rather than guessing. Inspect its
Compose wiring, runtime environment, application behavior, and health policy.
Start the real service, use logs and curl to distinguish reachability failures
from application-health failures, repair the runtime configuration, recreate
the container, and verify HTTP 200.
"""
    elif use_memory:
        prompt += "\n\nUse this prior Howdex operational memory:\n\n" + guidance
    else:
        prompt += "\n\nNo prior recovery memory is available."

    messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
    actions: list[tuple[str, str]] = []
    attempts = 0
    success = False

    try:
        for _turn in range(MAX_TURNS):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_tool_definitions(sandbox.port),
                temperature=temperature,
            )
            message = response.choices[0].message
            messages.append(message.model_dump(exclude_none=True))

            if message.content and message.content.strip().upper().startswith("DONE"):
                if success:
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "DONE rejected. The real /health verifier has not reported SUCCESS."
                        ),
                    }
                )
                continue

            if not message.tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue with approved tool calls until the real "
                            "health verifier reports SUCCESS."
                        ),
                    }
                )
                continue

            for tool_call in message.tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    output = "FATAL: tool arguments were not valid JSON"
                else:
                    if tool_call.function.name == "execute_bash":
                        cmd = str(arguments.get("cmd", ""))
                        attempts += 1
                        output = execute_bash(sandbox, cmd)
                        actions.append(("bash", cmd))
                        if record_to_memory:
                            memory.log_tool_call(
                                "execute_bash",
                                {"cmd": cmd},
                                output,
                                outcome=(
                                    "success"
                                    if output.startswith("SUCCESS:")
                                    else "failure"
                                    if output.startswith("FATAL:")
                                    else "partial"
                                ),
                            )
                    elif tool_call.function.name == "execute_fs_write":
                        file_path = str(arguments.get("file_path", ""))
                        content = str(arguments.get("content", ""))
                        output = execute_fs_write(
                            sandbox,
                            file_path,
                            content,
                        )
                        actions.append(("fs_write", file_path))
                        if record_to_memory:
                            memory.log_tool_call(
                                "execute_fs_write",
                                {
                                    "file_path": file_path,
                                    "content": content,
                                },
                                output,
                                outcome=("failure" if output.startswith("FATAL:") else "success"),
                            )
                    else:
                        output = "FATAL: unknown tool"

                print(f"[OUTPUT] {output}")
                if output.startswith("SUCCESS: real health verifier passed"):
                    success = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": output[:1800],
                    }
                )
            if success:
                print("[VERIFIER SUCCESS — stopping agent loop]")
                break
    finally:
        if record_to_memory:
            memory.end_session("success" if success else "failure")

    return AgentResult(
        label=label,
        success=success,
        attempts=attempts,
        actions=actions,
        used_memory=used_memory,
        source_pasted=source_pasted,
    )


def run_teacher(client: Any, memory: Howdex) -> AgentResult:
    sandbox = create_docker_sandbox("howdex_docker_teacher_")
    try:
        result = run_agent(
            client=client,
            label="TEACHER — DOCKER RECOVERY DISCOVERY",
            sandbox=sandbox,
            memory=memory,
            record_to_memory=True,
            use_memory=False,
            model=TEACHER_MODEL,
            temperature=0.2,
        )
        print("\n[HOWDEX LEARN]")
        procedures = memory.learn(min_samples=1)
        print(f"learned_procedures={len(procedures)}")
        for procedure in procedures:
            print(f"- {procedure.task_signature} confidence={procedure.confidence}")
        return result
    finally:
        cleanup_sandbox(sandbox)


def run_arm(
    *,
    client: Any,
    arm_name: str,
    memory: Howdex,
    use_memory: bool,
    trials: int,
) -> list[AgentResult]:
    results: list[AgentResult] = []
    for trial in range(1, trials + 1):
        sandbox = create_docker_sandbox(f"howdex_docker_{arm_name.lower()}_{trial}_")
        try:
            results.append(
                run_agent(
                    client=client,
                    label=f"{arm_name} TRIAL {trial}/{trials}",
                    sandbox=sandbox,
                    memory=memory,
                    record_to_memory=False,
                    use_memory=use_memory,
                    model=STUDENT_MODEL,
                    temperature=0.7,
                )
            )
        finally:
            cleanup_sandbox(sandbox)
    return results


def summarize(results: list[AgentResult]) -> dict[str, Any]:
    successes = sum(result.success for result in results)
    attempts = [result.attempts for result in results]
    return {
        "trials": len(results),
        "successes": successes,
        "success_rate": successes / max(1, len(results)),
        "avg_attempts": sum(attempts) / max(1, len(attempts)),
        "memory_used": sum(result.used_memory for result in results),
        "source_pasted": sum(result.source_pasted for result in results),
    }


def _openai_client() -> Any:
    from openai import OpenAI

    return OpenAI()


def main() -> int:
    availability = check_docker_available()
    if not availability.available:
        print(f"SKIP — Docker recovery benchmark unavailable: {availability.reason}")
        return 0
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required to run this benchmark.")
        return 2

    from howdex import Howdex

    reset_db()
    memory = Howdex(path=DB_PATH, embedder="hashing")
    client = _openai_client()
    teacher = run_teacher(client, memory)
    if not teacher.success:
        print("\nREAL DOCKER RECOVERY A/B BENCHMARK")
        print("Teacher:")
        print("  success: False")
        print("Control:")
        print("  not run")
        print("Treatment:")
        print("  not run")
        print("Delta:")
        print("  not available")
        print("Verdict:")
        print("  FAIL — teacher did not establish a verified recovery.")
        return 1

    control_results = run_arm(
        client=client,
        arm_name="CONTROL_NO_MEMORY",
        memory=memory,
        use_memory=False,
        trials=N_TRIALS,
    )
    treatment_results = run_arm(
        client=client,
        arm_name="TREATMENT_HOWDEX_MEMORY",
        memory=memory,
        use_memory=True,
        trials=N_TRIALS,
    )
    control = summarize(control_results)
    treatment = summarize(treatment_results)
    delta = treatment["success_rate"] - control["success_rate"]
    attempt_reduction = control["avg_attempts"] - treatment["avg_attempts"]
    pass_condition = (
        teacher.success
        and treatment["success_rate"] >= 0.80
        and treatment["success_rate"] > control["success_rate"]
        and treatment["memory_used"] == treatment["trials"]
        and treatment["source_pasted"] == 0
        and attempt_reduction >= 0
    )

    print("\n" + "=" * 80)
    print("REAL DOCKER RECOVERY A/B BENCHMARK")
    print("=" * 80)
    print("\nTeacher:")
    print(f"  success: {teacher.success}")
    print(f"  attempts: {teacher.attempts}")
    print(f"  actions: {teacher.actions}")
    print("\nControl:")
    print(f"  trials: {control['trials']}")
    print(f"  successes: {control['successes']}")
    print(f"  success_rate: {control['success_rate']:.2f}")
    print(f"  avg_attempts: {control['avg_attempts']:.2f}")
    print("\nTreatment:")
    print(f"  trials: {treatment['trials']}")
    print(f"  successes: {treatment['successes']}")
    print(f"  success_rate: {treatment['success_rate']:.2f}")
    print(f"  avg_attempts: {treatment['avg_attempts']:.2f}")
    print(f"  howdex_memory_used: {treatment['memory_used']}/{treatment['trials']}")
    print(f"  source_pasted: {treatment['source_pasted']}/{treatment['trials']}")
    print("\nDelta:")
    print(f"  success_rate_lift: {delta:+.2f}")
    print(f"  attempt_reduction: {attempt_reduction:+.2f}")
    print("\nVerdict:")
    if pass_condition:
        print("  PASS")
        print(
            "  Howdex transferred a verified local Docker recovery "
            "procedure without pasting source."
        )
    else:
        print("  FAIL")
        print("  No defensible Docker recovery lift; inspect the honest control/treatment results.")
    print("\nMachine summary:")
    print(
        json.dumps(
            {
                "teacher_success": teacher.success,
                "control": control,
                "treatment": treatment,
                "success_rate_lift": delta,
                "attempt_reduction": attempt_reduction,
                "pass": pass_condition,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if pass_condition else 1


if __name__ == "__main__":
    raise SystemExit(main())
