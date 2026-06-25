"""Deterministic ingestion middleware and logging integration tests."""

from __future__ import annotations

import json

import pytest

from howdex import Howdex
from howdex.ingest import (
    ANSI_Stripper,
    IngestionPipeline,
    IngestionRecord,
    MaxBytes_Truncator,
    ProgressBar_Compressor,
    RepeatedLine_Compressor,
    Secret_Redactor,
    StackTrace_Compressor,
    default_ingestion_pipeline,
)


def _record(content: str, content_type: str = "stderr") -> IngestionRecord:
    return IngestionRecord(
        source="test-agent",
        content=content,
        content_type=content_type,
        timestamp=1.0,
    )


def test_ingestion_record_rejects_untyped_content():
    with pytest.raises(TypeError, match="content must be a string"):
        IngestionRecord(
            source="test-agent",
            content=123,  # type: ignore[arg-type]
            content_type="stdout",
        )


def test_ansi_stripper_preserves_readable_text():
    result = ANSI_Stripper().transform(
        _record("\x1b[31mError:\x1b[0m build failed")
    )

    assert result.content == "Error: build failed"
    assert result.transformations_applied == ("ANSI_Stripper",)


def test_stack_trace_compressor_keeps_first_last_and_final_error():
    content = "\n".join(
        [
            "Traceback (most recent call last):",
            *[
                f'  File "worker.py", line {index}, in run'
                for index in range(10)
            ],
            "ValueError: invalid configuration",
        ]
    )

    result = StackTrace_Compressor(
        first_lines=2,
        last_lines=2,
    ).transform(_record(content))

    assert "Traceback (most recent call last):" in result.content
    assert "ValueError: invalid configuration" in result.content
    assert "[stack trace compressed: 8 lines omitted]" in result.content
    assert 'line 5' not in result.content


def test_progress_bar_compressor_preserves_final_status():
    content = "\n".join(
        [
            "Downloading 10%",
            "Downloading 50%",
            "Downloading 100%",
            "Download complete",
        ]
    )

    result = ProgressBar_Compressor().transform(_record(content, "stdout"))

    assert result.content == "\n".join(
        [
            "[compressed 3 progress updates]",
            "Downloading 100%",
            "Download complete",
        ]
    )


def test_repeated_line_compressor_records_total_count():
    result = RepeatedLine_Compressor().transform(
        _record("waiting\nwaiting\nwaiting\nready", "stdout")
    )

    assert result.content == "waiting\n[repeated 3 times]\nready"


def test_max_bytes_truncator_preserves_both_ends_and_limit():
    content = "BEGIN-" + ("x" * 500) + "-END"

    result = MaxBytes_Truncator(max_bytes=160).transform(_record(content))

    assert result.content.startswith("BEGIN-")
    assert result.content.endswith("-END")
    assert "[truncated output:" in result.content
    assert len(result.content.encode("utf-8")) <= 160


def test_secret_redactor_removes_tokens_passwords_and_private_keys():
    sensitive = "example-sensitive-value"
    content = "\n".join(
        [
            f"Authorization: Bearer {sensitive}",
            f"authorization=Basic {sensitive}",
            f"api_key={sensitive}",
            f"password: {sensitive}",
            "-----BEGIN PRIVATE KEY-----",
            sensitive,
            "-----END PRIVATE KEY-----",
        ]
    )

    result = Secret_Redactor().transform(_record(content))

    assert sensitive not in result.content
    assert "Authorization: Bearer [REDACTED]" in result.content
    assert "authorization=Basic [REDACTED]" in result.content
    assert "api_key=[REDACTED]" in result.content
    assert "password: [REDACTED]" in result.content
    assert "[REDACTED] PRIVATE KEY" in result.content
    assert result.redaction_status == "redacted"


def test_default_pipeline_records_only_applied_transformations():
    content = "\x1b[32mworking\x1b[0m\nworking\nworking"

    result = default_ingestion_pipeline().transform(_record(content))

    assert result.content == "working\n[repeated 3 times]"
    assert result.transformations_applied == (
        "ANSI_Stripper",
        "RepeatedLine_Compressor",
    )


def test_step_logging_stores_sanitized_observation_and_error(tmp_path):
    memory = Howdex(path=tmp_path / "ingestion.db", embedder="hashing")
    sensitive = "example-sensitive-value"
    memory.start_session("run build", source="cli-agent")
    memory.log_step(
        "run tests",
        (
            "\x1b[31mFAILED\x1b[0m\n"
            f"token={sensitive}\n"
            "retrying\nretrying\nretrying"
        ),
        outcome="failure",
        error=f"Authorization: Bearer {sensitive}",
    )
    memory.end_session(
        "failure",
        error=f"password={sensitive}",
    )

    row = next(
        episode
        for episode in memory.store.query_episodes()
        if not episode["is_segment"]
    )
    step = json.loads(row["steps"])[0]
    serialized = json.dumps(row)

    assert sensitive not in serialized
    assert "\x1b" not in step["observation"]
    assert "[repeated 3 times]" in step["observation"]
    assert step["error"] == "Authorization: Bearer [REDACTED]"
    assert row["error"] == "password=[REDACTED]"
    assert step["observation_ingestion"]["transformations_applied"] == [
        "ANSI_Stripper",
        "Secret_Redactor",
        "RepeatedLine_Compressor",
    ]
    assert step["error_ingestion"]["redaction_status"] == "redacted"
    assert (
        row["provenance"]["error_ingestion"]["redaction_status"]
        == "redacted"
    )


def test_explicit_ingestion_opt_out_keeps_control_text_but_still_redacts(tmp_path):
    memory = Howdex(path=tmp_path / "opt-out.db", embedder="hashing")
    sensitive = "example-sensitive-value"
    memory.start_session("advanced capture")
    memory.log_step(
        "capture raw terminal",
        f"\x1b[31mtoken={sensitive}\x1b[0m",
        sanitize=False,
    )
    memory.end_session("success")

    row = memory.store.query_episodes()[0]
    step = json.loads(row["steps"])[0]

    assert "\x1b[31m" in step["observation"]
    assert sensitive not in step["observation"]
    assert "observation_ingestion" not in step


def test_custom_pipeline_cannot_disable_final_secret_redaction(tmp_path):
    memory = Howdex(
        path=tmp_path / "custom.db",
        embedder="hashing",
        ingestion_pipeline=IngestionPipeline(middleware=()),
    )
    sensitive = "example-sensitive-value"
    memory.start_session("custom ingestion")
    memory.log_step("run command", f"password={sensitive}")
    memory.end_session("success")

    row = memory.store.query_episodes()[0]
    step = json.loads(row["steps"])[0]

    assert sensitive not in step["observation"]
    assert step["observation"] == "password=[REDACTED]"
    assert step["observation_ingestion"]["redaction_status"] == "redacted"
    assert step["observation_ingestion"]["transformations_applied"] == [
        "Secret_Redactor"
    ]
