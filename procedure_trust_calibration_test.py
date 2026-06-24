"""Procedure trust calibration benchmark harness.

Question:
    Do Howdex confidence and verification states predict real held-out success?

Dry-run mode validates the machinery without external dependencies:
    HOWDEX_CALIBRATION_DRY_RUN=1 python procedure_trust_calibration_test.py

Dogfood mode reads existing dogfood-results and local dogfood Codex metadata:
    HOWDEX_CALIBRATION_SOURCE=dogfood python procedure_trust_calibration_test.py

Dogfood calibration is internal evidence only. This harness never fabricates
live results and never mutates dogfood state.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BIN_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
MIN_REAL_SAMPLES = 10
CALIBRATION_ERROR_THRESHOLD = 0.15
STATUS_ORDER = (
    "verified",
    "candidate",
    "stale",
    "failed_verification",
)


@dataclass(frozen=True)
class CalibrationSample:
    sample_id: str
    predicted_confidence: float
    actual_success: bool
    verification_status: str
    support_count: int
    source: str
    dogfood_only: bool = False
    metadata: dict[str, Any] | None = None

    def normalized(self) -> "CalibrationSample":
        return CalibrationSample(
            sample_id=self.sample_id,
            predicted_confidence=max(0.0, min(1.0, float(self.predicted_confidence))),
            actual_success=bool(self.actual_success),
            verification_status=normalize_status(self.verification_status),
            support_count=max(0, int(self.support_count)),
            source=self.source,
            dogfood_only=bool(self.dogfood_only),
            metadata=dict(self.metadata or {}),
        )


def normalize_status(status: str | None) -> str:
    raw = str(status or "").strip().lower().replace("-", "_")
    if raw in {"verified", "signed_verified"}:
        return "verified"
    if raw in {"failed", "failed_verification", "verification_failed"}:
        return "failed_verification"
    if raw in {"stale", "deprecated"}:
        return "stale"
    return "candidate"


def bin_label(confidence: float) -> str:
    value = max(0.0, min(1.0, float(confidence)))
    for low, high in zip(BIN_EDGES, BIN_EDGES[1:]):
        if value < high or high == 1.0:
            return f"{low:.1f}-{high:.1f}"
    return "0.8-1.0"


def calibration_bins(samples: list[CalibrationSample]) -> list[dict[str, Any]]:
    normalized = [sample.normalized() for sample in samples]
    rows: list[dict[str, Any]] = []
    for low, high in zip(BIN_EDGES, BIN_EDGES[1:]):
        label = f"{low:.1f}-{high:.1f}"
        bucket = [
            sample for sample in normalized if bin_label(sample.predicted_confidence) == label
        ]
        if not bucket:
            rows.append(
                {
                    "bin": label,
                    "predicted_mean": None,
                    "actual_success": None,
                    "count": 0,
                    "error": None,
                }
            )
            continue
        predicted = round(
            sum(sample.predicted_confidence for sample in bucket) / len(bucket),
            4,
        )
        actual = round(
            sum(1.0 if sample.actual_success else 0.0 for sample in bucket)
            / len(bucket),
            4,
        )
        rows.append(
            {
                "bin": label,
                "predicted_mean": predicted,
                "actual_success": actual,
                "count": len(bucket),
                "error": round(abs(predicted - actual), 4),
            }
        )
    return rows


def expected_calibration_error(samples: list[CalibrationSample]) -> float:
    total = len(samples)
    if total == 0:
        return 0.0
    weighted = 0.0
    for row in calibration_bins(samples):
        if row["count"] and row["error"] is not None:
            weighted += (row["count"] / total) * float(row["error"])
    return round(weighted, 4)


def success_rate_for_status(
    samples: list[CalibrationSample],
    status: str,
) -> float | None:
    normalized_status = normalize_status(status)
    bucket = [
        sample.normalized()
        for sample in samples
        if sample.normalized().verification_status == normalized_status
    ]
    if not bucket:
        return None
    return round(
        sum(1.0 if sample.actual_success else 0.0 for sample in bucket)
        / len(bucket),
        4,
    )


def support_count_distribution(
    samples: list[CalibrationSample],
) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for sample in samples:
        key = str(sample.normalized().support_count)
        distribution[key] = distribution.get(key, 0) + 1
    return dict(sorted(distribution.items(), key=lambda item: int(item[0])))


def evaluate_samples(
    samples: list[CalibrationSample],
    *,
    source: str,
    dogfood_only: bool = False,
    dry_run: bool = False,
    min_samples: int = MIN_REAL_SAMPLES,
    threshold: float = CALIBRATION_ERROR_THRESHOLD,
) -> dict[str, Any]:
    normalized = [sample.normalized() for sample in samples]
    bins = calibration_bins(normalized)
    calibration_error = expected_calibration_error(normalized)
    sample_count = len(normalized)
    actual_rate = (
        sum(1.0 if sample.actual_success else 0.0 for sample in normalized)
        / sample_count
        if sample_count
        else 0.0
    )
    predicted_rate = (
        sum(sample.predicted_confidence for sample in normalized) / sample_count
        if sample_count
        else 0.0
    )

    if dry_run:
        verdict = "DRY RUN PASS" if sample_count and calibration_error <= threshold else "DRY RUN FAIL"
        live_claim = False
        claim_scope = "synthetic harness only; no live calibration claim"
    elif sample_count < min_samples:
        verdict = "INSUFFICIENT DATA"
        live_claim = False
        claim_scope = (
            "DOGFOOD INTERNAL ONLY"
            if dogfood_only
            else "insufficient held-out evidence"
        )
    elif calibration_error <= threshold:
        verdict = "CALIBRATED"
        live_claim = not dogfood_only
        claim_scope = "DOGFOOD INTERNAL ONLY" if dogfood_only else "held-out calibration"
    elif predicted_rate - actual_rate > threshold:
        verdict = "MIS-CALIBRATED"
        live_claim = not dogfood_only
        claim_scope = "DOGFOOD INTERNAL ONLY" if dogfood_only else "held-out calibration"
    else:
        verdict = "MIS-CALIBRATED"
        live_claim = not dogfood_only
        claim_scope = "DOGFOOD INTERNAL ONLY" if dogfood_only else "held-out calibration"

    summary = {
        "source": source,
        "dogfood_only": bool(dogfood_only),
        "claim_scope": claim_scope,
        "live_claim": live_claim,
        "bins": bins,
        "verified_success_rate": success_rate_for_status(normalized, "verified"),
        "candidate_success_rate": success_rate_for_status(normalized, "candidate"),
        "stale_success_rate": success_rate_for_status(normalized, "stale"),
        "failed_verification_success_rate": success_rate_for_status(
            normalized,
            "failed_verification",
        ),
        "calibration_error": calibration_error,
        "support_count_distribution": support_count_distribution(normalized),
        "sample_count": sample_count,
        "verdict": verdict,
    }
    if sample_count < min_samples and not dry_run:
        summary["minimum_samples_required"] = min_samples
    return summary


def synthetic_samples() -> list[CalibrationSample]:
    """Deterministic samples that validate the calibration machinery only."""
    return [
        CalibrationSample("synthetic-verified-1", 0.92, True, "verified", 8, "synthetic"),
        CalibrationSample("synthetic-verified-2", 0.86, True, "verified", 5, "synthetic"),
        CalibrationSample("synthetic-candidate-1", 0.50, True, "candidate", 2, "synthetic"),
        CalibrationSample("synthetic-candidate-2", 0.50, False, "candidate", 1, "synthetic"),
        CalibrationSample("synthetic-stale-1", 0.10, False, "stale", 3, "synthetic"),
        CalibrationSample("synthetic-stale-2", 0.10, False, "stale", 2, "synthetic"),
        CalibrationSample(
            "synthetic-failed-1",
            0.10,
            False,
            "failed_verification",
            4,
            "synthetic",
        ),
        CalibrationSample(
            "synthetic-failed-2",
            0.10,
            False,
            "failed_verification",
            1,
            "synthetic",
        ),
    ]


def dry_run_summary() -> dict[str, Any]:
    return evaluate_samples(
        synthetic_samples(),
        source="synthetic_dry_run",
        dry_run=True,
        min_samples=1,
    )


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_codex_metadata(codex_dir: Path) -> dict[str, dict[str, Any]]:
    procedures_dir = codex_dir / "procedures"
    if not procedures_dir.is_dir():
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    for path in sorted(procedures_dir.glob("*.json")):
        entry = load_json(path)
        if not isinstance(entry, dict):
            continue
        ids = {
            str(entry.get("id") or ""),
            str((entry.get("source") or {}).get("reference") or ""),
        }
        for identifier in ids:
            if identifier:
                metadata[identifier] = entry
    return metadata


def load_dogfood_samples(
    *,
    results_root: Path = Path("dogfood-results"),
    codex_dir: Path = Path(".howdex/dogfood/codex"),
    base_dir: Path | None = None,
) -> tuple[list[CalibrationSample], dict[str, int]]:
    """Read existing dogfood summaries/Codex entries without mutating them."""
    root = Path(results_root)
    base = Path.cwd() if base_dir is None else Path(base_dir)
    codex_metadata = load_codex_metadata(Path(codex_dir))
    samples: list[CalibrationSample] = []
    counts = {
        "summaries_found": 0,
        "summaries_with_outcome": 0,
        "samples_loaded": 0,
        "samples_skipped_missing_confidence": 0,
    }
    if not root.is_dir():
        return samples, counts

    for summary_file in sorted(root.glob("*/summary.json")):
        summary = load_json(summary_file)
        if not isinstance(summary, dict):
            continue
        counts["summaries_found"] += 1
        if "latest_test_passed" not in summary:
            continue
        counts["summaries_with_outcome"] += 1
        entry = _entry_for_summary(summary, codex_metadata, base)
        confidence = _confidence_from_summary_or_entry(summary, entry)
        if confidence is None:
            counts["samples_skipped_missing_confidence"] += 1
            continue
        samples.append(
            CalibrationSample(
                sample_id=str(summary.get("phase") or summary_file.parent.name),
                predicted_confidence=confidence,
                actual_success=bool(summary.get("latest_test_passed")),
                verification_status=_status_from_summary_or_entry(summary, entry),
                support_count=int(summary.get("support_count") or _support_from_entry(entry) or 0),
                source=str(summary_file),
                dogfood_only=True,
                metadata={
                    "summary_path": str(summary_file),
                    "codex_entry_id": entry.get("id") if entry else None,
                },
            )
        )
    counts["samples_loaded"] = len(samples)
    return samples, counts


def _entry_for_summary(
    summary: dict[str, Any],
    codex_metadata: dict[str, dict[str, Any]],
    base_dir: Path,
) -> dict[str, Any] | None:
    for procedure_id in summary.get("learned_procedure_ids") or []:
        entry = codex_metadata.get(str(procedure_id))
        if entry:
            return entry
    for raw_path in summary.get("codex_entry_paths") or []:
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = base_dir / path
        entry = load_json(path)
        if isinstance(entry, dict):
            return entry
    return None


def _confidence_from_summary_or_entry(
    summary: dict[str, Any],
    entry: dict[str, Any] | None,
) -> float | None:
    for key in ("predicted_confidence", "confidence"):
        if key in summary:
            try:
                return max(0.0, min(1.0, float(summary[key])))
            except (TypeError, ValueError):
                pass
    if entry:
        for item in (entry.get("provenance") or {}).get("evidence") or []:
            match = re.search(r"\bconfidence=([0-9.]+)", str(item))
            if match:
                return max(0.0, min(1.0, float(match.group(1))))
    return None


def _support_from_entry(entry: dict[str, Any] | None) -> int | None:
    if not entry:
        return None
    for item in (entry.get("provenance") or {}).get("evidence") or []:
        match = re.search(r"\bsupport_count=(\d+)", str(item))
        if match:
            return int(match.group(1))
    return None


def _status_from_summary_or_entry(
    summary: dict[str, Any],
    entry: dict[str, Any] | None,
) -> str:
    if "verification_status" in summary:
        return normalize_status(summary.get("verification_status"))
    if "procedure_status" in summary:
        return normalize_status(summary.get("procedure_status"))
    if entry:
        verification = entry.get("verification") or {}
        verification_status = normalize_status(verification.get("status"))
        public_status = normalize_status(entry.get("status"))
        if verification_status == "failed_verification":
            return "failed_verification"
        if public_status in {"verified", "stale"}:
            return public_status
        return public_status
    if summary.get("receipt_attached"):
        return "candidate"
    return "candidate"


def dogfood_summary(
    *,
    results_root: Path = Path("dogfood-results"),
    codex_dir: Path = Path(".howdex/dogfood/codex"),
    base_dir: Path | None = None,
) -> dict[str, Any]:
    samples, counts = load_dogfood_samples(
        results_root=results_root,
        codex_dir=codex_dir,
        base_dir=base_dir,
    )
    summary = evaluate_samples(
        samples,
        source="dogfood",
        dogfood_only=True,
        dry_run=False,
        min_samples=MIN_REAL_SAMPLES,
    )
    summary["dogfood_counts"] = counts
    if summary["verdict"] != "INSUFFICIENT DATA":
        summary["claim_scope"] = "DOGFOOD INTERNAL ONLY"
    return summary


def format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def format_table(summary: dict[str, Any]) -> str:
    lines = ["bin | predicted_mean | actual_success | count | error"]
    for row in summary.get("bins", []):
        lines.append(
            " | ".join(
                [
                    str(row["bin"]),
                    format_value(row["predicted_mean"]),
                    format_value(row["actual_success"]),
                    str(row["count"]),
                    format_value(row["error"]),
                ]
            )
        )
    return "\n".join(lines)


def output_schema(summary: dict[str, Any]) -> dict[str, Any]:
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
    missing = sorted(required - set(summary))
    if missing:
        raise ValueError(f"missing summary fields: {', '.join(missing)}")
    return summary


def main() -> int:
    dry_run = os.getenv("HOWDEX_CALIBRATION_DRY_RUN") == "1"
    source = os.getenv("HOWDEX_CALIBRATION_SOURCE", "").strip().lower()
    if dry_run or not source:
        summary = dry_run_summary()
    elif source == "dogfood":
        summary = dogfood_summary(
            results_root=Path(
                os.getenv("HOWDEX_CALIBRATION_RESULTS_DIR", "dogfood-results")
            ),
            codex_dir=Path(
                os.getenv(
                    "HOWDEX_CALIBRATION_CODEX_DIR",
                    ".howdex/dogfood/codex",
                )
            ),
        )
    else:
        raise SystemExit(
            "unsupported HOWDEX_CALIBRATION_SOURCE; use dogfood or dry-run"
        )

    output_schema(summary)
    print(format_table(summary))
    print()
    if summary.get("dogfood_only"):
        print("DOGFOOD INTERNAL ONLY")
    if summary.get("verdict") == "DRY RUN PASS":
        print("DRY RUN PASS — synthetic harness validated; no live calibration claim.")
    elif summary.get("verdict") == "INSUFFICIENT DATA":
        counts = summary.get("dogfood_counts") or {}
        print(
            "INSUFFICIENT DATA "
            f"(samples={summary.get('sample_count', 0)}, "
            f"summaries_found={counts.get('summaries_found', 0)})"
        )
    print(json.dumps(output_schema(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
