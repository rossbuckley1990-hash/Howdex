"""
Polyglot MacGyver Crypto Transfer Benchmark

Question:
    Can Howdex transfer a Python-discovered algorithm into a Bash-only student
    environment without pasting source code?

Teacher:
    Python allowed. Discovers:
      seed.txt -> reverse -> SHA256 hex -> openssl AES-256-CBC decrypt password.

Control:
    Bash only. No memory. No algorithm prompt.

Treatment:
    Bash only. Receives Howdex-derived operational facts, not Python source.

Pass:
    Treatment beats control and decrypts TARGET using only Bash tools.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from benchmark_openai import get_openai_client

from howdex import Howdex
from howdex.core.guidance import render_agent_guidance


DB_PATH = ".howdex_polyglot.db"
TEACHER_MODEL = os.getenv("HOWDEX_POLY_TEACHER_MODEL", "gpt-4o")
STUDENT_MODEL = os.getenv("HOWDEX_POLY_STUDENT_MODEL", "gpt-4o-mini")
N_TRIALS = int(os.getenv("HOWDEX_POLY_TRIALS", "5"))
MAX_TURNS = int(os.getenv("HOWDEX_POLY_MAX_TURNS", "12"))

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
    attempts: int
    actions: list[tuple[str, str]]
    used_memory: bool
    source_pasted: bool


def reset_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(DB_PATH + suffix)
        if p.exists():
            p.unlink()


def run_local(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def openssl_available() -> bool:
    try:
        result = subprocess.run(
            ["openssl", "version"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def create_crypto_challenge(prefix: str, seed: str, target: str) -> Path:
    sandbox = Path(tempfile.mkdtemp(prefix=prefix)).resolve()

    (sandbox / "seed.txt").write_text(seed)
    (sandbox / "plain.txt").write_text(target)

    key = sha256(seed[::-1].encode("utf-8")).hexdigest()

    result = run_local(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-salt",
            "-pbkdf2",
            "-in",
            "plain.txt",
            "-out",
            "vault.enc",
            "-pass",
            f"pass:{key}",
        ],
        sandbox,
    )

    if result.returncode != 0:
        raise RuntimeError(f"openssl encrypt failed: {result.stderr}")

    (sandbox / "plain.txt").unlink()
    return sandbox


def safe_path(workdir: Path, file_path: str) -> Path:
    candidate = (workdir / file_path).resolve()
    root = workdir.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Unsafe path outside sandbox: {file_path}")
    return candidate


def execute_fs_write(workdir: Path, file_path: str, content: str, allow_python: bool) -> str:
    allowed = {"decrypt.py", "probe.py", "notes.txt", "solve.sh"}

    if file_path not in allowed:
        return f"FATAL: only these files may be written: {sorted(allowed)}"

    if not allow_python and file_path.endswith(".py"):
        return "FATAL: Python files are disabled by policy. Use Bash tools only."

    target = safe_path(workdir, file_path)
    target.write_text(content)
    if file_path.endswith(".sh"):
        target.chmod(0o755)

    preview = content[:160].replace("\n", " ")
    print(f"[FS_WRITE] {file_path}: {preview}...")
    return f"wrote {file_path}"


def execute_bash(workdir: Path, cmd: str, allow_python: bool, expected_target: str) -> str:
    print(f"[EXEC] {cmd}")

    if not allow_python and re.search(r"\bpython(3)?\b|\.py\b", cmd):
        return "FATAL: Python is unavailable in this student environment."

    if allow_python:
        # Teacher exploration is intentionally broader. The teacher is allowed
        # to discover the algorithm using Python or shell probes. Student arms
        # remain restricted below.
        allowed_prefixes = (
            "python3 decrypt.py",
            "python3 probe.py",
            "cat seed.txt",
            "rev seed.txt",
            "echo -n ",
            "printf ",
            "openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | awk '{print $1}') -in vault.enc",
            "openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | sha256sum | awk '{print $1}') -in vault.enc",
            "cat vault.enc | openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | awk '{print $1}')",
            "cat vault.enc | openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | sha256sum | awk '{print $1}')",
            "bash solve.sh",
            "./solve.sh",
            "openssl enc -d -aes-256-cbc -pbkdf2 ",
        )
        if not cmd.startswith(allowed_prefixes):
            return (
                "FATAL: teacher command not allowed. Use python3 decrypt.py, "
                "python3 probe.py, cat/rev/echo/printf probes, bash solve.sh, "
                "or openssl AES-256-CBC decrypt."
            )

        result = subprocess.run(
            cmd,
            cwd=str(workdir),
            shell=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=False,
            executable="/bin/bash",
        )

        output = (result.stdout + "\n" + result.stderr).strip()

        if expected_target in output:
            return f"SUCCESS: decrypted {expected_target}"

        if result.returncode != 0:
            return f"FATAL: command exited {result.returncode}. Output: {output[:1000]}"

        return output[:1000] if output else "command produced no output"

    else:
        allowed = {
            "cat seed.txt",
            "rev seed.txt",
            "shasum -a 256 seed.txt",
            "cat seed.txt | rev",
            "cat seed.txt | rev | shasum -a 256",
            "cat seed.txt | rev | shasum -a 256 | awk '{print $1}'",
            "cat seed.txt | rev | sha256sum",
            "cat seed.txt | rev | sha256sum | awk '{print $1}'",
            "printf %s \"$(cat seed.txt | rev)\"",
            "printf %s \"$(cat seed.txt | rev)\" | shasum -a 256",
            "printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | awk '{print $1}'",
            "printf %s \"$(cat seed.txt | rev)\" | sha256sum",
            "printf %s \"$(cat seed.txt | rev)\" | sha256sum | awk '{print $1}'",
            "openssl enc -d -aes-256-cbc -pbkdf2 -in vault.enc -pass pass:$(cat seed.txt | rev | shasum -a 256 | awk '{print $1}')",
            "openssl enc -d -aes-256-cbc -pbkdf2 -in vault.enc -pass pass:$(cat seed.txt | rev | sha256sum | awk '{print $1}')",
            "openssl enc -d -aes-256-cbc -pbkdf2 -in vault.enc -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | awk '{print $1}')",
            "openssl enc -d -aes-256-cbc -pbkdf2 -in vault.enc -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | sha256sum | awk '{print $1}')",
            "cat vault.enc | openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(cat seed.txt | rev | shasum -a 256 | awk '{print $1}')",
            "cat vault.enc | openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(cat seed.txt | rev | sha256sum | awk '{print $1}')",
            "cat vault.enc | openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | awk '{print $1}')",
            "cat vault.enc | openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:$(printf %s \"$(cat seed.txt | rev)\" | sha256sum | awk '{print $1}')",
            "bash solve.sh",
            "./solve.sh",
        }

    # Student arms are Bash-only, but the exact safe command shape can vary.
    # This gate allows safe local read/hash/decrypt pipelines while banning
    # Python, writes, network, process substitution, redirects, and destructive tools.
    banned_patterns = [
        r"\bpython(3)?\b",
        r"\.py\b",
        r"\bperl\b",
        r"\bruby\b",
        r"\bnode\b",
        r"\bcurl\b",
        r"\bwget\b",
        r"\brm\b",
        r"\bmv\b",
        r"\bcp\b",
        r"\bdd\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\bsudo\b",
        r">",
        r"<",
        r"`",
        r";",
        r"&&",
        r"\|\|",
        r"/dev/tcp",
    ]

    allowed_tool_names = {
        "cat",
        "rev",
        "printf",
        "echo",
        "shasum",
        "sha256sum",
        "awk",
        "openssl",
        "bash",
        "./solve.sh",
    }

    def _is_safe_bash_command(command: str) -> bool:
        if any(re.search(pattern, command) for pattern in banned_patterns):
            return False

        # Only allow commands that interact with the benchmark files or the
        # derived password pipeline.
        if not any(token in command for token in ("seed.txt", "vault.enc", "solve.sh", "77_")):
            return False

        # Split simple pipelines and command substitutions into first command words.
        normalized = (
            command.replace("$(", " ")
            .replace(")", " ")
            .replace("|", " | ")
            .replace('"', " ")
            .replace("'", " ")
        )
        parts = [part.strip() for part in normalized.split("|") if part.strip()]

        for part in parts:
            word = part.split()[0] if part.split() else ""
            if word not in allowed_tool_names:
                return False

        return True

    # Common Bash translation bug: printf does not read stdin. This hashes
    # the empty string and produces e3b0c442..., so return a precise correction.
    if "cat seed.txt | rev | printf" in cmd:
        return (
            "FATAL: invalid Bash translation. printf does not read from stdin. "
            "Use command substitution instead: "
            "printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | awk '{print $1}'"
        )

    # Prevent interactive OpenSSL password prompts. Any decrypt attempt must
    # supply the derived password non-interactively and use PBKDF2.
    if "openssl" in cmd and "enc" in cmd and "-d" in cmd:
        if "-pbkdf2" not in cmd or "-pass pass:" not in cmd:
            return (
                "FATAL: openssl decrypt command must be non-interactive and include "
                "-pbkdf2 and -pass pass:<derived_hash>."
            )

    if cmd not in allowed and not _is_safe_bash_command(cmd):
        return (
            "FATAL: command not allowed. Use only permitted local Bash tools: "
            "cat, rev, printf, echo -n, shasum -a 256 or sha256sum, awk, openssl, bash solve.sh."
        )

    result = subprocess.run(
        cmd,
        cwd=str(workdir),
        shell=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=10,
        check=False,
        executable="/bin/bash",
    )

    output = (result.stdout + "\n" + result.stderr).strip()

    if expected_target in output:
        return f"SUCCESS: decrypted {expected_target}"

    if result.returncode != 0:
        return f"FATAL: command exited {result.returncode}. Output: {output[:1000]}"

    return output[:1000] if output else "command produced no output"


def raw_examples_from_sqlite() -> list[dict[str, Any]]:
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
    """Detect source-code leakage conservatively in treatment guidance."""
    patterns = (
        r"```",
        r"(?m)^\s*(?:from\s+\S+\s+import\s+|import\s+\S+)",
        r"(?m)^\s*(?:async\s+)?def\s+\w+\s*\(",
        r"(?m)^\s*class\s+\w+",
        r"\bhashlib\.",
        r"\bsubprocess(?:\.|\s+import\b)",
        r"\bseed\s*\[\s*::\s*-1\s*\]",
        r"(?m)^\s*#!.*python",
    )
    return any(re.search(pattern, guidance) for pattern in patterns)


def build_polyglot_memory(memory: Howdex) -> tuple[str, bool, bool]:
    suggestions = memory.suggest_procedure(
        "Decrypt vault.enc from seed.txt by deriving the openssl password.",
        top_k=5,
        min_confidence=0.0,
    )

    examples = raw_examples_from_sqlite()

    observed_text = ""
    observed_success = False

    for example in examples:
        for step in example.get("steps", []) or []:
            if not isinstance(step, dict):
                continue

            args = step.get("tool_args") or step.get("args") or {}
            observation = str(step.get("observation") or step.get("output") or "")

            if isinstance(args, dict):
                observed_text += "\n" + str(args.get("content") or "")
                observed_text += "\n" + str(args.get("cmd") or "")
            observed_text += "\n" + observation

            if "SUCCESS: decrypted" in observation or "TARGET:" in observation:
                observed_success = True

    lower = observed_text.lower()

    facts: list[str] = []

    if "seed.txt" in lower:
        facts.append("read the raw contents of seed.txt")

    if "[::-1]" in lower or "reverse" in lower or "reversed" in lower:
        facts.append("reverse the seed string before hashing it")

    if "sha256" in lower or "hashlib" in lower:
        facts.append("calculate the SHA256 hex digest of the reversed seed")

    if "hashlib.sha256" in lower or ".encode" in lower or "read_text" in lower:
        facts.append("hash the reversed seed bytes exactly, with no trailing newline")

    if "aes-256-cbc" in lower:
        facts.append("decrypt vault.enc with openssl AES-256-CBC")

    if "pbkdf2" in lower:
        facts.append("include the -pbkdf2 flag when decrypting")

    if "pass:" in lower or "-pass" in lower:
        facts.append("use the SHA256 hex digest as the openssl password via -pass pass:<hash>")

    if not facts and suggestions:
        facts.append("prior memory indicates the vault password is derived from seed.txt, not guessed")

    has_memory = bool(suggestions) and observed_success and len(facts) >= 4

    learned_facts = [
        *facts,
        "reverse text with rev",
        (
            "avoid adding a newline before hashing by using command "
            "substitution"
        ),
        (
            "use this exact corrected Bash hash shape: "
            "printf %s \"$(cat seed.txt | rev)\" | shasum -a 256 | "
            "awk '{print $1}'"
        ),
        "compute SHA256 on macOS with shasum -a 256",
        "extract the hash column with awk '{print $1}'",
        "decrypt using openssl enc -d -aes-256-cbc -pbkdf2",
    ]
    primary = suggestions[0] if suggestions else None
    payload = {
        "task_signature": (
            getattr(primary, "task_signature", None)
            or "polyglot crypto transfer"
        ),
        "confidence": getattr(primary, "confidence", None),
        "support_count": getattr(primary, "support_count", None),
        "learned_facts": learned_facts,
        "failed_attempts": [
            "cat seed.txt | rev | printf %s | shasum -a 256",
        ],
        "verification": [
            (
                "Success requires the real openssl command to output the "
                "TARGET string."
            ),
            "Do not claim completion until the real verifier reports SUCCESS.",
        ],
    }
    guidance = render_agent_guidance(
        [payload],
        objective="Decrypt vault.enc and reveal the hidden TARGET string.",
        constraints=[
            "Python is unavailable.",
            "Use Bash tools only.",
            "Do not paste or reconstruct Python source code.",
        ],
        target_environment="Bash-only student sandbox",
        include_source=False,
        include_failed_attempts=True,
        include_verification=True,
    )

    return guidance, has_memory, source_pasted_in_guidance(guidance)


def run_agent(
    *,
    label: str,
    workdir: Path,
    expected_target: str,
    memory: Howdex,
    record_to_memory: bool,
    use_memory: bool,
    allow_python: bool,
    model: str,
    temperature: float,
) -> AgentResult:
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)

    used_memory = False
    source_pasted = False
    memory_guidance = ""

    if use_memory:
        memory_guidance, used_memory, source_pasted = build_polyglot_memory(memory)
        print("\n[HOWDEX POLYGLOT MEMORY]")
        print(memory_guidance)
        print(f"[HOWDEX MEMORY AVAILABLE]: {used_memory}")
        print(f"[HOWDEX SOURCE PASTED]: {source_pasted}")

    if record_to_memory:
        memory.start_session("polyglot_crypto_teacher")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_bash",
                "description": "Run an allowed command in the sandbox.",
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
                "description": "Write an allowed file in the sandbox.",
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

    if record_to_memory:
        task_prompt = f"""
