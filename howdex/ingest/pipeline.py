"""Strictly typed deterministic ingestion middleware."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, runtime_checkable

RedactionStatus = Literal["not_redacted", "redacted"]

_ANSI_RE = re.compile(
    r"""
    \x1B
    (?:
        \][^\x07\x1B]*(?:\x07|\x1B\\)
        |
        [PX^_].*?\x1B\\
        |
        \[[0-?]*[ -/]*[@-~]
        |
        [@-_]
    )
    """,
    re.VERBOSE | re.DOTALL,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PROGRESS_RE = re.compile(
    r"(?i)(?:\b\d{1,3}(?:\.\d+)?%|\b\d+\s*/\s*\d+\b|"
    r"\[[#=>.\-\s]{4,}\]|\b(?:downloading|uploading|building|installing)"
    r"\b.*\d)"
)
_STACK_START_RE = re.compile(
    r"^(?:Traceback \(most recent call last\):|"
    r"(?:[\w.$]+)?(?:Error|Exception)(?::|\s+in thread)|"
    r"panic:)",
    re.IGNORECASE,
)
_STACK_FRAME_RE = re.compile(
    r"^\s*(?:File \".+\", line \d+|at .+(?:\(.+:\d+:\d+\)|:\d+:\d+)|"
    r"Caused by:|\.{3} \d+ more)",
    re.IGNORECASE,
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_BEARER_RE = re.compile(
    r"(?i)\b(bearer\s+)([^\s\x1b]+)"
)
_AUTHORIZATION_RE = re.compile(
    r"""(?ix)
    (authorization)(\s*(?:=|:)\s*)
    (?:(bearer|basic|token)\s+)?
    ([^\s,;\x1b]+)
    """
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (
        api[-_ ]?key|access[-_ ]?key|client[-_ ]?secret|
        password|passwd|secret|token|credential
    )
    (\s*(?:=|:)\s*)
    (?:
        "[^"\r\n]*"|'[^'\r\n]*'|[^\s,;\x1b]+
    )
    """
)
_SECRET_FLAG_RE = re.compile(
    r"""(?ix)
    (
        --?(?:api[-_]?key|access[-_]?key|client[-_]?secret|
        password|passwd|secret|token|credential)
        (?:=|\s+)
    )
    ([^\s\x1b]+)
    """
)
_AUTHORIZATION_FLAG_RE = re.compile(
    r"""(?ix)
    (--?authorization(?:=|\s+))
    (?:(bearer|basic|token)\s+)?
    ([^\s\x1b]+)
    """
)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:sk[-_]|gh[pousr]_|AKIA)[A-Za-z0-9_-]{12,}\b"
)
_URI_CREDENTIAL_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")


@dataclass(frozen=True)
class IngestionRecord:
    """One typed unit of text moving through the ingestion boundary."""

    source: str
    content: str
    content_type: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    redaction_status: RedactionStatus = "not_redacted"
    transformations_applied: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise TypeError("source must be a non-empty string")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.content_type, str) or not self.content_type.strip():
            raise TypeError("content_type must be a non-empty string")
        if isinstance(self.timestamp, bool) or not isinstance(
            self.timestamp,
            (int, float),
        ):
            raise TypeError("timestamp must be numeric")
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")
        if self.redaction_status not in {"not_redacted", "redacted"}:
            raise ValueError("invalid redaction_status")
        if not isinstance(self.transformations_applied, tuple) or not all(
            isinstance(item, str)
            for item in self.transformations_applied
        ):
            raise TypeError("transformations_applied must be a tuple of strings")
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "content_type", self.content_type.strip())
        object.__setattr__(self, "timestamp", float(self.timestamp))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def audit_metadata(self) -> dict[str, Any]:
        """Return safe ingestion metadata suitable for episode step JSON."""
        return {
            "source": self.source,
            "content_type": self.content_type,
            "timestamp": self.timestamp,
            "redaction_status": self.redaction_status,
            "transformations_applied": list(self.transformations_applied),
        }


