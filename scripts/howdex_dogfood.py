#!/usr/bin/env python3
"""Dogfood Howdex by recording Howdex development work as procedural memory.

The CLI is local-only. It stages an active build phase in
``.howdex/dogfood/current.json``, captures command logs under
``.howdex/dogfood/runs/``, writes local sanitized runtime evidence to
``dogfood-results/``, and replays the trace into Howdex on phase end.
Committed sanitized evidence belongs under ``evidence/dogfood/results/``.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from howdex import Howdex, __version__  # noqa: E402
from howdex.core.guidance import render_agent_guidance  # noqa: E402


DEFAULT_ROOT = Path(".howdex") / "dogfood"
DEFAULT_DB_NAME = "howdex.db"
STATE_FILE_NAME = "current.json"
CODEX_DIR_NAME = "codex"
GUIDANCE_DIR_NAME = "guidance"
RUNS_DIR_NAME = "runs"
RESULTS_ROOT = Path("dogfood-results")
DOGFOOD_SOURCE = "howdex-dogfood"
SUPPORT_SCOPE_STATEMENT = (
    "Dogfood procedures learned from this phase are single-episode, "
    "single-repo, single-user internal evidence. They are not external "
    "adoption, traction, users, market validation, and not proof of broad "
    "generalization."
)
METRIC_FIELDS = [
    "phase",
    "objective",
    "branch",
    "git_start_sha",
    "git_end_sha",
    "guidance_used",
    "guidance_chars",
    "selected_procedure_ids",
    "commands_run",
    "failed_attempts",
    "latest_test_label",
    "latest_test_passed",
    "latest_test_summary",
    "duration_seconds",
    "changed_files_count",
    "commit_count",
    "procedure_published",
    "support_count",
    "receipt_attached",
    "codex_entry_path",
    "summary_path",
]

_SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(authorization)\s*=\s*bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    ),
    re.compile(
        r"(?i)\b(OPENAI_API_KEY|[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|AUTHORIZATION|BEARER)[A-Z0-9_]*)\s*=\s*([^\s\"']+)"
    ),
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
]


def _now() -> float:
    return time.time()


def _iso(ts: float | None = None) -> str:
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(_now() if ts is None else ts),
    )


def _timestamp_slug(ts: float | None = None) -> str:
    value = _now() if ts is None else ts
    base = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(value))
    millis = int((value - int(value)) * 1000)
    return f"{base}-{millis:03d}"


def _slug(value: str, *, fallback: str = "item") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    slug = slug.strip(".-").lower()
    return slug or fallback


def redact_secrets(value: Any) -> Any:
    """Redact obvious secrets from strings, lists, and dictionaries."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _secret_key(str(key)):
                redacted[key] = "<SECRET_REDACTED>"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if not isinstance(value, str):
        return value

    redacted = value
    redacted = _SECRET_PATTERNS[0].sub(r"\1=<SECRET_REDACTED>", redacted)
    redacted = _SECRET_PATTERNS[1].sub(r"\1=<SECRET_REDACTED>", redacted)
    redacted = _SECRET_PATTERNS[2].sub(r"\1 <SECRET_REDACTED>", redacted)
    redacted = _SECRET_PATTERNS[3].sub("<SECRET_REDACTED>", redacted)
    redacted = _SECRET_PATTERNS[4].sub("<SECRET_REDACTED>", redacted)
    return redacted