You are the teacher run. Python is allowed.

Objective:
Decrypt vault.enc and reveal the hidden TARGET string.

You are not initially told the whole algorithm. Discover it using files and tools.

Teacher-only discovery scaffold:
- seed.txt is involved in deriving the password.
- vault.enc is an openssl-encrypted file.
- Do not use PyCryptodome/Crypto; it is not installed.
- Use Python standard library hashlib for SHA256.
- Read seed.txt exactly as text, with no added newline.
- Reverse the seed string with seed[::-1].
- Compute hashlib.sha256(reversed_seed.encode("utf-8")).hexdigest().
- Use that hex digest as the OpenSSL password.
- Use the real OpenSSL CLI for decryption:
  openssl enc -d -aes-256-cbc -pbkdf2 -in vault.enc -pass pass:<HASH>
- Do not use -out decrypted.txt; print decrypted stdout so the verifier can see TARGET.
- Write decrypt.py if useful, using subprocess.run([...], capture_output=True, text=True).
- Verify by producing the exact TARGET string.

Allowed:
- Python scripts are allowed.
- Bash is allowed.
"""
    elif use_memory:
        task_prompt = f"""
You are the treatment student. Python is banned.

Objective:
Decrypt vault.enc and reveal the hidden TARGET string.

Rules:
- You may not write or run Python.
- Use Bash tools only: cat, rev, printf, shasum -a 256 or sha256sum, awk, openssl.
- Use Howdex memory if available.
- When hashing command-substitution output, avoid adding a newline: use printf %s "$(cat seed.txt | rev)".
- Do not pipe into printf. The form cat seed.txt | rev | printf %s hashes empty input and will fail.
- Do not claim DONE until the real verifier reports SUCCESS.

