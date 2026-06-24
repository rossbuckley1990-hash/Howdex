from __future__ import annotations

import importlib
import os


def test_dry_run_requires_no_openai(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("HOWDEX_TRANSFER_DRY_RUN", "1")
    module = importlib.import_module("cross_model_verified_transfer_test")

    rows, bundle, guidance = module.dry_run_rows(trials=2, workdir=tmp_path)

    assert rows
    assert all("DRY RUN" in row.verdict for row in rows)
    assert bundle.codex_entry_path.is_file()
    assert "HOWDEX PROCEDURAL MEMORY" in guidance


def test_codex_export_import_path_used(tmp_path):
    module = importlib.import_module("cross_model_verified_transfer_test")

    bundle = module.export_import_via_codex(tmp_path)

    assert bundle.codex_path.is_dir()
    assert bundle.codex_entry_path.parent.name == "procedures"
    assert bundle.codex_entry_status == "verified"
    assert bundle.student_memory.list_procedures()
    bundle.teacher_memory.close()
    bundle.student_memory.close()


def test_receipt_required_for_verified_status(tmp_path):
    from howdex import Howdex
    from howdex.core.types import Procedure

    module = importlib.import_module("cross_model_verified_transfer_test")
    memory = Howdex(path=tmp_path / "memory.db", embedder="hashing")
    procedure = Procedure(
        id="unverified-transfer",
        task_signature="recover docker health",
        steps=[{"action": "inspect runtime"}],
        confidence=0.8,
    )
    memory.store.put_procedure(dict(procedure.__dict__))

    assert module.receipt_required_for_verified_transfer(memory, procedure.id) is False
    memory.verify_procedure(
        procedure.id,
        verifier_type="http_health",
        verifier_command="curl /health",
        expected_signal="healthy",
        observed_signal="HTTP 200 healthy",
        exit_code=0,
    )
    assert module.receipt_required_for_verified_transfer(memory, procedure.id) is True
    memory.close()


def test_no_source_paste_detection():
    module = importlib.import_module("cross_model_verified_transfer_test")

    assert module.source_pasted_in_guidance("Use docker compose logs, then verify /health.") is False
    assert module.source_pasted_in_guidance("```python\nimport os\n```") is True
    assert module.source_pasted_in_guidance("FROM python:3.12-alpine") is True


def test_control_treatment_base_framing_identical(tmp_path):
    module = importlib.import_module("cross_model_verified_transfer_test")
    bundle = module.export_import_via_codex(tmp_path)
    guidance = module.render_transfer_guidance(bundle.student_memory)

    control, treatment = module.build_transfer_prompts(guidance)

    assert control.base_prompt == treatment.base_prompt
    assert "No prior Howdex procedural memory" in control.memory_section
    assert "Prior learned Howdex procedural memory" in treatment.memory_section
    bundle.teacher_memory.close()
    bundle.student_memory.close()


def test_output_schema_has_required_fields(tmp_path):
    module = importlib.import_module("cross_model_verified_transfer_test")

    rows, bundle, _guidance = module.dry_run_rows(trials=1, workdir=tmp_path)
    payload = module.output_schema(rows)

    required = {
        "condition",
        "teacher",
        "student",
        "trials",
        "successes",
        "success_rate",
        "avg_attempts",
        "source_pasted",
        "verified_receipt",
        "verdict",
    }
    assert payload
    assert required <= payload[0].keys()
    assert any(row["condition"] == "cross_model_transfer" for row in payload)
    assert any(row["imported_through_codex"] for row in payload)
    bundle.teacher_memory.close()
    bundle.student_memory.close()
