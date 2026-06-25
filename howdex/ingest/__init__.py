"""Typed, deterministic ingestion for dirty agent and terminal output."""

from howdex.ingest.pipeline import (
    ANSI_Stripper,
    IngestionMiddleware,
    IngestionPipeline,
    IngestionRecord,
    MaxBytes_Truncator,
    ProgressBar_Compressor,
    RepeatedLine_Compressor,
    Secret_Redactor,
    StackTrace_Compressor,
    default_ingestion_pipeline,
)

__all__ = [
    "IngestionRecord",
    "IngestionMiddleware",
    "IngestionPipeline",
    "ANSI_Stripper",
    "ProgressBar_Compressor",
    "StackTrace_Compressor",
    "RepeatedLine_Compressor",
    "MaxBytes_Truncator",
    "Secret_Redactor",
    "default_ingestion_pipeline",
]
