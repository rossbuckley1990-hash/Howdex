from __future__ import annotations

import json
from pathlib import Path

import pytest

from howdex.cli import main
from howdex.registry import (
    parse_registry_source,
    registry_add,
    registry_index,
    registry_init,
    registry_pull,
    registry_verify,
)


def _entry(entry_id: str = "howdex.registry_test") -> dict:
    return {
        "avoid": ["Do not claim success before verification."],
        "category": "software_dependency_recovery",
        "id": entry_id,
        "learned_facts": ["Inspect the local manifest before changing dependencies."],
        "policy": {
            "allowed": ["Inspect local project files."],
            "forbidden": ["Run destructive host commands."],
            "requires_human_review": False,
            "source_artifacts": "excluded",
        },
        "provenance": {
            "evidence": ["registry protocol test fixture"],
            "learned_from": ["tests/test_registry_protocol.py"],
            "limitations": ["test fixture only"],
        },
        "risk_level": "low",
        "source": {
            "kind": "test",
            "name": "registry protocol fixture",
            "reference": "tests/test_registry_protocol.py",
        },
        "status": "candidate",
        "tags": ["dependency", "registry"],
        "title": "Recover a dependency issue",
        "verification": {
            "expected_signal": "dependency verifier passed",
            "status": "required",
            "verifier_command": "python -m pytest tests/test_registry_protocol.py",
            "verifier_type": "test",
        },
        "version": "1.0.0",
    }


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_registry_init_creates_layout(tmp_path):
    root = tmp_path / "registry"

    result = registry_init(root)

    assert result["manifest"] == root / "manifest.json"
    for dirname in ("procedures", "receipts", "signatures", "indexes"):
        assert (root / dirname).is_dir()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["registry_name"] == "registry"
    assert manifest["entry_count"] == 0
    assert manifest["root_hash"].startswith("sha256:")


def test_registry_index_creates_indexes(tmp_path):
    root = tmp_path / "registry"
    registry_init(root)
    _write(root / "procedures" / "entry.json", _entry())

    result = registry_index(root)

    assert result["entries"] == 1
    assert json.loads((root / "indexes" / "by_category.json").read_text()) == {
        "software_dependency_recovery": ["howdex.registry_test"]
    }
    assert json.loads((root / "indexes" / "by_tag.json").read_text())["registry"] == [
        "howdex.registry_test"
    ]


def test_registry_verify_passes_valid_registry(tmp_path):
    root = tmp_path / "registry"
    registry_init(root)
    _write(root / "procedures" / "entry.json", _entry())
    registry_index(root)

    result = registry_verify(root)

    assert result.ok
    assert result.errors == []


def test_registry_verify_fails_tampered_entry_root_hash(tmp_path):
    root = tmp_path / "registry"
    registry_init(root)
    entry_path = _write(root / "procedures" / "entry.json", _entry())
    registry_index(root)
    tampered = json.loads(entry_path.read_text(encoding="utf-8"))
    tampered["learned_facts"].append("Tampered fact.")
    _write(entry_path, tampered)

    result = registry_verify(root)

    assert not result.ok
    assert any(finding.code == "root_hash_mismatch" for finding in result.errors)


def test_registry_add_inserts_entry(tmp_path):
    source = _write(tmp_path / "entry.json", _entry("howdex.added_entry"))
    root = tmp_path / "registry"

    result = registry_add(source, root)

    assert result["entries"] == 1
    assert (root / "procedures" / "howdex.added_entry.json").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 1
    assert manifest["candidate_count"] == 1


def test_registry_pull_local_path_works(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    registry_init(source)
    _write(source / "procedures" / "entry.json", _entry())
    registry_index(source)

    result = registry_pull(source, destination)

    assert result["entries"] == 1
    assert registry_verify(destination).ok


def test_registry_pull_file_url_works(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    registry_init(source)
    _write(source / "procedures" / "entry.json", _entry())
    registry_index(source)

    result = registry_pull(source.as_uri(), destination)

    assert result["entries"] == 1
    assert registry_verify(destination).ok


def test_manifest_counts_correct(tmp_path):
    root = tmp_path / "registry"
    registry_init(root)
    _write(root / "procedures" / "candidate.json", _entry("howdex.candidate"))
    _write(
        root / "procedures" / "verified.json",
        _entry("howdex.verified")
        | {
            "status": "verified",
            "verification": {
                "expected_signal": "ok",
                "receipt_id": "receipt-1",
                "status": "verified",
                "verifier_command": "true",
                "verifier_type": "test",
            },
        },
    )

    registry_index(root)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 2
    assert manifest["candidate_count"] == 1
    assert manifest["verified_count"] == 1


def test_unsupported_remote_source_gives_clear_error(tmp_path):
    parsed = parse_registry_source("git+https://example.invalid/org/codex.git")

    assert parsed.mode == "git+https"
    with pytest.raises(ValueError, match="unsupported registry source mode"):
        registry_pull("git+https://example.invalid/org/codex.git", tmp_path / "registry")


def test_registry_cli_commands(tmp_path, capsys):
    root = tmp_path / "registry"
    source = _write(tmp_path / "entry.json", _entry())

    assert main(["registry", "init", str(root)]) == 0
    assert main(["registry", "add", str(source), "--to", str(root)]) == 0
    assert main(["registry", "index", str(root)]) == 0
    assert main(["registry", "verify", str(root)]) == 0
    assert main(["registry", "trust-policy", str(root)]) == 0
    output = capsys.readouterr().out
    assert "registry verify passed" in output
