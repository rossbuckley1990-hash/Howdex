"""Portable procedure and local Codex CLI tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from howdex import Howdex

CLI = [sys.executable, "-m", "howdex.cli"]
PUBLIC_CODEX_REQUIRED_FIELDS = {
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


def _run(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOWDEX_EMBEDDER"] = "hash"
    return subprocess.run(
        CLI + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _seed_procedure(db: Path, task: str = "deploy api") -> None:
    mem = Howdex(path=db, embedder="hashing")
    try:
        for _ in range(3):
            with mem.session(task) as session:
                session.step("check_database_url", "present")
                session.step("run_tests", "passed")
                session.step("deploy_service", "healthy")
        learned = mem.learn(min_samples=3)
        assert len(learned) == 1
    finally:
        mem.close()


def _assert_public_codex_entry(entry: dict) -> None:
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "codex" / "schemas" / "procedure.schema.json")
        .read_text(encoding="utf-8")
    )
    assert set(schema["required"]) == PUBLIC_CODEX_REQUIRED_FIELDS
    assert PUBLIC_CODEX_REQUIRED_FIELDS <= entry.keys()
    assert set(entry) <= set(schema["properties"])
    assert entry["status"] in schema["properties"]["status"]["enum"]
    assert entry["status"] is not None
    assert isinstance(entry["learned_facts"], list)
    assert entry["learned_facts"]
    assert entry["verification"]["status"] in schema["properties"]["verification"]["properties"][
        "status"
    ]["enum"]
    assert entry["verification"]["verifier_type"]
    assert entry["verification"]["verifier_command"]
    assert entry["verification"]["expected_signal"]
    assert entry["policy"]["source_artifacts"] in schema["properties"]["policy"]["properties"][
        "source_artifacts"
    ]["enum"]
    for object_field in ("policy", "provenance", "source", "verification"):
        assert set(entry[object_field]) <= set(
            schema["properties"][object_field]["properties"]
        )
    assert isinstance(entry["provenance"]["evidence"], list)
    assert entry["provenance"]["evidence"]


def test_procedure_export_creates_json_files_and_is_safe_to_repeat(tmp_path):
    db = tmp_path / "source.db"
    _seed_procedure(db)

    args = [
        "--path",
        str(db),
        "--embedder",
        "hashing",
        "procedure",
        "export",
    ]
    first = _run(tmp_path, args)
    second = _run(tmp_path, args)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    files = list((tmp_path / ".howdex" / "procedures").glob("*.json"))
    assert len(files) == 1

    document = json.loads(files[0].read_text())
    assert document["format"] == "howdex.procedure"
    assert document["format_version"] == 2
    assert document["procedure"]["id"]
    assert document["procedure"]["task_signature"] == "deploy api"
    assert document["procedure"]["extraction_method"] == (
        "parameterized_lcs"
    )
    assert document["procedure"]["steps"]
    assert document["procedure"]["preconditions"] == [
        "deploy_service",
        "inspect_file",
        "run_test_suite",
    ]
    assert document["success_evidence"]["success_rate"] == 1.0
    assert document["success_evidence"]["sample_count"] == 3
    assert document["success_evidence"]["support_count"] == 3
    assert document["success_evidence"]["success_count"] == 3
    assert document["success_evidence"]["failure_count"] == 0
    assert document["success_evidence"]["confidence"] >= 0.6
    assert document["success_evidence"]["base_confidence"] >= 0.6
    assert document["success_evidence"]["feedback_success_count"] == 0
    assert document["success_evidence"]["feedback_failure_count"] == 0
    assert len(document["procedure"]["raw_supporting_examples"]) == 3
    assert "parameter_bindings" in document["procedure"]
    assert document["procedure"]["canonical_steps"]
    assert document["procedure"]["parameterized_steps"]
    assert (
        document["procedure"]["example_bindings"]
        == document["procedure"]["parameter_bindings"]
    )
    assert len(document["success_evidence"]["source_episode_ids"]) == 3
    assert document["source"]["system"] == "howdex"
    assert document["source"]["node_id"]
    assert document["timestamps"]["created_at"]
    assert "updated_at" in document["timestamps"]
    assert document["usage"]["suggestion_count"] == 0
    assert document["usage"]["unverified_use_count"] == 0


def test_procedure_import_restores_without_duplicates(tmp_path):
    source_db = tmp_path / "source.db"
    destination_db = tmp_path / "destination.db"
    export_dir = tmp_path / "portable"
    _seed_procedure(source_db)

    exported = _run(
        tmp_path,
        [
            "--path",
            str(source_db),
            "--embedder",
            "hashing",
            "procedure",
            "export",
            str(export_dir),
        ],
    )
    procedure_file = next(export_dir.glob("*.json"))

    first = _run(
        tmp_path,
        [
            "--path",
            str(destination_db),
            "--embedder",
            "hashing",
            "procedure",
            "import",
            str(procedure_file),
        ],
    )
    second = _run(
        tmp_path,
        [
            "--path",
            str(destination_db),
            "--embedder",
            "hashing",
            "procedure",
            "import",
            str(export_dir),
        ],
    )

    assert exported.returncode == 0, exported.stderr
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "1 unchanged" in second.stdout

    restored = Howdex(path=destination_db, embedder="hashing")
    try:
        procedures = restored.list_procedures()
        assert len(procedures) == 1
        assert procedures[0].task_signature == "deploy api"
        assert procedures[0].steps[-1]["action"] == "deploy_service"
        assert procedures[0].support_count == 3
        assert procedures[0].confidence >= 0.6
    finally:
        restored.close()


def test_portable_procedure_preserves_verification_receipts(tmp_path):
    source_db = tmp_path / "source.db"
    destination_db = tmp_path / "destination.db"
    export_dir = tmp_path / "portable"
    _seed_procedure(source_db)
    source = Howdex(path=source_db, embedder="hashing")
    procedure = source.list_procedures()[0]
    source.attach_receipt(
        procedure.id,
        {
            "receipt_type": "test",
            "status": "pass",
            "command": "pytest -q",
            "digest": "sha256:portable",
        },
    )
    source.export_procedures(export_dir)
    source.close()

    procedure_file = next(export_dir.glob("*.json"))
    document = json.loads(procedure_file.read_text())
    assert document["verification"]["status"] == "verified"
    assert len(document["verification"]["receipts"]) == 1

    destination = Howdex(path=destination_db, embedder="hashing")
    first = destination.import_procedures(procedure_file)
    second = destination.import_procedures(procedure_file)
    restored = destination.list_procedures()[0]

    assert first["imported"] == 1
    assert second["unchanged"] == 1
    assert len(destination.list_receipts(restored.id)) == 1
    assert destination.procedure_verification_status(restored.id) == "verified"
    destination.close()


def test_v1_portable_procedure_remains_importable(tmp_path):
    source_db = tmp_path / "source.db"
    destination_db = tmp_path / "destination.db"
    export_dir = tmp_path / "portable"
    _seed_procedure(source_db)

    _run(
        tmp_path,
        [
            "--path",
            str(source_db),
            "--embedder",
            "hashing",
            "procedure",
            "export",
            str(export_dir),
        ],
    )
    procedure_file = next(export_dir.glob("*.json"))
    document = json.loads(procedure_file.read_text())
    document["format_version"] = 1
    document["procedure"].pop("raw_supporting_examples", None)
    document["procedure"].pop("parameter_bindings", None)
    for field in (
        "support_count",
        "success_count",
        "failure_count",
        "confidence",
        "base_confidence",
        "feedback_success_count",
        "feedback_failure_count",
        "source_episode_ids",
    ):
        document["success_evidence"].pop(field, None)
    document["usage"].pop("suggestion_count", None)
    document["usage"].pop("unverified_use_count", None)
    procedure_file.write_text(json.dumps(document))

    imported = _run(
        tmp_path,
        [
            "--path",
            str(destination_db),
            "--embedder",
            "hashing",
            "procedure",
            "import",
            str(procedure_file),
        ],
    )

    assert imported.returncode == 0, imported.stderr
    restored = Howdex(path=destination_db, embedder="hashing")
    try:
        procedure = restored.get_procedure("deploy api")
        assert procedure is not None
        assert procedure.confidence == procedure.success_rate
        assert procedure.base_confidence == procedure.confidence
        assert procedure.support_count == procedure.sample_count
        assert procedure.failure_count == (
            procedure.support_count - procedure.success_count
        )
    finally:
        restored.close()


def test_codex_publish_creates_manifest_and_procedure_artifacts(tmp_path):
    db = tmp_path / "source.db"
    _seed_procedure(db)

    init_args = ["codex", "init"]
    first_init = _run(tmp_path, init_args)
    second_init = _run(tmp_path, init_args)
    publish_args = [
        "--path",
        str(db),
        "--embedder",
        "hashing",
        "codex",
        "publish",
    ]
    first_publish = _run(tmp_path, publish_args)
    second_publish = _run(tmp_path, publish_args)

    assert first_init.returncode == 0, first_init.stderr
    assert second_init.returncode == 0, second_init.stderr
    assert first_publish.returncode == 0, first_publish.stderr
    assert second_publish.returncode == 0, second_publish.stderr

    codex = tmp_path / ".howdex" / "codex"
    manifest = json.loads((codex / "manifest.json").read_text())
    files = list((codex / "procedures").glob("*.json"))
    assert manifest["format"] == "howdex.codex"
    assert manifest["format_version"] == 1
    assert manifest["procedure_count"] == 1
    assert len(files) == 1
    entry = json.loads(files[0].read_text(encoding="utf-8"))
    _assert_public_codex_entry(entry)
    assert entry["title"] == "deploy api"
    assert entry["status"] == "candidate"
    assert entry["status"] is not None
    assert entry["verification"]["status"] == "required"
    assert "format" not in entry


def test_codex_publish_candidate_for_receipt_without_inspectable_proof(tmp_path):
    db = tmp_path / "source.db"
    _seed_procedure(db)
    mem = Howdex(path=db, embedder="hashing")
    try:
        procedure = mem.list_procedures()[0]
        mem.attach_receipt(
            procedure.id,
            {
                "receipt_type": "test",
                "status": "pass",
                "command": "pytest -q",
            },
        )
        published = mem.publish_codex(tmp_path / "codex")
    finally:
        mem.close()

    entry = json.loads(published["files"][0].read_text(encoding="utf-8"))
    _assert_public_codex_entry(entry)
    assert entry["status"] == "candidate"
    assert entry["verification"]["status"] == "required"


def test_codex_publish_verified_only_with_verified_receipt(tmp_path):
    db = tmp_path / "source.db"
    _seed_procedure(db)
    mem = Howdex(path=db, embedder="hashing")
    try:
        procedure = mem.list_procedures()[0]
        mem.verify_procedure(
            procedure.id,
            verifier_type="test",
            verifier_command="pytest -q",
            expected_signal="passed",
            observed_signal="338 passed",
            exit_code=0,
        )
        published = mem.publish_codex(tmp_path / "codex")
    finally:
        mem.close()

    entry = json.loads(published["files"][0].read_text(encoding="utf-8"))
    _assert_public_codex_entry(entry)
    assert entry["status"] == "verified"
    verification = entry["verification"]
    assert verification["expected_signal"] == "passed"
    assert verification["status"] == "verified"
    assert verification["verifier_command"] == "pytest -q"
    assert verification["verifier_type"] == "test"
    # The publish_codex -> codex lint round-trip fix requires verified
    # entries to carry receipt material so codex lint accepts them.
    assert verification["receipt_id"]
    assert isinstance(verification["receipts"], list) and verification["receipts"]


def test_codex_pull_imports_another_local_codex_idempotently(tmp_path):
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    source_db = source_root / "source.db"
    destination_db = destination_root / "destination.db"
    codex = source_root / ".howdex" / "codex"
    _seed_procedure(source_db, task="repair checkout")

    published = _run(
        source_root,
        [
            "--path",
            str(source_db),
            "--embedder",
            "hashing",
            "codex",
            "publish",
        ],
    )
    pull_args = [
        "--path",
        str(destination_db),
        "--embedder",
        "hashing",
        "codex",
        "pull",
        str(codex),
    ]
    first_pull = _run(destination_root, pull_args)
    second_pull = _run(destination_root, pull_args)

    assert published.returncode == 0, published.stderr
    assert first_pull.returncode == 0, first_pull.stderr
    assert second_pull.returncode == 0, second_pull.stderr
    assert "1 unchanged" in second_pull.stdout

    destination = Howdex(path=destination_db, embedder="hashing")
    try:
        procedures = destination.list_procedures()
        assert len(procedures) == 1
        assert procedures[0].task_signature == "repair checkout"
    finally:
        destination.close()
