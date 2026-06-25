from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from howdex import Howdex

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "howdex_dogfood.py"


def _module():
    spec = importlib.util.spec_from_file_location("howdex_dogfood_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _start(cwd: Path, phase: str = "phase-8-live-trust-calibration"):
    return _run(
        cwd,
        [
            "start",
            "--phase",
            phase,
            "--objective",
            "Run live procedure trust calibration from actual dogfood traces",
        ],
    )


def _state(cwd: Path) -> dict:
    return json.loads(
        (cwd / ".howdex" / "dogfood" / "current.json").read_text(
            encoding="utf-8"
        )
    )


def _add_known_steps(cwd: Path) -> None:
    for action, observation in [
        ("read package.json", "inspected current test configuration"),
        ("patch package.json test script", "updated dogfood test target"),
    ]:
        result = _run(
            cwd,
            ["step", "--action", action, "--observation", observation],
        )
        assert result.returncode == 0, result.stderr


def _run_passing_pytest(cwd: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        cwd,
        [
            "run",
            "--label",
            "pytest",
            "--",
            sys.executable,
            "-c",
            "print('486 passed in 0.12s')",
        ],
    )


def _prepare_successful_phase(cwd: Path) -> None:
    assert _start(cwd).returncode == 0
    _add_known_steps(cwd)
    result = _run_passing_pytest(cwd)
    assert result.returncode == 0, result.stderr


def test_start_creates_current_json_with_phase_objective_and_git_metadata(tmp_path):
    result = _start(tmp_path)

    assert result.returncode == 0, result.stderr
    state = _state(tmp_path)
    assert state["phase"] == "phase-8-live-trust-calibration"
    assert state["objective"] == (
        "Run live procedure trust calibration from actual dogfood traces"
    )
    assert "git_start_sha" in state
    assert state["python_version"]
    assert state["howdex_version"]
    assert state["active_database_path"].endswith(".howdex/dogfood/howdex.db")
    assert state["dogfood_state_path"].endswith(".howdex/dogfood/current.json")


def test_guidance_save_records_usage_and_writes_markdown(tmp_path):
    assert _start(tmp_path).returncode == 0

    result = _run(
        tmp_path,
        [
            "guidance",
            "--objective",
            "Run live procedure trust calibration from actual dogfood traces",
            "--save",
        ],
    )

    assert result.returncode == 0, result.stderr
    state = _state(tmp_path)
    guidance_path = Path(state["guidance_path"])
    assert state["guidance_used"] is True
    assert state["guidance_chars"] > 0
    assert isinstance(state["selected_procedure_ids"], list)
    assert guidance_path.is_file()
    assert "# HOWDEX OPERATIONAL MEMORY" in guidance_path.read_text(
        encoding="utf-8"
    )


def test_run_captures_passing_command_and_exit_code_zero(tmp_path):
    assert _start(tmp_path).returncode == 0

    result = _run_passing_pytest(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "exit_code=0" in result.stdout
    state = _state(tmp_path)
    run = state["command_runs"][0]
    assert run["label"] == "pytest"
    assert run["exit_code"] == 0
    assert run["passed"] is True
    assert run["pytest_summary"] == "486 passed"
    assert Path(run["log_path"]).is_file()
    assert state["steps"][-1]["action"] == "run command: pytest"


def test_run_captures_failing_command_and_increments_failed_attempts(tmp_path):
    assert _start(tmp_path).returncode == 0

    result = _run(
        tmp_path,
        [
            "run",
            "--label",
            "pytest",
            "--",
            sys.executable,
            "-c",
            "import sys; print('1 failed in 0.01s'); sys.exit(2)",
        ],
    )

    assert result.returncode == 2
    state = _state(tmp_path)
    assert state["command_runs"][0]["exit_code"] == 2
    assert state["failed_attempts"] == 1


def test_pytest_summary_parser_extracts_486_passed():
    module = _module()

    assert (
        module.parse_pytest_summary(
            "================ 486 passed in 3.21s ================"
        )
        == "486 passed"
    )


def test_end_auto_writes_summary_json_and_metrics_csv(tmp_path):
    _prepare_successful_phase(tmp_path)

    result = _run(tmp_path, ["end", "--auto"])

    assert result.returncode == 0, result.stderr
    summary_path = tmp_path / "dogfood-results" / "phase-8-live-trust-calibration" / "summary.json"
    metrics_path = tmp_path / "dogfood-results" / "metrics.csv"
    assert summary_path.is_file()
    assert metrics_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["phase"] == "phase-8-live-trust-calibration"
    assert summary["commands_run"] == 1
    assert summary["latest_test_summary"] == "486 passed"
    assert "single-episode" in summary["support_scope_statement"]
    codex_entries = sorted(
        (tmp_path / ".howdex" / "dogfood" / "codex" / "procedures").glob(
            "*.json"
        )
    )
    assert codex_entries
    entry = json.loads(codex_entries[0].read_text(encoding="utf-8"))
    assert entry["status"] == "candidate"

    rows = list(csv.DictReader(metrics_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["summary_path"].endswith("summary.json")


def test_end_auto_records_support_count_honestly(tmp_path):
    _prepare_successful_phase(tmp_path)

    assert _run(tmp_path, ["end", "--auto"]).returncode == 0
    summary = json.loads(
        (
            tmp_path
            / "dogfood-results"
            / "phase-8-live-trust-calibration"
            / "summary.json"
        ).read_text(encoding="utf-8")
    )

    assert summary["support_count"] == 1
    assert "not proof of broad generalization" in summary["support_scope_statement"]


def test_end_auto_attaches_receipt_from_passing_test_command(tmp_path):
    _prepare_successful_phase(tmp_path)

    result = _run(tmp_path, ["end", "--auto"])

    assert result.returncode == 0, result.stderr
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
        assert receipts[0].expected_signal == "486 passed"
    finally:
        memory.close()


def test_status_works_with_active_phase(tmp_path):
    assert _start(tmp_path).returncode == 0
    assert _run_passing_pytest(tmp_path).returncode == 0

    result = _run(tmp_path, ["status"])

    assert result.returncode == 0, result.stderr
    assert "active_phase=phase-8-live-trust-calibration" in result.stdout
    assert "commands_run=1" in result.stdout
    assert "failed_attempts=0" in result.stdout
    assert "guidance_used=no" in result.stdout


def test_abort_clears_active_state_and_preserves_logs_by_default(tmp_path):
    assert _start(tmp_path).returncode == 0
    assert _run_passing_pytest(tmp_path).returncode == 0
    log_path = Path(_state(tmp_path)["command_runs"][0]["log_path"])

    result = _run(tmp_path, ["abort", "--reason", "starting again"])

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".howdex" / "dogfood" / "current.json").exists()
    assert log_path.is_file()


def test_redaction_removes_obvious_secret_patterns():
    module = _module()
    secret = (
        "OPENAI_API_KEY=sk-testsecret123 "
        "Authorization=Bearer abcdef123456789 "
        "password=hunter2"
    )

    redacted = module.redact_secrets(secret)

    assert "sk-testsecret123" not in redacted
    assert "abcdef123456789" not in redacted
    assert "hunter2" not in redacted
    assert "<SECRET_REDACTED>" in redacted


def test_dogfooding_docs_warn_metrics_are_not_external_adoption():
    docs = " ".join(
        (REPO_ROOT / "docs" / "DOGFOODING.md")
        .read_text(encoding="utf-8")
        .split()
    )

    assert "not external adoption" in docs
    assert "not proof of broad generalization" in docs
