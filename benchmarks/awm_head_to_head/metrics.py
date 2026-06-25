"""Comparable metrics for AWM-style head-to-head benchmark rows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ConditionResult:
    condition: str
    task: str
    trials: int
    successes: int
    success_rate: float
    avg_attempts: float
    extraction_cost: float
    guidance_chars: int
    source_leakage: int
    auditability_score: float
    verification_coverage: float
    calibration_coverage: float
    portability_score: float
    base_prompt_sha256: str
    memory_strategy: str
    verdict: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_leakage_score(text: str, markers: tuple[str, ...] = ()) -> int:
    """Detect direct source/answer paste markers in guidance text."""
    haystack = str(text or "")
    generic_markers = (
        "```python",
        "```js",
        "```javascript",
        "FROM python:",
        "class Handler",
        "def required_mode",
        "#!/usr/bin/env",
        "BEGIN PRIVATE KEY",
    )
    return int(any(marker in haystack for marker in generic_markers + tuple(markers)))


def success_rate(successes: int, trials: int) -> float:
    if trials <= 0:
        return 0.0
    return round(successes / trials, 4)


def average_attempts(attempts: list[int]) -> float:
    if not attempts:
        return 0.0
    return round(sum(attempts) / len(attempts), 4)


def auditability_score(
    *,
    has_structured_steps: bool,
    has_trace_provenance: bool,
    has_receipt: bool,
    freeform_summary: bool = False,
) -> float:
    score = 0.0
    if has_structured_steps:
        score += 0.3
    if has_trace_provenance:
        score += 0.3
    if has_receipt:
        score += 0.4
    if freeform_summary:
        score = min(score, 0.45)
    return round(score, 4)


def verification_coverage(verified: int, total: int) -> float:
    return success_rate(verified, total)


def calibration_coverage(calibrated: int, total: int) -> float:
    return success_rate(calibrated, total)


def portability_score(
    *,
    json_exportable: bool,
    receipt_backed: bool,
    framework_neutral: bool,
) -> float:
    score = 0.0
    if json_exportable:
        score += 0.35
    if receipt_backed:
        score += 0.35
    if framework_neutral:
        score += 0.30
    return round(score, 4)


def ensure_comparable_schema(rows: list[ConditionResult]) -> list[dict[str, Any]]:
    payload = [row.to_dict() for row in rows]
    if not payload:
        return payload
    keys = set(payload[0])
    for row in payload:
        if set(row) != keys:
            raise ValueError("condition result schemas are not comparable")
    return payload


def machine_summary(rows: list[ConditionResult], *, mode: str) -> dict[str, Any]:
    payload = ensure_comparable_schema(rows)
    return {
        "benchmark": "awm_head_to_head",
        "mode": mode,
        "claim": (
            "Harness output only. This is not evidence that Howdex beats AWM "
            "unless a real baseline integration and live run are recorded."
        ),
        "conditions": payload,
    }


def summary_json(rows: list[ConditionResult], *, mode: str) -> str:
    return json.dumps(machine_summary(rows, mode=mode), indent=2, sort_keys=True)
