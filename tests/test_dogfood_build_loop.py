from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from howdex import Howdex


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "howdex_dogfood.py"


def _run(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOWDEX_EMBEDDER"] = "hash"
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.pop("OPENAI_API_KEY", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _start(cwd: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        cwd,
        [
            "start",
            "--phase",
            "procedure-trust-calibration",
            "--objective",
            "Add procedure trust calibration benchmark",
        ],
    )


def _log_procedural_steps(cwd: Path) -> None:
    steps = [
        (
            "read package.json",
            "inspected existing test command before adding the benchmark",
        ),
        (
            "patch package.json test script",
            "updated the test surface for the dogfood phase",
        ),
        (
            "run pytest",
            "480 passed",
        ),
    ]
    for action, observation in steps:
        result = _run(
            cwd,
            [
                "step",
                "--action",
                action,
                "--observation",
                observation,
            ],
        )
        assert result.returncode == 0, result.stderr


def _codex_entries(cwd: Path) -> list[dict]:
    entries = []
    for path in sorted(
        (cwd / ".howdex" / "dogfood" / "codex" / "procedures").glob("*.json")
    ):
        entries.append(json.loads(path.read_text(encoding="utf-8")))
    return entries


def test_start_creates_current_dogfood_state(tmp_path):
    result = _start(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "active_session_id=" in result.stdout
    state_path = tmp_path / ".howdex" / "dogfood" / "current.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "procedure-trust-calibration"
    assert state["objective"] == "Add procedure trust calibration benchmark"
    assert state["session_id"]
    assert state["steps"] == []


def test_step_logs_into_active_session_state(tmp_path):
    assert _start(tmp_path).returncode == 0

    result = _run(
        tmp_path,
        [
            "step",
            "--action",
            "created procedure_trust_calibration_test.py",
            "--observation",
            "added dry-run calibration bins and output schema",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "stored_steps=1" in result.stdout
    state = json.loads(
        (tmp_path / ".howdex" / "dogfood" / "current.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["steps"][0]["action"] == "created procedure_trust_calibration_test.py"
    assert "dry-run calibration" in state["steps"][0]["observation"]


def test_end_learns_at_least_one_candidate_procedure(tmp_path):
    assert _start(tmp_path).returncode == 0
    _log_procedural_steps(tmp_path)

    result = _run(tmp_path, ["end", "--outcome", "success"])

    assert result.returncode == 0, result.stderr
    assert "learned_procedure_ids=" in result.stdout
    assert not (tmp_path / ".howdex" / "dogfood" / "current.json").exists()
    entries = _codex_entries(tmp_path)
    assert entries
    assert any(entry["status"] == "candidate" for entry in entries)


def test_end_with_verifier_attaches_receipt(tmp_path):
    assert _start(tmp_path).returncode == 0
    _log_procedural_steps(tmp_path)

    result = _run(
        tmp_path,
        [
            "end",
            "--outcome",
            "success",
            "--verifier",
            "python -m pytest",
            "--observed",
            "480 passed",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "receipt_ids=" in result.stdout
    memory = Howdex(
        path=tmp_path / ".howdex" / "dogfood" / "howdex.db",
        embedder="hashing",
    )
    try:
        procedures = memory.list_procedures()
        assert procedures
        receipts = memory.list_receipts(procedures[0].id)
        assert receipts
        assert receipts[0].status == "verified"
        assert receipts[0].verifier_command == "python -m pytest"
    finally:
        memory.close()


def test_guidance_returns_markdown_without_source_artifacts(tmp_path):
    assert _start(tmp_path).returncode == 0
    _log_procedural_steps(tmp_path)
    assert _run(tmp_path, ["end", "--outcome", "success"]).returncode == 0

    result = _run(
        tmp_path,
        [
            "guidance",
            "--objective",
            "Add AWM head-to-head benchmark harness",
            "--max-chars",
            "2000",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "# HOWDEX OPERATIONAL MEMORY" in result.stdout
    assert "Source artifacts excluded:" in result.stdout
    assert "```python" not in result.stdout
    assert "def " not in result.stdout
    assert "import " not in result.stdout


def test_dogfood_harness_requires_no_openai_or_network(tmp_path):
    result = _run(
        tmp_path,
        [
            "guidance",
            "--objective",
            "Add local-only dogfood benchmark",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "# HOWDEX OPERATIONAL MEMORY" in result.stdout
    assert "No prior procedure memory was provided" in result.stdout
