"""Tests for the expanded intent taxonomy (transform / validate / repair).

These intents were added after dogfooding showed that data-wrangling and
infra-recovery verbs (normalize_*, coerce_*, clean_*, convert_*, recover_*,
repair_*, migrate_*) were all falling to `unknown` intent, which caused
~50% of steps in those workflows to be dropped during consolidation and
made learned procedures useless for transfer.
"""

from howdex.core.classification import INTENTS
from howdex.core.tool_calls import infer_intent, normalize_tool_name


# ---------------------------------------------------------------- #
# New intents exist in the canonical intent set
# ---------------------------------------------------------------- #
def test_new_intents_are_in_canonical_set():
    assert "transform" in INTENTS
    assert "validate" in INTENTS
    assert "repair" in INTENTS


# ---------------------------------------------------------------- #
# Data-wrangling verbs -> transform intent
# ---------------------------------------------------------------- #
WRANGLING_VERBS = [
    "strip_whitespace",
    "normalize_dates",
    "normalize_nulls",
    "coerce_numeric",
    "coerce_integer",
    "lowercase_column",
    "uppercase_column",
    "clean_text_encoding",
    "convert_unix_timestamps",
    "cast_column",
    "rename_column",
    "reshape_data",
    "merge_dataframes",
    "split_column",
    "deduplicate_rows",
    "backfill_nulls",
    "impute_missing",
    "round_floats",
    "scale_features",
    "standardize_units",
    "encode_categorical",
    "decode_json",
    "sanitize_input",
    "escape_html",
    "bucket_continuous",
    "aggregate_by",
    "summarize_by",
    "pivot_table",
    "melt_table",
    "format_strings",
]


def test_wrangling_verbs_map_to_transform_intent():
    failures = []
    for verb in WRANGLING_VERBS:
        canonical = normalize_tool_name(verb)
        intent, reason = infer_intent(canonical)
        if intent != "transform":
            failures.append(f"{verb} -> {canonical} -> {intent} ({reason})")
    assert not failures, (
        f"{len(failures)} wrangling verbs did not map to transform intent:\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------- #
# Validation verbs -> validate intent
# ---------------------------------------------------------------- #
VALIDATION_VERBS = [
    "validate_schema",
    "verify_csv",
    "check_constraints",
    "assert_row_count",
    "lint_config",
    "audit_logs",
    "diagnose_failure",
]


def test_validation_verbs_map_to_validate_intent():
    failures = []
    for verb in VALIDATION_VERBS:
        canonical = normalize_tool_name(verb)
        intent, reason = infer_intent(canonical)
        if intent != "validate":
            failures.append(f"{verb} -> {canonical} -> {intent} ({reason})")
    assert not failures, (
        f"{len(failures)} validation verbs did not map to validate intent:\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------- #
# Infra-recovery verbs -> repair intent
# ---------------------------------------------------------------- #
RECOVERY_VERBS = [
    "repair_service",
    "recover_database",
    "restore_backup",
    "fix_migration",
    "heal_cluster",
    "restart_container",
    "reload_config",
    "refresh_cache",
    "reconcile_state",
    "migrate_schema",
]


def test_recovery_verbs_map_to_repair_intent():
    failures = []
    for verb in RECOVERY_VERBS:
        canonical = normalize_tool_name(verb)
        intent, reason = infer_intent(canonical)
        if intent != "repair":
            failures.append(f"{verb} -> {canonical} -> {intent} ({reason})")
    assert not failures, (
        f"{len(failures)} recovery verbs did not map to repair intent:\n  "
        + "\n  ".join(failures)
    )


# ---------------------------------------------------------------- #
# No regressions: previously-working verbs still map correctly
# ---------------------------------------------------------------- #
def test_existing_verbs_still_canonicalize_correctly():
    cases = {
        "read_file": "read",
        "search_code": "search",
        "list_buckets": "list",
        "create_user": "create",
        "edit_file": "update",
        "write_file": "write",
        "drop_duplicates": "delete",
        "run_tests": "execute",
        "execute_command": "execute",
        "transfer_ownership": "transfer",
        "notify_user": "notify",
        "approve_request": "approve",
        "reject_request": "reject",
        "authenticate_user": "authenticate",
    }
    failures = []
    for verb, expected_intent in cases.items():
        canonical = normalize_tool_name(verb)
        intent, _ = infer_intent(canonical)
        if intent != expected_intent:
            failures.append(f"{verb}: expected {expected_intent}, got {intent}")
    assert not failures, "\n  ".join(failures)


# ---------------------------------------------------------------- #
# Side-effect classification for new intents
# ---------------------------------------------------------------- #
def test_transform_is_classified_as_mutating():
    """Transforms change data shape, so they should not be read_only."""
    from howdex.core.classification import infer_side_effect_class

    side_effect, _ = infer_side_effect_class(
        canonical_name="normalize_dates",
        intent="transform",
        arguments={"column": "order_date"},
        metadata={},
    )
    assert side_effect in {"local_write", "external_write"}


def test_validate_is_classified_as_read_only():
    """Validation reads data to check it; it should not mutate."""
    from howdex.core.classification import infer_side_effect_class

    side_effect, _ = infer_side_effect_class(
        canonical_name="verify_csv",
        intent="validate",
        arguments={},
        metadata={},
    )
    assert side_effect == "read_only"


def test_repair_is_classified_as_mutating():
    """Repairs change state, so they should not be read_only."""
    from howdex.core.classification import infer_side_effect_class

    side_effect, _ = infer_side_effect_class(
        canonical_name="recover_database",
        intent="repair",
        arguments={},
        metadata={},
    )
    assert side_effect in {"local_write", "external_write"}


# ---------------------------------------------------------------- #
# A full wrangling episode now survives consolidation
# ---------------------------------------------------------------- #
def test_wrangling_episode_survives_consolidation():
    """A 9-step wrangling trace should produce a procedure with all 9 steps,
    not be dropped to <50% known ratio."""
    import tempfile
    from pathlib import Path

    from howdex import Howdex

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "wrangle.db"
        mem = Howdex(path=str(db), embedder="hashing")
        mem.start_session("clean_orders_csv")
        # Use the same 9 verbs as the dogfood run
        for verb, args in [
            ("read_file", {"path": "spec.txt"}),
            ("read_csv", {"path": "orders.csv"}),
            ("strip_whitespace", {"columns": ["order_id"]}),
            ("drop_duplicates", {"key_columns": ["order_id"]}),
            ("normalize_dates", {"column": "order_date"}),
            ("coerce_numeric", {"column": "amount_usd"}),
            ("lowercase_column", {"column": "status"}),
            ("write_csv", {"path": "orders_clean.csv"}),
            ("verify_csv", {"path": "orders_clean.csv"}),
        ]:
            mem.log_tool_call(verb, args, "ok")
        mem.end_session("success")

        procs = mem.learn(min_samples=1)
        assert len(procs) == 1, f"expected 1 procedure, got {len(procs)}"
        p = procs[0]
        # All 9 steps should survive — previously 4-5 of them would be
        # dropped because their verbs mapped to `unknown` intent.
        assert len(p.steps) == 9, (
            f"expected 9 steps in consolidated procedure, got {len(p.steps)}; "
            f"steps: {[s.get('action') for s in p.steps]}"
        )
        mem.close()
