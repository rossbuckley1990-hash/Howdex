from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_works_without_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = importlib.import_module("benchmarks.awm_head_to_head.runner")

    rows = runner.run_dry(task_name="docker", trials=3)

    assert [row.condition for row in rows] == ["vanilla", "awm_style", "howdex"]
    assert all(row.trials == 3 for row in rows)


def test_all_conditions_produce_comparable_result_schema():
    runner = importlib.import_module("benchmarks.awm_head_to_head.runner")
    metrics = importlib.import_module("benchmarks.awm_head_to_head.metrics")

    rows = runner.run_dry(task_name="docker", trials=3)
    payload = metrics.ensure_comparable_schema(rows)

    assert len(payload) == 3
    assert set(payload[0]) == set(payload[1]) == set(payload[2])
    required = {
        "condition",
        "success_rate",
        "avg_attempts",
        "extraction_cost",
        "guidance_chars",
        "source_leakage",
        "auditability_score",
        "verification_coverage",
        "calibration_coverage",
        "portability_score",
    }
    assert required <= set(payload[0])


def test_identical_base_framing_enforced():
    runner = importlib.import_module("benchmarks.awm_head_to_head.runner")

    rows = runner.run_dry(task_name="docker", trials=3)
    hashes = {row.base_prompt_sha256 for row in rows}

    assert len(hashes) == 1
    runner.enforce_identical_base_framing(rows)


def test_source_leakage_metric_works():
    metrics = importlib.import_module("benchmarks.awm_head_to_head.metrics")

    assert metrics.source_leakage_score("Use docker compose logs.") == 0
    assert metrics.source_leakage_score("```python\nclass Handler: pass\n```") == 1
    assert metrics.source_leakage_score("FROM python:3.12-alpine") == 1


def test_auditability_score_distinguishes_howdex_receipts_from_freeform_summary():
    runner = importlib.import_module("benchmarks.awm_head_to_head.runner")

    by_condition = {row.condition: row for row in runner.run_dry(task_name="docker", trials=3)}

    assert by_condition["howdex"].auditability_score > by_condition["awm_style"].auditability_score
    assert by_condition["howdex"].verification_coverage > by_condition["awm_style"].verification_coverage
    assert by_condition["awm_style"].auditability_score > by_condition["vanilla"].auditability_score


def test_metrics_calculation_works():
    metrics = importlib.import_module("benchmarks.awm_head_to_head.metrics")

    assert metrics.success_rate(2, 4) == 0.5
    assert metrics.average_attempts([2, 4, 6]) == 4.0
    assert metrics.verification_coverage(1, 4) == 0.25
    assert metrics.portability_score(
        json_exportable=True,
        receipt_backed=True,
        framework_neutral=True,
    ) == 1.0


def test_runner_prints_machine_readable_summary():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.awm_head_to_head.runner",
            "--dry-run",
            "--trials",
            "3",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "condition | trials | successes" in result.stdout
    json_start = result.stdout.index("{")
    payload = json.loads(result.stdout[json_start:])
    assert payload["benchmark"] == "awm_head_to_head"
    assert payload["mode"] == "dry-run"
    assert [row["condition"] for row in payload["conditions"]] == [
        "vanilla",
        "awm_style",
        "howdex",
    ]
    assert "not evidence that Howdex beats AWM" in payload["claim"]


def test_readme_explains_harness_not_victory_claim():
    readme = (
        ROOT / "benchmarks" / "awm_head_to_head" / "README.md"
    ).read_text(encoding="utf-8")

    assert "This is a harness, not a victory claim" in readme
    assert "Do not claim that Howdex beats AWM" in readme
    assert "local AWM-style workflow-memory approximation" in readme


def test_result_doc_records_required_caveat_and_repro_command():
    result_doc = (
        ROOT / "evidence" / "awm_head_to_head" / "AWM_HEAD_TO_HEAD_RESULTS.md"
    ).read_text(encoding="utf-8")

    assert (
        'PATH="$PWD/.venv/bin:$PATH" python -m benchmarks.awm_head_to_head.runner '
        "--dry-run --trials 5"
    ) in result_doc
    assert (
        "This is a local AWM-style approximation unless explicitly stated otherwise. "
        "It is not a claim that Howdex has beaten the AWM paper or public "
        "WebArena/Mind2Web baselines."
    ) in result_doc
    assert "not a real AWM implementation" in result_doc
