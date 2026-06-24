from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "procedure_trust_calibration_test.py"


@pytest.fixture
def calibration_module():
    sys.modules.pop("procedure_trust_calibration_test", None)
    return importlib.import_module("procedure_trust_calibration_test")


def _sample(
    module,
    sample_id: str,
    confidence: float,
    success: bool,
    status: str,
    support_count: int = 1,
):
    return module.CalibrationSample(
        sample_id,
        confidence,
        success,
        status,
        support_count,
        "unit",
    )


def _run(
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    merged["PYTHONPATH"] = str(REPO_ROOT)
    merged.pop("OPENAI_API_KEY", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        env=merged,
        capture_output=True,
        text=True,
    )


def test_binning_works(calibration_module):
    assert calibration_module.bin_label(0.0) == "0.0-0.2"
    assert calibration_module.bin_label(0.19) == "0.0-0.2"
    assert calibration_module.bin_label(0.2) == "0.2-0.4"
    assert calibration_module.bin_label(0.99) == "0.8-1.0"
    assert calibration_module.bin_label(1.0) == "0.8-1.0"


def test_calibration_error_calculation(calibration_module):
    samples = [
        _sample(calibration_module, "high", 0.9, True, "verified"),
        _sample(calibration_module, "low", 0.1, False, "failed_verification"),
    ]

    assert calibration_module.expected_calibration_error(samples) == 0.1


def test_verified_procedures_are_reported_separately(calibration_module):
    summary = calibration_module.evaluate_samples(
        [
            _sample(calibration_module, "verified-ok", 0.9, True, "verified"),
            _sample(calibration_module, "verified-fail", 0.8, False, "verified"),
        ],
        source="unit",
        min_samples=1,
    )

    assert summary["verified_success_rate"] == 0.5


def test_candidate_procedures_are_reported_separately(calibration_module):
    summary = calibration_module.evaluate_samples(
        [
            _sample(calibration_module, "candidate-ok", 0.6, True, "candidate"),
            _sample(calibration_module, "candidate-fail", 0.6, False, "candidate"),
        ],
        source="unit",
        min_samples=1,
    )

    assert summary["candidate_success_rate"] == 0.5


def test_stale_procedures_are_reported_separately(calibration_module):
    summary = calibration_module.evaluate_samples(
        [_sample(calibration_module, "stale-fail", 0.3, False, "stale")],
        source="unit",
        min_samples=1,
    )

    assert summary["stale_success_rate"] == 0.0


def test_failed_verification_procedures_are_reported_separately(
    calibration_module,
):
    summary = calibration_module.evaluate_samples(
        [
            _sample(
                calibration_module,
                "failed-verifier",
                0.1,
                False,
                "failed_verification",
            )
        ],
        source="unit",
        min_samples=1,
    )

    assert summary["failed_verification_success_rate"] == 0.0


def test_support_count_distribution_is_reported(calibration_module):
    summary = calibration_module.evaluate_samples(
        [
            _sample(calibration_module, "one", 0.4, False, "candidate", 1),
            _sample(calibration_module, "two", 0.7, True, "verified", 2),
            _sample(calibration_module, "two-b", 0.8, True, "verified", 2),
        ],
        source="unit",
        min_samples=1,
    )

    assert summary["support_count_distribution"] == {"1": 1, "2": 2}


def test_dry_run_requires_no_openai_or_docker(tmp_path):
    result = _run(
        tmp_path,
        {
            "HOWDEX_CALIBRATION_DRY_RUN": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN PASS" in result.stdout
    assert "no live calibration claim" in result.stdout


def test_dogfood_mode_handles_empty_data_with_insufficient_data(
    tmp_path,
    calibration_module,
):
    summary = calibration_module.dogfood_summary(
        results_root=tmp_path / "dogfood-results",
        codex_dir=tmp_path / ".howdex" / "dogfood" / "codex",
        base_dir=tmp_path,
    )

    assert summary["verdict"] == "INSUFFICIENT DATA"
    assert summary["sample_count"] == 0
    assert summary["dogfood_only"] is True
    assert summary["claim_scope"] == "DOGFOOD INTERNAL ONLY"


def _write_sample_dogfood_tree(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".howdex" / "dogfood" / "codex" / "procedures"
    codex_dir.mkdir(parents=True)
    entry = {
        "id": "howdex.proc.phase-one",
        "status": "candidate",
        "source": {
            "reference": "procedure-phase-one",
        },
        "verification": {
            "status": "required",
        },
        "provenance": {
            "evidence": [
                "support_count=1",
                "success_count=1",
                "confidence=0.7600",
            ],
        },
    }
    entry_path = codex_dir / "phase-one.json"
    entry_path.write_text(json.dumps(entry), encoding="utf-8")

    summary_dir = tmp_path / "dogfood-results" / "phase-one"
    summary_dir.mkdir(parents=True)
    summary = {
        "phase": "phase-one",
        "latest_test_passed": True,
        "latest_test_summary": "486 passed",
        "support_count": 1,
        "learned_procedure_ids": ["procedure-phase-one"],
        "codex_entry_paths": [str(entry_path)],
    }
    (summary_dir / "summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )


def test_dogfood_mode_reads_sample_dogfood_summaries(
    tmp_path,
    calibration_module,
):
    _write_sample_dogfood_tree(tmp_path)

    samples, counts = calibration_module.load_dogfood_samples(
        results_root=tmp_path / "dogfood-results",
        codex_dir=tmp_path / ".howdex" / "dogfood" / "codex",
        base_dir=tmp_path,
    )
    summary = calibration_module.dogfood_summary(
        results_root=tmp_path / "dogfood-results",
        codex_dir=tmp_path / ".howdex" / "dogfood" / "codex",
        base_dir=tmp_path,
    )

    assert counts["summaries_found"] == 1
    assert counts["samples_loaded"] == 1
    assert samples[0].predicted_confidence == 0.76
    assert samples[0].verification_status == "candidate"
    assert summary["sample_count"] == 1
    assert summary["verdict"] == "INSUFFICIENT DATA"


def test_output_schema_has_required_fields(calibration_module):
    summary = calibration_module.dry_run_summary()
    payload = calibration_module.output_schema(summary)

    required = {
        "source",
        "bins",
        "verified_success_rate",
        "candidate_success_rate",
        "stale_success_rate",
        "failed_verification_success_rate",
        "calibration_error",
        "support_count_distribution",
        "sample_count",
        "verdict",
    }
    assert required <= payload.keys()


def test_dry_run_does_not_make_live_claims(calibration_module):
    summary = calibration_module.dry_run_summary()

    assert summary["verdict"] == "DRY RUN PASS"
    assert summary["live_claim"] is False
    assert "synthetic harness only" in summary["claim_scope"]