def _secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in (
            "api_key",
            "apikey",
            "token",
            "secret",
            "password",
            "private_key",
            "access_key",
            "authorization",
            "bearer",
        )
    )


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            redact_secrets(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_git(args: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _git_changed_files() -> list[str]:
    status = _run_git(["status", "--short"])
    if status == "unknown":
        return []
    files: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        files.append(path)
    return sorted(set(files))


def _git_commit_count_since(start_sha: str | None) -> int:
    if not start_sha or start_sha == "unknown":
        return 0
    count = _run_git(["rev-list", "--count", f"{start_sha}..HEAD"])
    try:
        return max(0, int(count))
    except (TypeError, ValueError):
        return 0


def resolve_root(value: str | None = None) -> Path:
    return (Path(value).expanduser() if value else DEFAULT_ROOT).resolve()


def state_path(root: Path) -> Path:
    return root / STATE_FILE_NAME


def db_path(root: Path, override: str | None = None) -> Path:
    return (
        Path(override).expanduser().resolve()
        if override
        else root / DEFAULT_DB_NAME
    )


def codex_path(root: Path) -> Path:
    return root / CODEX_DIR_NAME


def guidance_dir(root: Path) -> Path:
    return root / GUIDANCE_DIR_NAME


def runs_dir(root: Path, phase: str) -> Path:
    return root / RUNS_DIR_NAME / _slug(phase, fallback="phase")


def summary_path(phase: str) -> Path:
    return RESULTS_ROOT / _slug(phase, fallback="phase") / "summary.json"


def metrics_path() -> Path:
    return RESULTS_ROOT / "metrics.csv"


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise SystemExit(
            f"no active dogfood phase at {path}; run `howdex_dogfood.py start` first"
        )
    return _read_json(path)


def save_state(root: Path, payload: dict[str, Any]) -> None:
    _write_json(state_path(root), payload)


def start_phase(
    *,
    phase: str,
    objective: str,
    root: Path,
    db: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = state_path(root)
    if path.exists():
        raise SystemExit(
            f"dogfood phase already active at {path}; end it before starting another"
        )

    root.mkdir(parents=True, exist_ok=True)
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    git_start_sha = _run_git(["rev-parse", "HEAD"])
    dirty_state = _run_git(["status", "--porcelain"])
    if dirty_state == "unknown":
        clean_state = "unknown"
    elif dirty_state:
        clean_state = "dirty"
    else:
        clean_state = "clean"
    started_at = _now()
    payload = {
        "active_database_path": str(db),
        "branch": branch,
        "command_runs": [],
        "created_at": _iso(started_at),
        "db_path": str(db),
        "dirty_state": clean_state,
        "dogfood_state_path": str(path),
        "failed_attempts": 0,
        "git_start_sha": git_start_sha,
        "guidance_chars": 0,
        "guidance_path": None,
        "guidance_used": False,
        "howdex_version": __version__,
        "metadata": dict(metadata or {}),
        "objective": objective,
        "phase": phase,
        "python_version": sys.version.split()[0],
        "selected_procedure_ids": [],
        "session_id": str(uuid.uuid4()),
        "source": DOGFOOD_SOURCE,
        "started_at": started_at,
        "steps": [],
        "version": 2,
    }
    save_state(root, payload)
    return payload


def log_step(
    *,
    root: Path,
    action: str,
    observation: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = load_state(root)
    step = {
        "action": redact_secrets(action),
        "metadata": redact_secrets(dict(metadata or {})),
        "observation": redact_secrets(observation),
        "recorded_at": _iso(),
        "ts": _now(),
    }
    payload.setdefault("steps", []).append(step)
    save_state(root, payload)
    return payload


def parse_pytest_summary(text: str) -> str | None:
    """Extract a compact pytest summary such as ``486 passed``."""
    cleaned = " ".join(str(text or "").split())
    patterns = [
        r"=+\s*([^=]*?\b\d+\s+(?:passed|failed|skipped|xfailed|xpassed|errors?|warnings?)(?:,\s*\d+\s+(?:passed|failed|skipped|xfailed|xpassed|errors?|warnings?))*[^=]*?)\s+in\s+[\d.]+s\s*=+",
        r"\b(\d+\s+passed(?:,\s*\d+\s+\w+)*)\b",
        r"\b(\d+\s+failed(?:,\s*\d+\s+\w+)*)\b",
        r"\b(\d+\s+errors?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            summary = match.group(1).strip(" =")
            return redact_secrets(summary)
    return None


def _command_string(command: list[str]) -> str:
    return " ".join(command)


def _split_env_assignments(command: list[str]) -> tuple[dict[str, str], list[str]]:
    env: dict[str, str] = {}
    remaining = list(command)
    while remaining and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", remaining[0]):
        key, value = remaining.pop(0).split("=", 1)
        env[key] = value
    return env, remaining


def run_command(
    *,
    root: Path,
    label: str,
    command: list[str],
) -> dict[str, Any]:
    if not command:
        raise SystemExit("run requires a command after --")
    payload = load_state(root)
    phase = str(payload["phase"])
    command_env, executable = _split_env_assignments(command)
    if not executable:
        raise SystemExit("run command only contained environment assignments")

    env = os.environ.copy()
    env.update(command_env)
    started_at = _now()
    started_iso = _iso(started_at)
    result = subprocess.run(
        executable,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    ended_at = _now()
    duration = round(ended_at - started_at, 3)
    combined_output = "\n".join(
        part
        for part in (
            result.stdout,
            result.stderr,
        )
        if part
    )
    safe_output = redact_secrets(combined_output)
    safe_command = redact_secrets(_command_string(command))
    log_path = (
        runs_dir(root, phase)
        / f"{_timestamp_slug(started_at)}-{_slug(label, fallback='command')}.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                f"label={label}",
                f"command={safe_command}",
                f"started_at={started_iso}",
                f"exit_code={result.returncode}",
                f"duration_seconds={duration}",
                "",
                safe_output,
            ]
        ),
        encoding="utf-8",
    )

    pytest_summary = parse_pytest_summary(safe_output)
    run_record = {
        "command": safe_command,
        "duration_seconds": duration,
        "ended_at": _iso(ended_at),
        "exit_code": int(result.returncode),
        "label": label,
        "log_path": str(log_path),
        "passed": result.returncode == 0,
        "pytest_summary": pytest_summary,
        "started_at": started_iso,
    }
    payload.setdefault("command_runs", []).append(run_record)
    if result.returncode != 0:
        payload["failed_attempts"] = int(payload.get("failed_attempts") or 0) + 1
    observation_parts = [
        f"exit_code={result.returncode}",
        f"duration_seconds={duration}",
    ]
    if pytest_summary:
        observation_parts.append(f"pytest_summary={pytest_summary}")
    log_step(
        root=root,
        action=f"run command: {label}",
        observation="; ".join(observation_parts),
        metadata={
            "command": safe_command,
            "exit_code": result.returncode,
            "log_path": str(log_path),
            "pytest_summary": pytest_summary,
        },
    )
    payload = load_state(root)
    payload.setdefault("command_runs", []).append(run_record)
    if result.returncode != 0:
        payload["failed_attempts"] = int(payload.get("failed_attempts") or 0) + 1
        # log_step reload/save above means undo the duplicate increment in the
        # pre-log payload path and keep one authoritative failure count.
        payload["failed_attempts"] = len(
            [
                run
                for run in payload.get("command_runs", [])
                if int(run.get("exit_code", 0)) != 0
            ]
        )
    save_state(root, payload)
    return run_record


def _render_guidance_with_suggestions(
    *,
    memory: Howdex,
    objective: str,
    max_chars: int,
) -> tuple[str, list[str]]:
    suggestions = memory.suggest_procedure(
        objective,
        top_k=3,
        min_confidence=0.0,
    )
    guidance = render_agent_guidance(
        suggestions,
        objective=objective,
        target_environment="Howdex repository dogfood build loop",
        constraints=[
            "Use prior dogfood procedures as guidance only.",
            "Do not include source artifacts unless explicitly requested.",
            "Verify the phase with local commands before treating it as complete.",
        ],
        include_source=False,
        include_verification=True,
        max_chars=max_chars,
    )
    return guidance, [suggestion.procedure_id for suggestion in suggestions]


def render_guidance(
    *,
    objective: str,
    root: Path,
    db: Path,
    max_chars: int = 6000,
    save: bool = False,
) -> str:
    memory = Howdex(path=db, embedder="hashing")
    try:
        guidance, selected_ids = _render_guidance_with_suggestions(
            memory=memory,
            objective=objective,
            max_chars=max_chars,
        )
    finally:
        memory.close()

    if save:
        payload = load_state(root)
        phase = str(payload["phase"])
        path = guidance_dir(root) / f"{_slug(phase, fallback='phase')}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(guidance, encoding="utf-8")
        payload["guidance_chars"] = len(guidance)
        payload["guidance_path"] = str(path)
        payload["guidance_used"] = True
        payload["selected_procedure_ids"] = selected_ids
        save_state(root, payload)
    return guidance


def _replay_state(memory: Howdex, payload: dict[str, Any]) -> str:
    episode = memory.start_session(
        str(payload["objective"]),
        source=payload.get("source") or DOGFOOD_SOURCE,
        provenance={
            "dogfood": True,
            "dogfood_metrics": True,
            "phase": payload.get("phase"),
            "phase_metadata": payload.get("metadata", {}),
            "state_session_id": payload.get("session_id"),
        },
    )
    episode.session_id = str(payload["session_id"])
    episode.started_at = float(payload.get("started_at") or _now())
    for step in payload.get("steps", []):
        memory.log_step(
            str(step.get("action", "")),
            str(step.get("observation", "")),
            metadata={
                "dogfood_phase": payload.get("phase"),
                **dict(step.get("metadata") or {}),
            },
            ts=float(step.get("ts") or _now()),
        )
    return episode.session_id


def _latest_test_run(payload: dict[str, Any]) -> dict[str, Any] | None:
    for run in reversed(payload.get("command_runs", [])):
        haystack = f"{run.get('label', '')} {run.get('command', '')}".lower()
        if "pytest" in haystack or "test" in haystack:
            return run
    return None


def _publish_before_receipts(
    memory: Howdex,
    root: Path,
) -> tuple[dict[str, Any], list[str]]:
    published = memory.publish_codex(codex_path(root))
    files = [str(path) for path in published.get("files", [])]
    return published, files


def _attach_receipts_from_test(
    memory: Howdex,
    procedures: list[Any],
    *,
    episode_id: str,
    phase: str,
    latest_test: dict[str, Any] | None,
) -> list[str]:
    if not latest_test or int(latest_test.get("exit_code", 1)) != 0:
        return []
    expected = latest_test.get("pytest_summary") or "passed"
    observed = latest_test.get("pytest_summary") or "exit_code=0"
    receipt_ids: list[str] = []
    for procedure in procedures:
        receipt = memory.verify_procedure(
            procedure.id,
            verifier_type="dogfood",
            verifier_command=str(latest_test.get("command") or ""),
            expected_signal=str(expected),
            observed_signal=str(observed),
            exit_code=0,
            source_episode_id=episode_id,
            environment_fingerprint={
                "source": DOGFOOD_SOURCE,
                "phase": phase,
            },
            metadata={
                "dogfood": True,
                "phase": phase,
                "log_path": latest_test.get("log_path"),
            },
        )
        receipt_ids.append(str(receipt.receipt_id))
    return receipt_ids


def _summary_and_metrics(
    *,
    payload: dict[str, Any],
    learned: list[Any],
    published_files: list[str],
    receipt_ids: list[str],
    episode_id: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    phase = str(payload["phase"])
    git_end_sha = _run_git(["rev-parse", "HEAD"])
    changed_files = _git_changed_files()
    latest_test = _latest_test_run(payload)
    duration_seconds = round(_now() - float(payload.get("started_at") or _now()), 3)
    support_count = 1 if learned else 0
    summary_file = summary_path(phase)
    command_runs = [
        {
            "command": redact_secrets(run.get("command", "")),
            "duration_seconds": run.get("duration_seconds"),
            "exit_code": run.get("exit_code"),
            "label": run.get("label"),
            "log_path": run.get("log_path"),
            "passed": run.get("passed"),
            "pytest_summary": redact_secrets(run.get("pytest_summary")),
        }
        for run in payload.get("command_runs", [])
    ]
    summary = {
        "branch": payload.get("branch"),
        "changed_files": changed_files,
        "changed_files_count": len(changed_files),
        "codex_entry_paths": published_files,
        "command_runs": command_runs,
        "commands_run": len(command_runs),
        "commit_count": _git_commit_count_since(payload.get("git_start_sha")),
        "dirty_state_at_start": payload.get("dirty_state"),
        "duration_seconds": duration_seconds,
        "episode_id": episode_id,
        "failed_attempts": int(payload.get("failed_attempts") or 0),
        "git_diff_stat": _run_git(["diff", "--stat"]),
        "git_end_sha": git_end_sha,
        "git_start_sha": payload.get("git_start_sha"),
        "guidance_chars": int(payload.get("guidance_chars") or 0),
        "guidance_path": payload.get("guidance_path"),
        "guidance_used": bool(payload.get("guidance_used")),
        "howdex_version": payload.get("howdex_version"),
        "latest_test_label": latest_test.get("label") if latest_test else "",
        "latest_test_passed": bool(latest_test and latest_test.get("passed")),
        "latest_test_summary": redact_secrets(
            latest_test.get("pytest_summary") if latest_test else ""
        ),
        "learned_procedure_ids": [procedure.id for procedure in learned],
        "objective": payload.get("objective"),
        "phase": phase,
        "procedure_published": bool(published_files),
        "python_version": payload.get("python_version"),
        "receipt_attached": bool(receipt_ids),
        "receipt_ids": receipt_ids,
        "selected_procedure_ids": payload.get("selected_procedure_ids", []),
        "support_count": support_count,
        "support_scope_statement": SUPPORT_SCOPE_STATEMENT,
    }
    metrics = {
        "phase": phase,
        "objective": str(payload.get("objective", "")),
        "branch": str(payload.get("branch", "")),
        "git_start_sha": str(payload.get("git_start_sha", "")),
        "git_end_sha": git_end_sha,
        "guidance_used": str(bool(payload.get("guidance_used"))),
        "guidance_chars": str(int(payload.get("guidance_chars") or 0)),
        "selected_procedure_ids": ";".join(payload.get("selected_procedure_ids", [])),
        "commands_run": str(len(command_runs)),
        "failed_attempts": str(int(payload.get("failed_attempts") or 0)),
        "latest_test_label": str(latest_test.get("label") if latest_test else ""),
        "latest_test_passed": str(bool(latest_test and latest_test.get("passed"))),
        "latest_test_summary": str(
            redact_secrets(latest_test.get("pytest_summary") if latest_test else "")
        ),
        "duration_seconds": str(duration_seconds),
        "changed_files_count": str(len(changed_files)),
        "commit_count": str(_git_commit_count_since(payload.get("git_start_sha"))),
        "procedure_published": str(bool(published_files)),
        "support_count": str(support_count),
        "receipt_attached": str(bool(receipt_ids)),
        "codex_entry_path": ";".join(published_files),
        "summary_path": str(summary_file),
    }
    return summary, metrics


def _append_metrics(row: dict[str, str]) -> None:
    path = metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=METRIC_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in METRIC_FIELDS})


def end_phase(
    *,
    root: Path,
    outcome: str = "success",
    verifier: str | None = None,
    observed: str | None = None,
    expected: str | None = None,
    exit_code: int | None = None,
    error: str | None = None,
    auto: bool = False,
) -> dict[str, Any]:
    payload = load_state(root)
    db = Path(payload.get("db_path") or db_path(root))
    memory = Howdex(path=db, embedder="hashing")
    try:
        episode_id = _replay_state(memory, payload)
        memory.end_session(outcome=outcome, error=error)
        learned = memory.learn(min_samples=1)

        published, published_files = _publish_before_receipts(memory, root)
        receipts: list[str] = []
        latest_test = _latest_test_run(payload)

        if auto:
            receipts = _attach_receipts_from_test(
                memory,
                learned,
                episode_id=episode_id,
                phase=str(payload.get("phase")),
                latest_test=latest_test,
            )
            summary, metrics = _summary_and_metrics(
                payload=payload,
                learned=learned,
                published_files=published_files,
                receipt_ids=receipts,
                episode_id=episode_id,
            )
            _write_json(summary_path(str(payload["phase"])), summary)
            _append_metrics(metrics)
        elif verifier and observed is not None:
            resolved_expected = expected or observed
            resolved_exit_code = (
                int(exit_code)
                if exit_code is not None
                else (0 if outcome == "success" else 1)
            )
            for procedure in learned:
                receipt = memory.verify_procedure(
                    procedure.id,
                    verifier_type="dogfood",
                    verifier_command=verifier,
                    expected_signal=resolved_expected,
                    observed_signal=observed,
                    exit_code=resolved_exit_code,
                    source_episode_id=episode_id,
                    environment_fingerprint={
                        "source": DOGFOOD_SOURCE,
                        "phase": payload.get("phase"),
                    },
                    metadata={
                        "dogfood": True,
                        "phase": payload.get("phase"),
                    },
                )
                receipts.append(str(receipt.receipt_id))

        state_path(root).unlink(missing_ok=True)
        return {
            "codex_path": str(codex_path(root)),
            "episode_id": episode_id,
            "learned_procedure_ids": [procedure.id for procedure in learned],
            "phase": payload.get("phase"),
            "published": published.get("exported", 0),
            "published_files": published_files,
            "receipt_ids": receipts,
            "summary_path": str(summary_path(str(payload["phase"]))) if auto else "",
        }
    finally:
        memory.close()


def status(root: Path) -> str:
    payload = load_state(root)
    latest_test = _latest_test_run(payload)
    lines = [
        f"active_phase={payload.get('phase')}",
        f"objective={payload.get('objective')}",
        f"branch={payload.get('branch')}",
        f"commands_run={len(payload.get('command_runs', []))}",
        f"failed_attempts={payload.get('failed_attempts', 0)}",
        "latest_test_status="
        + (
            f"{latest_test.get('label')} passed={latest_test.get('passed')} "
            f"summary={latest_test.get('pytest_summary') or ''}"
            if latest_test
            else "none"
        ),
        f"guidance_used={'yes' if payload.get('guidance_used') else 'no'}",
    ]
    return "\n".join(lines)


def abort_phase(root: Path, *, reason: str, delete_logs: bool = False) -> dict[str, Any]:
    payload = load_state(root)
    phase = str(payload.get("phase") or "")
    state_path(root).unlink(missing_ok=True)
    logs_deleted = False
    if delete_logs:
        shutil.rmtree(runs_dir(root, phase), ignore_errors=True)
        logs_deleted = True
    return {
        "phase": phase,
        "reason": reason,
        "logs_deleted": logs_deleted,
    }


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--metadata must be JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--metadata must be a JSON object")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dogfood Howdex by recording Howdex roadmap build phases."
    )
    parser.add_argument("--root", default=None, help="dogfood root; default .howdex/dogfood")
    parser.add_argument("--db", default=None, help="Howdex DB path; default <root>/howdex.db")

    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start a dogfood phase")
    start.add_argument("--phase", required=True)
    start.add_argument("--objective", required=True)
    start.add_argument("--metadata", default=None, help="optional JSON object")

    step = sub.add_parser("step", help="append a step to the active phase")
    step.add_argument("--action", required=True)
    step.add_argument("--observation", required=True)
    step.add_argument("--metadata", default=None, help="optional JSON object")

    run = sub.add_parser("run", help="run a local command under dogfood tracing")
    run.add_argument("--label", required=True)
    run.add_argument("command_argv", nargs=argparse.REMAINDER)

    end = sub.add_parser("end", help="end the active phase, learn, and publish Codex")
    end.add_argument("--outcome", default="success")
    end.add_argument("--error", default=None)
    end.add_argument("--verifier", default=None)
    end.add_argument("--observed", default=None)
    end.add_argument("--expected", default=None)
    end.add_argument("--exit-code", type=int, default=None)
    end.add_argument("--auto", action="store_true")

    guidance = sub.add_parser("guidance", help="render guidance for the next phase")
    guidance.add_argument("--objective", required=True)
    guidance.add_argument("--max-chars", type=int, default=6000)
    guidance.add_argument("--save", action="store_true")

    sub.add_parser("status", help="print the active dogfood phase status")

    abort = sub.add_parser("abort", help="clear active dogfood state safely")
    abort.add_argument("--reason", required=True)
    abort.add_argument("--delete-logs", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = resolve_root(args.root)
    db = db_path(root, args.db)

    if args.command == "start":
        payload = start_phase(
            phase=args.phase,
            objective=args.objective,
            root=root,
            db=db,
            metadata=_parse_metadata(args.metadata),
        )
        print(f"active_session_id={payload['session_id']}")
        print(f"state={state_path(root)}")
        print(f"db={payload['active_database_path']}")
        return 0

    if args.command == "step":
        payload = log_step(
            root=root,
            action=args.action,
            observation=args.observation,
            metadata=_parse_metadata(args.metadata),
        )
        print(f"active_session_id={payload['session_id']}")
        print(f"stored_steps={len(payload.get('steps', []))}")
        return 0

    if args.command == "run":
        command = list(args.command_argv)
        if command and command[0] == "--":
            command = command[1:]
        run_record = run_command(root=root, label=args.label, command=command)
        print(f"label={run_record['label']}")
        print(f"exit_code={run_record['exit_code']}")
        print(f"passed={run_record['passed']}")
        if run_record.get("pytest_summary"):
            print(f"pytest_summary={run_record['pytest_summary']}")
        print(f"log_path={run_record['log_path']}")
        return int(run_record["exit_code"])

    if args.command == "end":
        result = end_phase(
            root=root,
            outcome=args.outcome,
            verifier=args.verifier,
            observed=args.observed,
            expected=args.expected,
            exit_code=args.exit_code,
            error=args.error,
            auto=args.auto,
        )
        print(f"episode_id={result['episode_id']}")
        print(
            "learned_procedure_ids="
            + ",".join(result["learned_procedure_ids"])
        )
        print(f"candidate_codex={result['codex_path']}")
        if result["summary_path"]:
            print(f"summary_path={result['summary_path']}")
        if result["receipt_ids"]:
            print("receipt_ids=" + ",".join(result["receipt_ids"]))
        return 0

    if args.command == "guidance":
        print(
            render_guidance(
                objective=args.objective,
                root=root,
                db=db,
                max_chars=args.max_chars,
                save=args.save,
            )
        )
        return 0

    if args.command == "status":
        print(status(root))
        return 0

    if args.command == "abort":
        result = abort_phase(
            root,
            reason=args.reason,
            delete_logs=args.delete_logs,
        )
        print(f"aborted_phase={result['phase']}")
        print(f"reason={result['reason']}")
        print(f"logs_deleted={result['logs_deleted']}")
        return 0

    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