@runtime_checkable
class IngestionMiddleware(Protocol):
    """The deterministic ingestion middleware contract."""

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        """Return a transformed copy of ``record``."""


@dataclass(frozen=True)
class IngestionPipeline:
    """Apply middleware in a fixed, inspectable order."""

    middleware: tuple[IngestionMiddleware, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.middleware, tuple):
            raise TypeError("middleware must be a tuple")
        if not all(
            isinstance(item, IngestionMiddleware)
            for item in self.middleware
        ):
            raise TypeError("all middleware must implement transform(record)")

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        transformed = record
        for middleware in self.middleware:
            transformed = middleware.transform(transformed)
            if not isinstance(transformed, IngestionRecord):
                raise TypeError("ingestion middleware must return IngestionRecord")
        return transformed

    def ingest(
        self,
        content: str,
        *,
        source: str,
        content_type: str,
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionRecord:
        return self.transform(
            IngestionRecord(
                source=source,
                content=content,
                content_type=content_type,
                timestamp=time.time() if timestamp is None else timestamp,
                metadata=dict(metadata or {}),
            )
        )


@dataclass(frozen=True)
class ANSI_Stripper:
    """Remove ANSI terminal sequences and unreadable control bytes."""

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        content = _ANSI_RE.sub("", record.content)
        content = _CONTROL_RE.sub("", content)
        return _with_content(record, content, type(self).__name__)


@dataclass(frozen=True)
class ProgressBar_Compressor:
    """Collapse contiguous terminal progress updates while keeping the last."""

    minimum_updates: int = 2

    def __post_init__(self) -> None:
        if self.minimum_updates < 2:
            raise ValueError("minimum_updates must be at least 2")

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        lines = record.content.splitlines()
        output: list[str] = []
        index = 0
        changed = False
        while index < len(lines):
            if not _is_progress_line(lines[index]):
                output.append(lines[index])
                index += 1
                continue
            end = index + 1
            while end < len(lines) and _is_progress_line(lines[end]):
                end += 1
            run = lines[index:end]
            if len(run) >= self.minimum_updates:
                output.append(f"[compressed {len(run)} progress updates]")
                output.append(run[-1])
                changed = True
            else:
                output.extend(run)
            index = end
        content = "\n".join(output)
        if record.content.endswith(("\n", "\r")) and content:
            content += "\n"
        return _with_content(
            record,
            content if changed else record.content,
            type(self).__name__,
        )


@dataclass(frozen=True)
class StackTrace_Compressor:
    """Keep the beginning and end of long stack traces."""

    first_lines: int = 4
    last_lines: int = 4

    def __post_init__(self) -> None:
        if self.first_lines < 1 or self.last_lines < 1:
            raise ValueError("stack trace line limits must be positive")

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        lines = record.content.splitlines()
        frame_indexes = [
            index
            for index, line in enumerate(lines)
            if _STACK_FRAME_RE.search(line)
        ]
        if len(frame_indexes) < 3:
            return record
        starts = [
            index
            for index, line in enumerate(lines)
            if _STACK_START_RE.search(line)
        ]
        start = starts[0] if starts else max(0, frame_indexes[0] - 1)
        block = lines[start:]
        keep = self.first_lines + self.last_lines
        if len(block) <= keep + 1:
            return record
        omitted = len(block) - keep
        compressed = [
            *lines[:start],
            *block[: self.first_lines],
            f"[stack trace compressed: {omitted} lines omitted]",
            *block[-self.last_lines :],
        ]
        content = "\n".join(compressed)
        if record.content.endswith(("\n", "\r")):
            content += "\n"
        return _with_content(record, content, type(self).__name__)


@dataclass(frozen=True)
class RepeatedLine_Compressor:
    """Collapse consecutive identical non-empty lines."""

    minimum_repetitions: int = 2

    def __post_init__(self) -> None:
        if self.minimum_repetitions < 2:
            raise ValueError("minimum_repetitions must be at least 2")

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        lines = record.content.splitlines()
        output: list[str] = []
        index = 0
        changed = False
        while index < len(lines):
            line = lines[index]
            end = index + 1
            while end < len(lines) and lines[end] == line:
                end += 1
            count = end - index
            output.append(line)
            if line and count >= self.minimum_repetitions:
                output.append(f"[repeated {count} times]")
                changed = True
            elif not line and count > 1:
                output.extend([""] * (count - 1))
            index = end
        content = "\n".join(output)
        if record.content.endswith(("\n", "\r")) and content:
            content += "\n"
        return _with_content(
            record,
            content if changed else record.content,
            type(self).__name__,
        )


@dataclass(frozen=True)
class MaxBytes_Truncator:
    """Bound UTF-8 payload size while retaining both ends."""

    max_bytes: int = 65_536

    def __post_init__(self) -> None:
        if self.max_bytes < 128:
            raise ValueError("max_bytes must be at least 128")

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        encoded = record.content.encode("utf-8")
        if len(encoded) <= self.max_bytes:
            return record
        marker = (
            f"[truncated output: original_bytes={len(encoded)}; "
            f"max_bytes={self.max_bytes}]"
        )
        marker_bytes = marker.encode("utf-8")
        available = self.max_bytes - len(marker_bytes) - 2
        prefix_budget = available // 2
        suffix_budget = available - prefix_budget
        prefix = encoded[:prefix_budget].decode("utf-8", errors="ignore")
        suffix = encoded[-suffix_budget:].decode("utf-8", errors="ignore")
        content = f"{prefix}\n{marker}\n{suffix}"
        while len(content.encode("utf-8")) > self.max_bytes:
            suffix = suffix[1:]
            content = f"{prefix}\n{marker}\n{suffix}"
        return _with_content(record, content, type(self).__name__)


@dataclass(frozen=True)
class Secret_Redactor:
    """Redact common credentials without retaining their original values."""

    replacement: str = "[REDACTED]"

    def transform(self, record: IngestionRecord) -> IngestionRecord:
        content = _PRIVATE_KEY_RE.sub(
            f"{self.replacement} PRIVATE KEY",
            record.content,
        )
        content = _AUTHORIZATION_RE.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}"
                + (
                    f"{match.group(3)} "
                    if match.group(3)
                    else ""
                )
                + self.replacement
            ),
            content,
        )
        content = _AUTHORIZATION_FLAG_RE.sub(
            lambda match: (
                match.group(1)
                + (
                    f"{match.group(2)} "
                    if match.group(2)
                    else ""
                )
                + self.replacement
            ),
            content,
        )
        content = _BEARER_RE.sub(rf"\1{self.replacement}", content)
        content = _SECRET_FLAG_RE.sub(rf"\1{self.replacement}", content)
        content = _SECRET_ASSIGNMENT_RE.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}{self.replacement}"
            ),
            content,
        )
        content = _KNOWN_TOKEN_RE.sub(self.replacement, content)
        content = _URI_CREDENTIAL_RE.sub(
            rf"\1{self.replacement}\3",
            content,
        )
        if content == record.content:
            return record
        return _with_content(
            record,
            content,
            type(self).__name__,
            redacted=True,
        )


def default_ingestion_pipeline(
    *,
    max_bytes: int = 65_536,
) -> IngestionPipeline:
    """Return the default local-only sanitization pipeline."""
    return IngestionPipeline(
        middleware=(
            ANSI_Stripper(),
            Secret_Redactor(),
            ProgressBar_Compressor(),
            StackTrace_Compressor(),
            RepeatedLine_Compressor(),
            MaxBytes_Truncator(max_bytes=max_bytes),
        )
    )


def _with_content(
    record: IngestionRecord,
    content: str,
    transformation: str,
    *,
    redacted: bool = False,
) -> IngestionRecord:
    if content == record.content:
        return record
    transformations = record.transformations_applied
    if transformation not in transformations:
        transformations = (*transformations, transformation)
    return replace(
        record,
        content=content,
        redaction_status=(
            "redacted" if redacted else record.redaction_status
        ),
        transformations_applied=transformations,
    )


def _is_progress_line(line: str) -> bool:
    return bool(_PROGRESS_RE.search(line))