{memory_guidance}
"""
    else:
        task_prompt = """
You are the control student. Python is banned.

Objective:
Decrypt vault.enc and reveal the hidden TARGET string.

Rules:
- You may not write or run Python.
- Use Bash tools only: cat, rev, printf, shasum -a 256 or sha256sum, awk, openssl.
- No prior memory is available.
- You are not told the password-derivation algorithm.
- Do not claim DONE until the real verifier reports SUCCESS.
"""

    messages: list[dict[str, Any]] = [{"role": "system", "content": task_prompt}]

    attempts = 0
    actions: list[tuple[str, str]] = []
    success = False

    for _turn in range(MAX_TURNS):
        response = _openai_client().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content and "DONE" in message.content.upper():
            if success:
                print("[DONE accepted]")
                break
            messages.append(
                {
                    "role": "user",
                    "content": "DONE rejected. You must receive SUCCESS from the verifier first.",
                }
            )
            continue

        if not message.tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Continue using tool calls until the real verifier reports SUCCESS.",
                }
            )
            continue

        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments)

            if tool_call.function.name == "execute_bash":
                attempts += 1
                output = execute_bash(workdir, args["cmd"], allow_python, expected_target)
                actions.append(("bash", args["cmd"]))
                if record_to_memory:
                    memory.log_tool_call("execute_bash", {"cmd": args["cmd"]}, output)
                if f"SUCCESS: decrypted {expected_target}" in output:
                    success = True

            elif tool_call.function.name == "execute_fs_write":
                output = execute_fs_write(
                    workdir,
                    args["file_path"],
                    args["content"],
                    allow_python,
                )
                actions.append(("fs_write", args["file_path"]))
                if record_to_memory:
                    memory.log_tool_call(
                        "execute_fs_write",
                        {"file_path": args["file_path"], "content": args["content"]},
                        output,
                    )

            else:
                output = "FATAL: unknown tool"

            print(f"[OUTPUT] {output[:500]}")

            chat_output = output if len(output) <= 1000 else output[:1000] + "\n...[truncated]"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": chat_output,
                }
            )

        if success:
            print("[VERIFIER SUCCESS — stopping agent loop]")
            break

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


def summarize(results: list[AgentResult]) -> dict[str, Any]:
    successes = sum(1 for r in results if r.success)
    return {
        "trials": len(results),
        "successes": successes,
        "success_rate": successes / max(1, len(results)),
        "avg_attempts": sum(r.attempts for r in results) / max(1, len(results)),
        "memory_used": sum(1 for r in results if r.used_memory),
        "source_pasted": sum(1 for r in results if r.source_pasted),
    }


def run_benchmark() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required.")
    if not openssl_available():
        raise SystemExit("openssl is required.")

    reset_db()
    memory = Howdex(path=DB_PATH, embedder="hashing")

    teacher_sandbox = create_crypto_challenge(
        "howdex_poly_teacher_",
        seed="alpha_tango_99",
        target="TARGET:OMEGA_PROTOCOL",
    )

    try:
        teacher = run_agent(
            label="TEACHER — PYTHON CRYPTO DISCOVERY",
            workdir=teacher_sandbox,
            expected_target="TARGET:OMEGA_PROTOCOL",
            memory=memory,
            record_to_memory=True,
            use_memory=False,
            allow_python=True,
            model=TEACHER_MODEL,
            temperature=0.2,
        )
        print("\n[HOWDEX LEARN]")
        procedures = memory.learn(min_samples=1)
        print(f"learned_procedures={len(procedures)}")
        for p in procedures:
            print(f"- {getattr(p, 'task_signature', None)} confidence={getattr(p, 'confidence', None)}")
    finally:
        shutil.rmtree(teacher_sandbox, ignore_errors=True)

    if not teacher.success:
        print("\nPOLYGLOT MACGYVER BENCHMARK")
        print("teacher_success=false")
        print("verdict=FAIL")
        return

    control_results: list[AgentResult] = []
    treatment_results: list[AgentResult] = []

    for i in range(1, N_TRIALS + 1):
        seed = f"bravo_delta_{i}_77"
        target = f"TARGET:POLYGLOT_{i}"

        control_sandbox = create_crypto_challenge(
            f"howdex_poly_control_{i}_",
            seed=seed,
            target=target,
        )
        try:
            control_results.append(
                run_agent(
                    label=f"CONTROL — BASH ONLY NO MEMORY {i}/{N_TRIALS}",
                    workdir=control_sandbox,
                    expected_target=target,
                    memory=memory,
                    record_to_memory=False,
                    use_memory=False,
                    allow_python=False,
                    model=STUDENT_MODEL,
                    temperature=0.7,
                )
            )
        finally:
            shutil.rmtree(control_sandbox, ignore_errors=True)

        treatment_sandbox = create_crypto_challenge(
            f"howdex_poly_treatment_{i}_",
            seed=seed,
            target=target,
        )
        try:
            treatment_results.append(
                run_agent(
                    label=f"TREATMENT — BASH ONLY WITH HOWDEX {i}/{N_TRIALS}",
                    workdir=treatment_sandbox,
                    expected_target=target,
                    memory=memory,
                    record_to_memory=False,
                    use_memory=True,
                    allow_python=False,
                    model=STUDENT_MODEL,
                    temperature=0.7,
                )
            )
        finally:
            shutil.rmtree(treatment_sandbox, ignore_errors=True)

    control = summarize(control_results)
    treatment = summarize(treatment_results)
    delta = treatment["success_rate"] - control["success_rate"]
    attempt_reduction = control["avg_attempts"] - treatment["avg_attempts"]

    pass_condition = (
        treatment["success_rate"] >= 0.80
        and treatment["success_rate"] > control["success_rate"]
        and treatment["memory_used"] == treatment["trials"]
        and treatment["source_pasted"] == 0
        and attempt_reduction >= 0
    )

    print("\n" + "=" * 80)
    print("POLYGLOT MACGYVER CRYPTO TRANSFER BENCHMARK")
    print("=" * 80)

    print("\nTeacher:")
    print(f"  success: {teacher.success}")
    print(f"  attempts: {teacher.attempts}")

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
        print("  Howdex reliably transferred Python-discovered operational knowledge into Bash-only execution without pasting source code.")
    else:
        print("  FAIL")
        print("  No defensible polyglot capability-lift claim.")

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


if __name__ == "__main__":
    run_benchmark()
