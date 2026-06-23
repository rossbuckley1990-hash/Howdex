"""Stdlib-only integrity tests for the public Howdex Codex catalogue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CODEX = ROOT / "codex"
ENTRIES = CODEX / "entries"
SCHEMAS = CODEX / "schemas"
REQUIRED_PROCEDURE_FIELDS = {
    "avoid",
    "category",
    "id",
    "learned_facts",
    "policy",
    "provenance",
    "risk_level",
    "source",
    "status",
    "tags",
    "title",
    "verification",
    "version",
}
REQUIRED_RECEIPT_FIELDS = {
    "artifact_hashes",
    "environment",
    "exit_code",
    "expected_signal",
    "observed_signal",
    "procedure_id",
    "receipt_id",
    "status",
    "verified_at",
    "verifier_command",
    "verifier_type",
}
SOURCE_MARKERS = (
    "def ",
    "import ",
    "class ",
    "#!/usr/bin/env",
)


def _entry_paths() -> list[Path]:
    return sorted(ENTRIES.glob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), path
    return payload


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def test_expected_seed_entries_exist():
    assert {path.name for path in _entry_paths()} == {
        "docker_compose_health_recovery.json",
        "macgyver_zb2_decoder.json",
        "node_missing_dependency.json",
        "polyglot_openssl_sha256_reverse_seed.json",
    }


def test_every_entry_has_required_machine_readable_metadata():
    for path in _entry_paths():
        entry = _load(path)
        assert REQUIRED_PROCEDURE_FIELDS <= entry.keys(), path
        assert isinstance(entry["learned_facts"], list), path
        assert entry["learned_facts"], path
        assert isinstance(entry["avoid"], list), path
        assert isinstance(entry["verification"], dict), path
        assert entry["verification"].get("verifier_type"), path
        assert entry["verification"].get("verifier_command"), path
        assert entry["verification"].get("expected_signal"), path
        assert isinstance(entry["policy"], dict), path
        assert entry["policy"].get("source_artifacts") in {
            "excluded",
            "excluded_by_default",
            "policy_controlled",
        }, path
        assert isinstance(entry["provenance"], dict), path
        assert entry["provenance"].get("evidence"), path


def test_entry_ids_are_unique():
    ids = [_load(path)["id"] for path in _entry_paths()]
    assert len(ids) == len(set(ids))


def test_public_entries_exclude_pasted_source_and_fenced_blocks():
    for path in _entry_paths():
        entry = _load(path)
        text = "\n".join(_strings(entry))
        lowered = text.casefold()
        assert "```" not in text, path
        for marker in SOURCE_MARKERS:
            assert marker not in lowered, (path, marker)
        assert entry["policy"]["source_artifacts"] != "included", path


def test_schema_files_exist_and_require_contract_fields():
    procedure_path = SCHEMAS / "procedure.schema.json"
    receipt_path = SCHEMAS / "receipt.schema.json"
    assert procedure_path.is_file()
    assert receipt_path.is_file()

    procedure = _load(procedure_path)
    receipt = _load(receipt_path)
    assert set(procedure["required"]) == REQUIRED_PROCEDURE_FIELDS
    assert set(receipt["required"]) == REQUIRED_RECEIPT_FIELDS
    assert REQUIRED_PROCEDURE_FIELDS <= procedure["properties"].keys()
    assert REQUIRED_RECEIPT_FIELDS <= receipt["properties"].keys()


def test_all_codex_json_is_canonical_pretty_printed():
    paths = sorted(CODEX.rglob("*.json"))
    assert paths
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        expected = (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        assert raw == expected, path
        assert raw.endswith("\n"), path
        assert list(payload) == sorted(payload), path
