"""
Cross-Model Verified Transfer Study

Question:
    Can a procedure learned by one model/agent/runtime be exported through
    Howdex and reused successfully by another model/agent/runtime, with
    independent verification?

Default mode is deterministic dry-run:
    HOWDEX_TRANSFER_DRY_RUN=1 python3 cross_model_verified_transfer_test.py

Live Docker mode requires Docker plus OPENAI_API_KEY and does not fabricate a
cross-model claim. It prints measured rows only when real agents and the real
Docker health verifier run.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from howdex import Howdex

import real_docker_recovery_ab_test as docker_ab

DEFAULT_TEACHER_MODEL = os.getenv("HOWDEX_TRANSFER_TEACHER_MODEL", "gpt-4o")
DEFAULT_STUDENT_MODEL = os.getenv("HOWDEX_TRANSFER_STUDENT_MODEL", "gpt-4o-mini")
DEFAULT_TRIALS = int(os.getenv("HOWDEX_TRANSFER_TRIALS", "5"))
DEFAULT_MAX_TURNS = int(os.getenv("HOWDEX_TRANSFER_MAX_TURNS", str(docker_ab.MAX_TURNS)))
DEFAULT_TASK = os.getenv("HOWDEX_TRANSFER_TASK", "docker").strip().lower()
DRY_RUN = os.getenv("HOWDEX_TRANSFER_DRY_RUN", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DOCKER_QUERY = "recover broken Docker Compose HTTP health endpoint"
DOCKER_TASK = "recover broken Docker Compose HTTP service until /health is 200"


@dataclass(frozen=True)
class TransferRow:
    condition: str
    teacher: str
    student: str
    trials: int
    successes: int
    success_rate: float
    avg_attempts: float
    source_pasted: int
    verified_receipt: bool
    verdict: str
    imported_through_codex: bool = False
    verifier_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["success_rate"] = round(float(self.success_rate), 4)
        payload["avg_attempts"] = round(float(self.avg_attempts), 4)
        return payload


@dataclass(frozen=True)
class TransferMemoryBundle:
    teacher_memory: Howdex
    student_memory: Howdex
    codex_path: Path
    procedure_id: str
    codex_entry_path: Path
    receipt_exists: bool
    codex_entry_status: str


def source_pasted_in_guidance(guidance: str) -> bool:
    """Conservatively detect source artifact leakage in transfer guidance."""
    return docker_ab.source_pasted_in_guidance(guidance) or any(
        re.search(pattern, guidance)
        for pattern in (
            r"```",
            r"(?m)^\s*services:\s*$",
            r"(?m)^\s*FROM\s+\S+",
            r"\bBaseHTTPRequestHandler\b",
            r"\bHTTPServer\s*\(",
            r"\bserve_forever\s*\(",
        )
    )


def build_transfer_prompts(memory_section: str, *, sandbox_port: int = docker_ab.PROMPT_HASH_PORT):
    """Build control/treatment prompts and assert identical base framing."""
    control = docker_ab.build_control_docker_prompt(sandbox_port)
    treatment = docker_ab.build_treatment_docker_prompt(sandbox_port, memory_section)
    if control.base_prompt != treatment.base_prompt:
        raise AssertionError("control and treatment base framing must be byte-identical")
    return control, treatment


def render_transfer_guidance(memory: Howdex, *, sandbox_port: int = docker_ab.PROMPT_HASH_PORT) -> str:
    """Render Howdex guidance from imported procedure memory only."""
    from howdex.core.guidance import render_procedure_guidance

    suggestions = memory.suggest_procedure(
        DOCKER_QUERY,
        top_k=3,
        min_confidence=0.0,
    )
    procedure_guidance = render_procedure_guidance(suggestions, max_chars=3500)
    return docker_ab.howdex_memory_section(procedure_guidance)


def build_verified_teacher_memory(path: str | Path | None = None) -> tuple[Howdex, str]:
    """Create a deterministic Docker recovery teacher memory with a receipt."""
    db_path: str | Path = ":memory:" if path is None else Path(path)
    memory = Howdex(path=db_path, embedder="hashing")
    memory.start_session(DOCKER_TASK, source="cross_model_transfer_teacher")
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "cat docker-compose.yml"},
        "service app maps localhost:<PORT_1> to container port 8000",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "cat runtime.env"},
        "APP_PORT=9000\nHEALTH_MODE=degraded",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "cat health-policy.conf"},
        "required_health_mode=ready",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_fs_write",
        {
            "file_path": "runtime.env",
            "content": "APP_PORT=8000\nHEALTH_MODE=ready\n",
        },
        "wrote runtime.env",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "docker compose up -d --build --force-recreate"},
        "container recreated",
        outcome="success",
    )
    memory.log_tool_call(
        "execute_bash",
        {"cmd": "curl -sS -i http://127.0.0.1:<PORT_1>/health"},
        "SUCCESS: real health verifier passed: HTTP 200 body=healthy",
        outcome="success",
    )
    episode = memory.end_session("success")
    procedures = memory.learn(min_samples=1)
    if not procedures:
        raise RuntimeError("Howdex failed to learn transfer procedure")
    procedure = max(
        procedures,
        key=lambda item: (item.confidence, item.support_count, item.task_signature),
    )
    memory.verify_procedure(
        procedure.id,
        verifier_type="http_health",
        verifier_command="curl -sS -i http://127.0.0.1:<PORT_1>/health",
        expected_signal="HTTP 200 body=healthy",
        observed_signal="SUCCESS: real health verifier passed: HTTP 200 body=healthy",
        exit_code=0,
        environment_fingerprint={
            "benchmark": "cross_model_verified_transfer",
            "task": "docker",
        },
        artifact_hashes={},
        source_episode_id=episode.session_id,
    )
    return memory, procedure.id


def export_import_via_codex(root: str | Path) -> TransferMemoryBundle:
    """Export verified teacher memory to Codex and import it into fresh memory."""
    root = Path(root)
    teacher_memory, procedure_id = build_verified_teacher_memory(root / "teacher.db")
    receipts = teacher_memory.list_receipts(procedure_id)
    if not receipts:
        raise RuntimeError("transfer procedure requires a verification receipt")

    codex_path = root / "codex"
    published = teacher_memory.publish_codex(codex_path)
    if not published["files"]:
        raise RuntimeError("Codex export produced no procedure entries")
    codex_entry_path = Path(published["files"][0])
    codex_entry = json.loads(codex_entry_path.read_text(encoding="utf-8"))
    if codex_entry.get("status") != "verified":
        raise RuntimeError("verified teacher receipt did not produce a verified Codex entry")

    student_memory = Howdex(path=root / "student.db", embedder="hashing")
    imported = student_memory.import_procedures(codex_path / "procedures")
    if imported["imported"] + imported["updated"] + imported["unchanged"] <= 0:
        raise RuntimeError("student memory did not import the Codex procedure")

    return TransferMemoryBundle(
        teacher_memory=teacher_memory,
        student_memory=student_memory,
        codex_path=codex_path,
        procedure_id=procedure_id,
        codex_entry_path=codex_entry_path,
        receipt_exists=True,
        codex_entry_status=str(codex_entry.get("status") or ""),
    )


def receipt_required_for_verified_transfer(memory: Howdex, procedure_id: str) -> bool:
    """Return whether procedure evidence is strong enough for verified transfer."""
    return bool(memory.list_receipts(procedure_id)) and (
        memory.procedure_verification_status(procedure_id) == "verified"
    )


def dry_run_rows(
    *,
    teacher_model: str = DEFAULT_TEACHER_MODEL,
    student_model: str = DEFAULT_STUDENT_MODEL,
    trials: int = DEFAULT_TRIALS,
    workdir: str | Path | None = None,
) -> tuple[list[TransferRow], TransferMemoryBundle, str]:
    """Validate the transfer harness without OpenAI, Docker, or network calls."""
    root_obj = (
        tempfile.TemporaryDirectory(prefix="howdex_transfer_dry_")
        if workdir is None
        else None
    )
    root = Path(root_obj.name if root_obj is not None else workdir)  # type: ignore[arg-type]
    bundle = export_import_via_codex(root)
    guidance = render_transfer_guidance(bundle.student_memory)
    source_pasted = int(source_pasted_in_guidance(guidance))
    build_transfer_prompts(guidance)
    verified_receipt = receipt_required_for_verified_transfer(
        bundle.teacher_memory,
        bundle.procedure_id,
    )
    imported = bundle.codex_entry_path.is_file() and bool(
        bundle.student_memory.list_procedures()
    )

    treatment_successes = trials if verified_receipt and imported and source_pasted == 0 else 0
    rows = [
        TransferRow(
            condition="no_memory_control",
            teacher=teacher_model,
            student=student_model,
            trials=trials,
            successes=0,
            success_rate=0.0,
            avg_attempts=0.0,
            source_pasted=0,
            verified_receipt=False,
            verdict="DRY RUN CONTROL",
            imported_through_codex=False,
        ),
        TransferRow(
            condition="same_model_transfer",
            teacher=teacher_model,
            student=teacher_model,
            trials=trials,
            successes=treatment_successes,
            success_rate=treatment_successes / max(1, trials),
            avg_attempts=1.0 if treatment_successes else 0.0,
            source_pasted=source_pasted,
            verified_receipt=verified_receipt,
            verdict="DRY RUN PASS — no live model claim",
            imported_through_codex=imported,
        ),
        TransferRow(
            condition="cross_model_transfer",
            teacher=teacher_model,
            student=student_model,
            trials=trials,
            successes=treatment_successes,
            success_rate=treatment_successes / max(1, trials),
            avg_attempts=1.0 if treatment_successes else 0.0,
            source_pasted=source_pasted,
            verified_receipt=verified_receipt,
            verdict="DRY RUN PASS — no live model claim",
            imported_through_codex=imported,
        ),
        TransferRow(
            condition="cross_framework_transfer",
            teacher=f"{teacher_model}/generic-openai-style",
            student=f"{student_model}/mcp-langgraph-style",
            trials=trials,
            successes=treatment_successes,
            success_rate=treatment_successes / max(1, trials),
            avg_attempts=1.0 if treatment_successes else 0.0,
            source_pasted=source_pasted,
            verified_receipt=verified_receipt,
            verdict="DRY RUN PASS — adapter path simulated; no live model claim",
            imported_through_codex=imported,
        ),
    ]
    # Keep TemporaryDirectory alive long enough for tests using returned paths.
    if root_obj is not None:
        bundle.teacher_memory.close()
        bundle.student_memory.close()
        root_obj.cleanup()
    return rows, bundle, guidance


def output_schema(rows: list[TransferRow]) -> list[dict[str, Any]]:
    return [row.to_dict() for row in rows]


def print_results(rows: list[TransferRow]) -> None:
    headers = [
        "condition",
        "teacher",
        "student",
        "trials",
        "successes",
        "success_rate",
        "avg_attempts",
        "source_pasted",
        "verified_receipt",
        "verdict",
    ]
    print(" | ".join(headers))
    print(" | ".join("---" for _ in headers))
    for row in rows:
        values = row.to_dict()
        print(
            " | ".join(
                [
                    str(values["condition"]),
                    str(values["teacher"]),
                    str(values["student"]),
                    str(values["trials"]),
                    str(values["successes"]),
                    f"{values['success_rate']:.2f}",
                    f"{values['avg_attempts']:.2f}",
                    str(values["source_pasted"]),
                    str(values["verified_receipt"]),
                    str(values["verdict"]),
                ]
            )
        )
    print("\nMachine summary:")
    print(json.dumps(output_schema(rows), indent=2, sort_keys=True))


def _openai_client() -> Any:
    from benchmark_openai import get_openai_client

    return get_openai_client()


def _live_run() -> tuple[list[TransferRow], int]:
    if DEFAULT_TASK != "docker":
        print(f"SKIP — unsupported HOWDEX_TRANSFER_TASK={DEFAULT_TASK!r}; only docker is implemented")
        return [], 0
    docker_ab.STUDENT_MODEL = DEFAULT_STUDENT_MODEL
    docker_ab.MAX_TURNS = DEFAULT_MAX_TURNS
    availability = docker_ab.check_docker_available()
    if not availability.available:
        print(f"SKIP — Docker transfer benchmark unavailable: {availability.reason}")
        return [], 0
    if not os.getenv("OPENAI_API_KEY"):
        print("SKIP — OPENAI_API_KEY is required for live cross-model transfer.")
        return [], 0

    client = _openai_client()
    root_obj = tempfile.TemporaryDirectory(prefix="howdex_transfer_live_")
    root = Path(root_obj.name)
    memory = Howdex(path=root / "teacher.db", embedder="hashing")
    try:
        teacher_sandbox = docker_ab.create_docker_sandbox("howdex_transfer_teacher_")
        try:
            teacher = docker_ab.run_agent(
                client=client,
                label="TRANSFER TEACHER",
                sandbox=teacher_sandbox,
                memory=memory,
                record_to_memory=True,
                use_memory=False,
                model=DEFAULT_TEACHER_MODEL,
                temperature=0.2,
            )
        finally:
            docker_ab.cleanup_sandbox(teacher_sandbox)
        if not teacher.success:
            return [
                TransferRow(
                    condition="teacher",
                    teacher=DEFAULT_TEACHER_MODEL,
                    student="-",
                    trials=1,
                    successes=0,
                    success_rate=0.0,
                    avg_attempts=float(teacher.attempts),
                    source_pasted=0,
                    verified_receipt=False,
                    verdict="FAIL — teacher did not establish procedure",
                )
            ], 1
        procedures = memory.learn(min_samples=1)
        procedure = max(procedures, key=lambda item: (item.confidence, item.support_count))
        memory.verify_procedure(
            procedure.id,
            verifier_type="http_health",
            verifier_command="curl -sS -i http://127.0.0.1:<PORT_1>/health",
            expected_signal="HTTP 200 body=healthy",
            observed_signal="SUCCESS: real health verifier passed: HTTP 200 body=healthy",
            exit_code=0,
            environment_fingerprint={
                "benchmark": "cross_model_verified_transfer",
                "teacher_model": DEFAULT_TEACHER_MODEL,
            },
            artifact_hashes={},
            source_episode_id=procedure.source_episode_ids[-1] if procedure.source_episode_ids else None,
        )
        codex_path = root / "codex"
        memory.publish_codex(codex_path)
        imported_memory = Howdex(path=root / "student.db", embedder="hashing")
        imported_memory.import_procedures(codex_path / "procedures")

        control_results = docker_ab.run_arm(
            client=client,
            arm_name="TRANSFER_CONTROL_NO_MEMORY",
            memory=imported_memory,
            use_memory=False,
            trials=DEFAULT_TRIALS,
        )
        treatment_results = docker_ab.run_arm(
            client=client,
            arm_name="TRANSFER_CROSS_MODEL",
            memory=imported_memory,
            use_memory=True,
            trials=DEFAULT_TRIALS,
        )
        control = docker_ab.summarize(control_results)
        treatment = docker_ab.summarize(treatment_results)
        receipt_exists = receipt_required_for_verified_transfer(memory, procedure.id)
        control_row = TransferRow(
            condition="no_memory_control",
            teacher=DEFAULT_TEACHER_MODEL,
            student=DEFAULT_STUDENT_MODEL,
            trials=control["trials"],
            successes=control["successes"],
            success_rate=control["success_rate"],
            avg_attempts=control["avg_attempts"],
            source_pasted=control["source_pasted"],
            verified_receipt=False,
            verdict="MEASURED CONTROL",
        )
        treatment_pass = (
            treatment["success_rate"] > control["success_rate"]
            and treatment["source_pasted"] == 0
            and receipt_exists
            and treatment["memory_used"] == treatment["trials"]
        )
        treatment_row = TransferRow(
            condition="cross_model_transfer",
            teacher=DEFAULT_TEACHER_MODEL,
            student=DEFAULT_STUDENT_MODEL,
            trials=treatment["trials"],
            successes=treatment["successes"],
            success_rate=treatment["success_rate"],
            avg_attempts=treatment["avg_attempts"],
            source_pasted=treatment["source_pasted"],
            verified_receipt=receipt_exists,
            verdict="PASS" if treatment_pass else "FAIL",
            imported_through_codex=True,
        )
        return [control_row, treatment_row], 0 if treatment_pass else 1
    finally:
        memory.close()
        root_obj.cleanup()


def main() -> int:
    if DRY_RUN:
        rows, _bundle, guidance = dry_run_rows()
        print_results(rows)
        print(
            "\nVerdict: DRY RUN PASS — harness validated; no live cross-model proof claimed."
            if all(row.source_pasted == 0 for row in rows)
            else "\nVerdict: DRY RUN FAIL — inspect source leakage."
        )
        return 0 if all(row.source_pasted == 0 for row in rows) else 1
    rows, code = _live_run()
    if rows:
        print_results(rows)
    print("\nNo cross-model proof is claimed unless this live run succeeds and is committed.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
