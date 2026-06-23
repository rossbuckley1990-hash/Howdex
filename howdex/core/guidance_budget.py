"""Deterministic retrieval-budget controls for large Codex guidance sets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from howdex.core.codex_staleness import (
    StalenessDecision,
    apply_staleness_confidence,
    evaluate_codex_staleness,
    has_compatibility_metadata,
)
from howdex.core.guidance_facts import (
    _categories_for_text,
    _procedure_context_text,
)
from howdex.core.guidance_utils import get_value
from howdex.core.receipts import procedure_trust_status
from howdex.core.retrieval import tokenize


@dataclass(frozen=True)
class GuidanceBudget:
    """Controls for selecting a compact, precise guidance set."""

    max_procedures: int = 3
    max_guidance_chars: int = 6_000
    min_relevance_score: float = 0.05
    diversity_by_category: bool = True
    suppress_low_confidence: bool = True
    suppress_stale_or_incompatible: bool = True
    include_candidates: bool = True
    include_verified_only: bool = False
    current_environment: Any = None
    low_confidence_threshold: float = 0.2


@dataclass(frozen=True)
class GuidanceSelectionDecision:
    """One included or excluded selection decision with an inspectable reason."""

    procedure: Any
    procedure_id: str
    title: str
    category: str
    status: str
    relevance_score: float
    adjusted_score: float
    reason: str
    staleness_status: str = "none"
    estimated_chars: int = 0


@dataclass(frozen=True)
class GuidanceProcedureSelection:
    """Selected procedures plus deterministic selection diagnostics."""

    selected: list[Any] = field(default_factory=list)
    included: list[GuidanceSelectionDecision] = field(default_factory=list)
    excluded: list[GuidanceSelectionDecision] = field(default_factory=list)
    omitted_count: int = 0
    context_budget_used: int = 0
    max_guidance_chars: int = 0

    def __iter__(self):
        return iter(self.selected)

    def __len__(self) -> int:
        return len(self.selected)

    def __getitem__(self, index: int) -> Any:
        return self.selected[index]


def select_guidance_procedures(
    query: str,
    candidates: Any,
    budget: GuidanceBudget | Mapping[str, Any] | None,
) -> GuidanceProcedureSelection:
    """Select a precise, bounded set of procedure-like objects for guidance."""
    resolved_budget = _coerce_budget(budget)
    candidate_list = _as_list(candidates)
    query_text = " ".join(str(query or "").split())
    query_categories = set(_categories_for_text(query_text))
    scored: list[tuple[float, int, Any, GuidanceSelectionDecision]] = []
    excluded: list[GuidanceSelectionDecision] = []

    for index, procedure in enumerate(candidate_list):
        score = _relevance_score(query_text, query_categories, procedure)
        status = _procedure_status(procedure)
        category = _category(procedure)
        staleness = _staleness(procedure, resolved_budget.current_environment)
        confidence = _confidence(procedure, status)
        adjusted = _adjusted_score(score, confidence, status, staleness)
        estimate = _estimated_chars(procedure)
        identity = _identity(procedure, index)
        title = _title(procedure, index)

        reason = _exclusion_reason(
            score=score,
            status=status,
            confidence=confidence,
            staleness=staleness,
            budget=resolved_budget,
        )
        decision = GuidanceSelectionDecision(
            procedure=procedure,
            procedure_id=identity,
            title=title,
            category=category,
            status=status,
            relevance_score=score,
            adjusted_score=adjusted,
            reason=reason or "eligible",
            staleness_status=staleness.status,
            estimated_chars=estimate,
        )
        if reason:
            excluded.append(decision)
            continue
        scored.append((adjusted, index, procedure, decision))

    scored.sort(
        key=lambda item: (
            -item[0],
            -item[3].relevance_score,
            _status_sort(item[3].status),
            item[3].title.casefold(),
            item[3].procedure_id.casefold(),
        )
    )

    selected: list[Any] = []
    included: list[GuidanceSelectionDecision] = []
    seen_signatures: set[str] = set()
    seen_category_signatures: set[tuple[str, str]] = set()
    used_chars = _base_guidance_overhead(query_text)
    max_chars = max(0, int(resolved_budget.max_guidance_chars))
    max_procedures = max(0, int(resolved_budget.max_procedures))

    for _, _, procedure, decision in scored:
        if len(selected) >= max_procedures:
            excluded.append(
                _replace_reason(decision, "max_procedures budget reached")
            )
            continue

        signature = _dedupe_signature(procedure)
        if signature in seen_signatures:
            excluded.append(
                _replace_reason(decision, "near-duplicate procedure suppressed")
            )
            continue

        category_signature = (decision.category, signature)
        if (
            resolved_budget.diversity_by_category
            and category_signature in seen_category_signatures
        ):
            excluded.append(
                _replace_reason(decision, "duplicate category/template suppressed")
            )
            continue

        projected_chars = used_chars + decision.estimated_chars
        if max_chars and projected_chars > max_chars:
            excluded.append(
                _replace_reason(decision, "max_guidance_chars budget reached")
            )
            continue

        selected.append(procedure)
        included.append(_replace_reason(decision, "included"))
        seen_signatures.add(signature)
        seen_category_signatures.add(category_signature)
        used_chars = projected_chars

    return GuidanceProcedureSelection(
        selected=selected,
        included=included,
        excluded=excluded,
        omitted_count=len(candidate_list) - len(selected),
        context_budget_used=min(used_chars, max_chars) if max_chars else used_chars,
        max_guidance_chars=max_chars,
    )


def _coerce_budget(budget: GuidanceBudget | Mapping[str, Any] | None) -> GuidanceBudget:
    if budget is None:
        return GuidanceBudget()
    if isinstance(budget, GuidanceBudget):
        return budget
    values = dict(budget)
    valid = GuidanceBudget.__dataclass_fields__.keys()
    return GuidanceBudget(**{key: values[key] for key in valid if key in values})


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, GuidanceProcedureSelection):
        return list(value.selected)
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _relevance_score(
    query: str,
    query_categories: set[str],
    procedure: Any,
) -> float:
    explicit_score = get_value(procedure, "score")
    try:
        explicit = float(explicit_score)
    except (TypeError, ValueError):
        explicit = 0.0
    text = _procedure_text(procedure)
    query_tokens = set(tokenize(query))
    proc_tokens = set(tokenize(text))
    token_score = _jaccard(query_tokens, proc_tokens)
    procedure_categories = set(_categories_for_text(text))
    category_score = 0.0
    if query_categories and query_categories != {"unknown"}:
        if procedure_categories & query_categories:
            category_score = 0.45
        elif procedure_categories - {"unknown"}:
            category_score = -0.25
    title = _title(procedure, 0).casefold()
    exact_boost = 0.2 if query and query.casefold() in title else 0.0
    score = max(explicit, token_score + category_score + exact_boost)
    return round(max(0.0, min(1.0, score)), 6)


def _adjusted_score(
    relevance: float,
    confidence: float,
    status: str,
    staleness: StalenessDecision,
) -> float:
    status_bonus = {
        "verified": 0.04,
        "candidate": 0.0,
        "experimental": -0.01,
        "deprecated": -0.2,
    }.get(status, 0.0)
    freshness_bonus = {
        "fresh": 0.02,
        "warning": -0.01,
        "unknown": -0.02,
        "stale": -0.08,
        "incompatible": -1.0,
        "none": 0.0,
    }.get(staleness.status, 0.0)
    decayed_confidence = apply_staleness_confidence(confidence, staleness)
    return round(
        max(
            0.0,
            min(
                1.0,
                relevance + status_bonus + freshness_bonus + (0.03 * decayed_confidence),
            ),
        ),
        6,
    )


def _exclusion_reason(
    *,
    score: float,
    status: str,
    confidence: float,
    staleness: StalenessDecision,
    budget: GuidanceBudget,
) -> str:
    if budget.include_verified_only and status != "verified":
        return "include_verified_only excludes non-verified procedure"
    if not budget.include_candidates and status == "candidate":
        return "include_candidates=False excludes candidate procedure"
    if score < float(budget.min_relevance_score):
        return "below min_relevance_score"
    if budget.suppress_low_confidence and confidence < float(budget.low_confidence_threshold):
        return "low confidence suppressed"
    if budget.suppress_stale_or_incompatible and staleness.status in {
        "stale",
        "incompatible",
    }:
        return f"{staleness.status} procedure suppressed"
    return ""


def _staleness(procedure: Any, current_environment: Any) -> StalenessDecision:
    if has_compatibility_metadata(procedure):
        return evaluate_codex_staleness(procedure, current_environment)
    return StalenessDecision(
        status="none",
        reasons=[],
        required_reverification=False,
        confidence_multiplier=1.0,
    )


def _procedure_status(procedure: Any) -> str:
    for key in ("status", "verification_status", "procedure_status", "proof_status"):
        value = str(get_value(procedure, key) or "").strip().casefold()
        if value in {"verified", "candidate", "experimental", "deprecated"}:
            return value
        if value == "observed_episode_support":
            return "candidate"
    if get_value(procedure, "procedure_verified") is True:
        return "verified"
    try:
        trust = procedure_trust_status(procedure)
    except Exception:
        trust = ""
    if trust == "verified":
        return "verified"
    if trust == "failed_verification":
        return "deprecated"
    return "candidate"


def _confidence(procedure: Any, status: str) -> float:
    value = get_value(procedure, "confidence")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.9 if status == "verified" else 0.6


def _category(procedure: Any) -> str:
    category = str(get_value(procedure, "category") or "").strip()
    if category:
        return category
    categories = [
        category
        for category in _categories_for_text(_procedure_text(procedure))
        if category != "unknown"
    ]
    return categories[0] if categories else "unknown"


def _procedure_text(procedure: Any) -> str:
    chunks = [
        str(get_value(procedure, "id") or ""),
        str(get_value(procedure, "title") or ""),
        str(get_value(procedure, "task_signature") or ""),
        str(get_value(procedure, "category") or ""),
        _flatten_text(get_value(procedure, "tags")),
        _flatten_text(get_value(procedure, "learned_facts")),
        _flatten_text(get_value(procedure, "avoid")),
        _flatten_text(get_value(procedure, "verification")),
        _flatten_text(get_value(procedure, "steps")),
        _flatten_text(get_value(procedure, "canonical_steps")),
    ]
    try:
        chunks.append(_procedure_context_text(procedure))
    except Exception:
        pass
    return "\n".join(chunk for chunk in chunks if chunk)


def _title(procedure: Any, index: int) -> str:
    return str(
        get_value(procedure, "task_signature")
        or get_value(procedure, "title")
        or get_value(procedure, "name")
        or get_value(procedure, "procedure_id")
        or get_value(procedure, "id")
        or f"procedure_{index}"
    )


def _identity(procedure: Any, index: int) -> str:
    return str(
        get_value(procedure, "procedure_id")
        or get_value(procedure, "id")
        or get_value(procedure, "task_signature")
        or get_value(procedure, "title")
        or f"procedure_{index}"
    )


def _dedupe_signature(procedure: Any) -> str:
    facts = get_value(procedure, "learned_facts")
    steps = get_value(procedure, "canonical_steps") or get_value(procedure, "steps")
    basis = {
        "category": _category(procedure),
        "facts": facts,
        "steps": steps,
        "verification": get_value(procedure, "verification"),
    }
    encoded = json.dumps(
        basis,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    tokens = tokenize(encoded)
    return " ".join(sorted(set(tokens)))


def _estimated_chars(procedure: Any) -> int:
    title = _title(procedure, 0)
    facts = _flatten_text(get_value(procedure, "learned_facts"))
    verification = _flatten_text(get_value(procedure, "verification"))
    avoid = _flatten_text(get_value(procedure, "avoid"))
    estimate = len(title) + len(facts) + len(verification) + len(avoid) + 280
    return max(160, estimate)


def _base_guidance_overhead(query: str) -> int:
    return 900 + len(query)


def _status_sort(status: str) -> int:
    return {
        "verified": 0,
        "candidate": 1,
        "experimental": 2,
        "deprecated": 3,
    }.get(status, 4)


def _replace_reason(
    decision: GuidanceSelectionDecision,
    reason: str,
) -> GuidanceSelectionDecision:
    return GuidanceSelectionDecision(
        procedure=decision.procedure,
        procedure_id=decision.procedure_id,
        title=decision.title,
        category=decision.category,
        status=decision.status,
        relevance_score=decision.relevance_score,
        adjusted_score=decision.adjusted_score,
        reason=reason,
        staleness_status=decision.staleness_status,
        estimated_chars=decision.estimated_chars,
    )


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(
            f"{key}: {_flatten_text(value[key])}"
            for key in sorted(value, key=lambda item: str(item))
        )
    if isinstance(value, (list, tuple, set)):
        values = sorted(value, key=str) if isinstance(value, set) else value
        return "\n".join(_flatten_text(item) for item in values)
    return "" if value is None else str(value)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return round(len(left & right) / len(left | right), 6)
