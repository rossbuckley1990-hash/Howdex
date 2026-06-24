"""Optional OpenTelemetry helpers for Howdex observability.

This module is safe to import when OpenTelemetry is not installed. In that
case all tracing operations are deterministic no-ops.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

TRACER_NAME = "howdex"
MAX_ATTRIBUTE_LENGTH = 512
_SENSITIVE_ATTRIBUTE_KEY_PARTS = (
    "artifact_content",
    "command_output",
    "content",
    "observed_signal",
    "raw",
    "source_artifact",
    "source_code",
    "stderr",
    "stdout",
)
_SAFE_SOURCE_KEYS = {"howdex.source_episode_count"}

_TRACER_OVERRIDE: Any = None
_CURRENT_SPAN: ContextVar[Any | None] = ContextVar(
    "howdex_current_telemetry_span",
    default=None,
)


class _NoOpSpan:
    def __init__(self, name: str = "", attributes: dict[str, Any] | None = None):
        self.name = name
        self.attributes = dict(attributes or {})
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[str(key)] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append((str(name), dict(attributes or {})))

    def is_recording(self) -> bool:
        return False


class _NoOpTracer:
    def start_as_current_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> _NoOpSpan:
        return _NoOpSpan(name, attributes)


_NOOP_TRACER = _NoOpTracer()


def get_tracer() -> Any:
    """Return the OpenTelemetry tracer, or a no-op tracer when unavailable."""
    if _TRACER_OVERRIDE is not None:
        return _TRACER_OVERRIDE
    try:
        from opentelemetry import trace  # type: ignore
    except Exception:
        return _NOOP_TRACER
    try:
        return trace.get_tracer(TRACER_NAME)
    except Exception:
        return _NOOP_TRACER


def is_enabled() -> bool:
    """Return whether a real OpenTelemetry tracer provider appears active."""
    if _TRACER_OVERRIDE is not None:
        return _TRACER_OVERRIDE is not _NOOP_TRACER
    try:
        from opentelemetry import trace  # type: ignore
    except Exception:
        return False
    try:
        provider_name = type(trace.get_tracer_provider()).__name__.casefold()
    except Exception:
        return False
    return "noop" not in provider_name


@contextmanager
def span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Start a span if tracing is available; otherwise yield a no-op span."""
    tracer = get_tracer()
    safe_attributes = _safe_attributes(attributes)
    try:
        manager = tracer.start_as_current_span(
            str(name),
            attributes=safe_attributes,
        )
    except TypeError:
        manager = tracer.start_as_current_span(str(name))
    except Exception:
        manager = _NOOP_TRACER.start_as_current_span(
            str(name),
            attributes=safe_attributes,
        )

    try:
        with manager as active_span:
            active_span = active_span or manager
            for key, value in safe_attributes.items():
                set_attribute(active_span, key, value)
            token = _CURRENT_SPAN.set(active_span)
            try:
                yield active_span
            finally:
                _CURRENT_SPAN.reset(token)
    except Exception:
        raise


def emit_event(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Emit an event on the current span when one exists."""
    current = _CURRENT_SPAN.get()
    if current is None:
        try:
            from opentelemetry import trace  # type: ignore
        except Exception:
            return
        try:
            current = trace.get_current_span()
        except Exception:
            return
    if hasattr(current, "add_event"):
        try:
            current.add_event(str(name), _safe_attributes(attributes))
        except Exception:
            return


def set_attribute(span_obj: Any, key: str, value: Any) -> None:
    """Safely set one span attribute."""
    safe = _safe_value(value)
    if safe is None:
        return
    if hasattr(span_obj, "set_attribute"):
        try:
            span_obj.set_attribute(str(key), safe)
        except Exception:
            return


def _safe_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    if not attributes:
        return {}
    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        safe_key = str(key)
        if _sensitive_attribute_key(safe_key):
            safe[safe_key] = "[redacted]"
            continue
        safe_value = _safe_value(value)
        if safe_value is not None:
            safe[safe_key] = safe_value
    return safe


def _sensitive_attribute_key(key: str) -> bool:
    lowered = key.casefold()
    if lowered in _SAFE_SOURCE_KEYS:
        return False
    return any(part in lowered for part in _SENSITIVE_ATTRIBUTE_KEY_PARTS)


def _safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.replace("\n", " ").strip()
        if len(text) > MAX_ATTRIBUTE_LENGTH:
            return f"{text[:MAX_ATTRIBUTE_LENGTH]}…"
        return text
    if isinstance(value, (list, tuple)):
        items = [_safe_value(item) for item in value]
        return [item for item in items if item is not None][:20]
    return str(value)[:MAX_ATTRIBUTE_LENGTH]


__all__ = [
    "emit_event",
    "get_tracer",
    "is_enabled",
    "span",
]
